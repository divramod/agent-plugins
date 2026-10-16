#!/usr/bin/env python3
"""The questions of the session's store, printed in the Q form. No model call, read-only.

`hal2-cli-plans questions list` prints (`$HAL2_CLI_PLANS`, else the one on PATH); when it is missing or fails, q.py
prints through its own parser (handoff's `qform.py`: an old entry's inline options split onto their own lines too). A store
with malformed open questions gets one warning line after the list.

  q.py [open]       the open questions (the default)
  q.py a|answered   the answered ones
  q.py l|list       all: the open first, then the answered and dropped, each by number
  q.py ... --json   the same entries as data
  q.py --path       only the store's path, relative to the checkout
  q.py ... --repo <path>   another checkout

In the farmer's own worktree (`farmer-<repo>`) it prints the farmer's joined list instead (`farmer.py questions`): the
farmer's own questions, the log's open asks and every worktree's store; `--path` still names the own store.

The store is the current plan's `plans/<plan>/questions.md` (`plans/CURRENT_PLAN`, a slug or a path; else the plan the
root HANDOFF.md links), else the checkout's gitignored root `QUESTIONS.md`, the same entry format (the handoff
skill's `questions.py` parses it). Exit 0, 1 a store that cannot be read or parsed (one line), 2 the handoff skill's
parser is not found.
"""

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qshape  # noqa: E402  (beside this script)

SKILLS = Path(__file__).resolve().parent.parent.parent
HANDOFF_SCRIPTS = SKILLS / "handoff" / "scripts"
FARMER_SCRIPTS = SKILLS / "farmer" / "scripts"


def load_by_path(name: str, path: Path):
    """A module loaded by path under its own name, so the handoff skill's `questions` and the farmer's never clash;
    None when the file is missing or fails to import."""
    if not path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    except Exception:  # noqa: BLE001
        sys.modules.pop(name, None)
        return None
    return mod


# The Q form (CLI lookup, the one inline split of D3, the form check): handoff's qform.py (D9), loaded first under
# its own name so handoff's questions.py finds the same module when it imports it.
qform = load_by_path("qform", HANDOFF_SCRIPTS / "qform.py")
questions = load_by_path("handoff_questions", HANDOFF_SCRIPTS / "questions.py")

MODES = {"open": "open", "a": "answered", "answered": "answered", "l": "all", "list": "all"}
NONE = {"open": "no open questions", "answered": "no answered questions", "all": "no questions"}
PLAN_LINK = re.compile(r"\]\(((?:\./)?plans/[^)\s]+)/plan\.md\)")


def checkout_of(start: Path) -> Path:
    """The nearest folder at or above `start` with a `.git` (a folder, or the file of a worktree)."""
    start = start.resolve()
    for folder in (start, *start.parents):
        if (folder / ".git").exists():
            return folder
    return start


def plan_folder(root: Path) -> Path | None:
    """The folder of the current plan: what CURRENT_PLAN names, else the plan the root HANDOFF.md links."""
    current = root / "plans" / "CURRENT_PLAN"
    name = current.read_text().strip().rstrip("/") if current.is_file() else ""
    name = name.removesuffix("/plan.md").rstrip("/")
    if name:
        for candidate in (root / name, root / "plans" / name, root / "plans" / Path(name).name):
            if (candidate / "plan.md").is_file():
                return candidate
    handoff = root / "HANDOFF.md"
    m = PLAN_LINK.search(handoff.read_text()) if handoff.is_file() else None
    if m and (root / m.group(1) / "plan.md").is_file():
        return root / m.group(1)
    return None


def store_of(root: Path) -> Path:
    plan = plan_folder(root)
    return plan / "questions.md" if plan else root / "QUESTIONS.md"


def load(path: Path) -> list[dict]:
    """The entries of the store: open first, then answered and dropped, each by number. Raises ValueError."""
    if not path.is_file():
        return []
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError) as err:
        raise ValueError(f"cannot read: {err}") from err
    entries, problems = questions.parse(text)
    problems = questions.check(entries, problems)
    if problems:
        raise ValueError(problems[0] + (f" (and {len(problems) - 1} more)" if len(problems) > 1 else ""))
    raw = questions.raw_entries(text)
    for e in entries:
        e["question"], e["closed"] = raw[e["n"]]["question"], raw[e["n"]]["closed"]
    return sorted(entries, key=lambda e: (e["state"] != "open", e["n"]))


def pick(entries: list[dict], mode: str) -> list[dict]:
    if mode == "all":
        return entries
    return [e for e in entries if e["state"] == mode]


def render_entry(e: dict) -> str:
    text, options, _ = qform.lines_of(e["question"])
    first, *rest = text.split("\n")
    lines = [f"Q{e['n']}: {first}".rstrip(), *rest, *options]
    if e["state"] == "answered":
        lines.append(f"Answer ({e['closed']}): {e['a']}")
    elif e["state"] == "dropped":
        lines.append(f"Dropped ({e['closed']})" + (f": {e['a']}" if e["a"] else ""))
    return "\n".join(lines)


