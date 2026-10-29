"""Where a farm's daybook lives, writing it safely, and the scan of the farm's unfinished plans.

The farm root is the main checkout (the first entry of `git worktree list`), outside git the folder itself (D2).
The folder is `DAYBOOK_DIR`, else jobsearch's `daily/` when it holds `watches.yaml`, else `daybook/` (D3).
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time

LOCK_WAIT, LOCK_STALE = 5.0, 60.0
HERE = os.path.dirname(os.path.realpath(__file__))
PLAN_PY = [os.path.join(HERE, "..", "..", "plan", "scripts", "plan.py"),
           os.path.expanduser("~/.claude/skills/plan/scripts/plan.py")]


def current_plan(tree):
    """The checkout's CURRENT_PLAN: the git dir's, else the old one in `plans/` (the plan skill's pointers.py, loaded by its
    path next to plan.py; the plans/ file alone where that skill is missing). Stripped, "" for none."""
    for plan_py in PLAN_PY:
        path = os.path.join(os.path.dirname(plan_py), "pointers.py")
        if os.path.isfile(path):
            spec = importlib.util.spec_from_file_location("pointers", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.read(tree, "CURRENT_PLAN")
    try:
        return read_text(os.path.join(tree, "plans", "CURRENT_PLAN")).strip()
    except OSError:
        return ""


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class FarmError(Exception):
    pass


class LockError(Exception):
    pass


def git(args, cwd):
    try:
        res = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, check=False, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout if res.returncode == 0 else None


def worktrees(root):
    """The paths of `git worktree list`, the main checkout first; [] outside git."""
    out = git(["worktree", "list", "--porcelain"], root) or ""
    return [line[9:] for line in out.splitlines() if line.startswith("worktree ")]


def farm_root(start):
    start = os.path.abspath(start)
    if not os.path.isdir(start):
        raise FarmError(f"no such folder: {start}")
    trees = worktrees(start)
    return (trees[0] if trees else start), trees


def folder_of(root):
    if os.environ.get("DAYBOOK_DIR"):
        return os.path.abspath(os.environ["DAYBOOK_DIR"]), False
    daily = os.path.join(root, "daily")
    if os.path.isfile(os.path.join(daily, "watches.yaml")):
        return daily, True
    return os.path.join(root, "daybook"), False


def make_folder(root, folder):
    """Create the folder; a farm's own `daybook/` is excluded through `<git-common-dir>/info/exclude` once."""
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as err:
        raise FarmError(f"cannot create {folder}: {err}") from err
    if os.environ.get("DAYBOOK_DIR") or folder != os.path.join(root, "daybook"):
        return
    common = (git(["rev-parse", "--git-common-dir"], root) or "").strip()
    if not common:
        return
    exclude = os.path.join(root, common, "info", "exclude")
    text = read_text(exclude) if os.path.exists(exclude) else ""
    if "/daybook/" not in text.splitlines():
        os.makedirs(os.path.dirname(exclude), exist_ok=True)
        with open(exclude, "a", encoding="utf-8") as fh:
            fh.write(("" if not text or text.endswith("\n") else "\n") + "/daybook/\n")


class Lock:
    """`<folder>/.daybook.lock` by O_CREAT|O_EXCL; a lock older than 60 s is stale."""

    def __init__(self, folder):
        self.path = os.path.join(folder, ".daybook.lock")

    def __enter__(self):
        end = time.monotonic() + LOCK_WAIT
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.path) > LOCK_STALE:
                        os.remove(self.path)
                        continue
                except OSError:
                    continue
            if time.monotonic() > end:
                raise LockError(f"the lock {self.path} was not taken in {LOCK_WAIT:.0f} s")
            time.sleep(0.05)

    def __exit__(self, *exc):
        try:
            os.remove(self.path)
        except OSError:
            pass


def write_atomic(path, text):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".daybook-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def step_table(text):
    """(done, total, next number, next step) from a plan.md's step table (`#`, `Step`, `Status` columns)."""
    cols, rows = None, []
    for line in text.splitlines():
        if not line.startswith("|"):
            if cols and rows:
                break
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cols is None:
            if "#" in cells and "Step" in cells and "Status" in cells:
                cols = cells
        elif not all(re.fullmatch(r":?-+:?", c) for c in cells if c) and len(cells) == len(cols):
            rows.append(dict(zip(cols, cells)))
    done = [r for r in rows if r["Status"].lower().startswith("done")]
    nxt = next((r for r in rows if not r["Status"].lower().startswith("done")), None)
    return len(done), len(rows), (nxt["#"] if nxt else None), (nxt["Step"] if nxt else None)


def plan_line(label, done, total, number, step, path=None):
    head = f"- {label} ({done}/{total})"
    if number:
        head += f", next {number}: {step[:110]}"
    return head + (f" · `{path}`" if path else "")


def worktree_plans(trees, main):
    """Each worktree's CURRENT_PLAN, counted from its own plan.md (no plan.py call per worktree)."""
    out = []
    for tree in trees:
        slug = current_plan(tree)
        if not slug:
            continue
        label = "main" if tree == main else os.path.basename(tree)
        entry = {"worktree": label, "slug": slug, "path": None, "done": None, "total": None, "next": None}
        for path in (os.path.join("plans", slug, "plan.md"), os.path.join("plans", slug + ".md")):
            if os.path.isfile(os.path.join(tree, path)):
                done, total, number, step = step_table(read_text(os.path.join(tree, path)))
                entry.update(path=path, done=done, total=total,
                             next={"number": number, "step": step} if number else None)
                break
        entry["line"] = (plan_line(f"wt {label}: {slug}", entry["done"], entry["total"], number, step)
                         if entry["path"] else f"- wt {label}: {slug}")
        out.append(entry)
    return out


def plan_tool():
    override = os.environ.get("DAYBOOK_PLAN_PY")
    for path in ([override] if override else PLAN_PY):
        if os.path.isfile(path):
            return path
    return None


def main_plans(main, named):
    tool = plan_tool()
    if not tool:
        return [{"line": "- (plan.py not found: look at plans/ by hand)"}]
    res = subprocess.run([sys.executable, tool, "--root", main, "list"], capture_output=True, text=True, check=False)
    try:
        plans = json.loads(res.stdout or "[]")
    except ValueError:
        return [{"line": "- (plans not readable: run `plan.py list`)"}]
    out = []
    for plan in plans:
        done, total = plan.get("done") or 0, plan.get("total") or 0
        if plan.get("finished") or done >= total or plan.get("slug") in named:
            continue
        nxt = plan.get("next") or {}
        out.append({"worktree": None, "slug": plan["slug"], "path": plan.get("path"), "done": done, "total": total,
                    "next": {"number": nxt.get("number"), "step": nxt.get("step")} if nxt else None,
                    "line": plan_line(plan["slug"], done, total, nxt.get("number"), str(nxt.get("step") or ""),
                                      plan.get("path"))})
    return out


def scan_plans(main, trees):
    """The worktrees' current plans, then the main checkout's unfinished plans not already named (D6)."""
    if not os.path.isdir(os.path.join(main, "plans")) and not trees:
        return []
    ours = worktree_plans(trees, main)
    rest = main_plans(main, {p["slug"] for p in ours}) if os.path.isdir(os.path.join(main, "plans")) else []
    return ours + rest