def render(entries: list[dict], mode: str, store: str) -> str:
    """The head line, then every entry of the mode as it stands, a blank line between; one line when none."""
    chosen = pick(entries, mode)
    if not chosen:
        return NONE[mode]
    n = len(chosen)
    if mode == "all":
        head = f"{n} question{'s' * (n != 1)}, {sum(e['state'] == 'open' for e in chosen)} open ({store})"
    else:
        head = f"{n} {mode} question{'s' * (n != 1)} ({store})"
    return head + "\n\n" + "\n\n".join(render_entry(e) for e in chosen)


def cli_path() -> str | None:
    """The CLI: `$HAL2_CLI_PLANS` when set (a missing file means none), else `hal2-cli-plans` on PATH."""
    return qform.binary() if qform else None


def run_cli(cli: str, root: Path, *args: str, ok=(0,)) -> subprocess.CompletedProcess | None:
    try:
        run = subprocess.run([cli, "questions", *args], cwd=root, text=True, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return run if run.returncode in ok else None


def cli_problems(cli: str, root: Path, rel: str) -> list[dict] | None:
    """The store's problems from `questions check --json` ({n, message}); None when the CLI cannot say."""
    run = run_cli(cli, root, "check", "--json", "--store", rel, ok=(0, 1))
    try:
        return json.loads(run.stdout)["problems"] if run else None
    except (ValueError, KeyError, TypeError):
        return None


def via_cli(args, root: Path, rel: str, mode: str) -> int | None:
    """Print through `hal2-cli-plans questions list`; None when the CLI is missing or fails (then q.py's own path
    prints). `questions check --json` names the store's problems: a malformed option form of an open agent entry
    (told by its entry, see `qshape.is_form_problem`) becomes one warning line after the list; any other problem
    breaks the store as before: one line naming the file, exit 1."""
    cli = cli_path()
    if not cli:
        return None
    printed = run_cli(cli, root, "list", f"--{mode}", "--json" if args.json else "--markdown", "--store", rel)
    problems = cli_problems(cli, root, rel)
    if printed is None or problems is None or not printed.stdout.strip():
        return None
    if problems:
        data = run_cli(cli, root, "list", "--all", "--json", "--store", rel)
        try:
            entries = json.loads(data.stdout)["entries"]
        except (AttributeError, ValueError, KeyError):
            return None
        broken = [p for p in problems if not qshape.is_form_problem(p["n"], entries)]
        if broken:
            print(f"{rel}: {broken[0]['message']}" + (f" (and {len(problems) - 1} more)" if len(problems) > 1 else ""))
            return 1
    out = printed.stdout
    sys.stdout.write(out if out.endswith("\n") else out + "\n")
    if problems and not args.json:
        print(qshape.warning([(p["n"], p["message"]) for p in problems]))
    return 0


def in_farmer_slot(root: Path) -> bool:
    """The checkout is the farmer's own worktree `farmer-<repo>`: `/q` there is the farmer's joined list (D14)."""
    return root.name.startswith("farmer-") and (FARMER_SCRIPTS / "questions.py").is_file()


def hand_over(args, root: Path) -> int | None:
    """The farmer's joined list (`farmer.py questions`) in the farmer's worktree; None when it cannot be loaded."""
    if str(FARMER_SCRIPTS) not in sys.path:
        sys.path.append(str(FARMER_SCRIPTS))
    farmer = load_by_path("farmer_questions", FARMER_SCRIPTS / "questions.py")
    return farmer.joined(args.mode, args.json, str(root)) if farmer else None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mode", nargs="?", default="open", choices=sorted(MODES))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--path", action="store_true")
    ap.add_argument("--repo", default=".")
    args = ap.parse_args(argv)
    root = checkout_of(Path(args.repo).expanduser())
    path = store_of(root)
    rel = str(path.relative_to(root))
    if args.path:
        print(rel)
        return 0
    if in_farmer_slot(root):
        done = hand_over(args, root)
        if done is not None:
            return done
    mode = MODES[args.mode]
    done = via_cli(args, root, rel, mode)
    if done is not None:
        return done
    if questions is None or qform is None:
        print(f"q: no hal2-cli-plans, and the handoff skill's questions.py is not found in {HANDOFF_SCRIPTS}", file=sys.stderr)
        return 2
    try:
        entries = load(path)
    except ValueError as err:
        print(f"{rel}: {err}")
        return 1
    if args.json:
        decided = qshape.decisions(path.read_text())
        chosen = [qshape.json_entry(qform, e, decided.get(e["n"])) for e in pick(entries, mode)]
        bad = [{"n": e["n"], "message": why} for e in entries if (why := qshape.form_problem(qform, e))]
        print(json.dumps({"store": rel, "mode": mode, "entries": chosen, "problems": bad}, indent=2))
    else:
        print(render(entries, mode, rel))
        bad = [(e["n"], why) for e in entries if (why := qshape.form_problem(qform, e))]
        if bad:
            print(qshape.warning(bad))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
