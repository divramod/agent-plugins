#!/usr/bin/env python3
"""Where this checkout's handoff lives, and its stamp (hal2 plan 0206; hal2's decision record `record-formats`).

  where.py [--json]     the handoff's path below the repository root (--json: file, form, plan, decisions, questions)
  where.py --apply      the store home: take the edit folder's changes (the handoff, the ledgers) into the plan store
                        and run its sync trigger; prints nothing in the files home
  where.py --stamp      the same, after writing a missing `plans/<plan>/handoff.md` from the plan skill's template
                        and setting its `updated`, `branch`, `at` (the short sha of HEAD) and `status`; the handoff of
                        a plan of a masterplan also gets, under its heading, the line `Row <n> of [masterplan
                        <NNNN>](../<slug>/plan.md)` (hal2 plan 0275 step 5): written when missing, its row and link
                        kept current, the words after the link left as they are

The current plan (the `CURRENT_PLAN` pointer) in the record format (its plan.md has front matter with a `type`): the
handoff is the plan's committed `plans/<plan>/handoff.md` (form `record`), the decisions index is the plan's ledger
`decisions.md`. A legacy plan, work without a plan and a servant's worktree (`plans/LEAD`: the plan's files are the
foreman's): the gitignored root `HANDOFF.md` with its own Decisions section (form `legacy`). `--stamp` changes nothing
of a legacy handoff: its header line is written by hand.

In the store home (hal2 plan 0409: `hal2-cli-plans home` says `store`, no plan file in the tree) the plan's files are
a copy in the farm's edit folder outside the tree (plan skill's planhome.py, a stable view), rendered unless the copy
has edits of its own: `file`, `plan`, `decisions`, `questions` are absolute paths there, and `--apply` (which
commit-handoff.sh runs) takes them into the store instead of a commit. A legacy handoff there is no root file either:
the checkout's HANDOFF.md and QUESTIONS.md live in the store (scope `checkout:<branch>`, hal2 plan 0409 step 12),
rendered beside the edit folder (`hal2-cli-plans checkout render`) and taken back by `--apply`.

Exit 0 printed, 1 the store refused the edit, 2 git missing.
"""

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import sibling  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)
sys.path.insert(0, str(sibling("plan") / "scripts"))

import checker  # noqa: E402  (the plan skill's)
import envelope  # noqa: E402
import folder  # noqa: E402
import masterplan  # noqa: E402
import planhome  # noqa: E402
import pointers  # noqa: E402  (CURRENT_PLAN and LEAD: the git dir's, else plans/)

ROOT_FILE = "HANDOFF.md"
MASTER_LINE = re.compile(r"^Row \S+ of \[masterplan \d{4}\]\(\.\./[^)\s]+/plan\.md\)")


def git(root: Path | None, *args: str) -> str:
    cmd = ["git", *(["-C", str(root)] if root else []), *args]
    return subprocess.run(cmd, text=True, capture_output=True).stdout.strip()


def store_view(root: Path) -> "planhome.View | None":
    """The store home's edit folder with the current plan (and its masterplan) rendered, registered as `root`'s plan
    folders; None in the files home."""
    info = planhome.home(root)
    if info is None:
        return None
    view = planhome.View(root, info, stable=True)
    if (slug := planhome.pointer_slug(root)) and (folder := view.render(slug)):
        parent = masterplan.parent_of((view.dir / folder / "plan.md").read_text())
        if parent is not None:
            view.render(str(parent))
    planhome.register(root, view.dir)
    return view


def current_plan(root: Path) -> Path | None:
    """The plan.md the CURRENT_PLAN pointer (the git dir's, else the old one in `plans/`) names; None for a shot, a task name or no pointer. In the store home the edit
    folder's copy (rendered on the first call)."""
    if planhome.view_of(root) is None:
        store_view(root)
    slug = pointers.read(root, pointers.CURRENT_PLAN)
    plan = planhome.plans_dir(root) / slug / "plan.md"
    return plan if slug and "/" not in slug and plan.is_file() else None


def locate(root: Path) -> dict:
    plan = current_plan(root)
    record = bool(plan) and folder.is_record(plan.read_text()) and not pointers.exists(root, pointers.LEAD)
    in_store = planhome.view_of(root) is not None
    rel = lambda name: str(plan.parent / name) if in_store else str((plan.parent / name).relative_to(root))  # noqa: E731
    copy = checkout_copy(root) if in_store and not record else None
    return {"file": rel("handoff.md") if record else str(copy / ROOT_FILE) if copy else ROOT_FILE,
            "form": "record" if record else "legacy",
            "plan": rel("plan.md") if plan else None,
            "decisions": rel("decisions.md") if record else None,
            "questions": rel("questions.md") if plan else str(copy / "QUESTIONS.md") if copy else "plans/questions.md"}


def checkout_copy(root: Path) -> Path | None:
    """The store home's root HANDOFF.md and QUESTIONS.md (scope `checkout:<branch>`), rendered into a folder outside
    the tree (`hal2-cli-plans checkout render`; `--apply` takes them back); None when the CLI cannot say."""
    try:
        done = planhome.run(root, "checkout", "render", "--repo", str(root))
    except planhome.HomeError:
        return None
    return Path(done["dir"]) if done.get("dir") else None


def masterplan_line(plan: Path) -> str | None:
    """`Row <n> of [masterplan <NNNN>](../<slug>/plan.md)` for a plan of a masterplan: the row that links the plan
    at `plan` there. None for any other plan, and when this checkout holds no such masterplan or row."""
    parent = masterplan.parent_of(plan.read_text())
    row = masterplan.row_of(plan, parent) if parent is not None else None
    if row is None:
        return None
    home = masterplan.find(plan.parent.parent, parent).parent.name
    return f"Row {row} of [masterplan {parent:04d}](../{home}/plan.md)"


def with_masterplan_line(text: str, line: str) -> str:
    """A handoff's text with `line` between its heading and its first section: a line that starts with such a link
    is replaced up to the link's end (the words after it are the writer's and stay), else `line` is written as a
    paragraph of its own."""
    front, body = envelope.split(text)
    lines = body.split("\n")
    h1 = next((i for i, found in enumerate(lines) if found.startswith("# ")), None)
    if h1 is None:
        return text
    end = next((i for i in range(h1 + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    for i in range(h1 + 1, end):
        if found := MASTER_LINE.match(lines[i]):
            lines[i] = line + lines[i][found.end():]
            break
    else:
        lines[h1 + 1:h1 + 1] = ["", line + "."]
    return text[:len(text) - len(body)] + "\n".join(lines)


def stamp(root: Path, where: dict) -> None:
    """A record handoff exists and says when, on which branch and at which commit it was written; the handoff of a
    plan of a masterplan names its row there."""
    if where["form"] != "record":
        return
    plan = root / where["plan"]
    folder.scaffold_existing(root, plan)
    path = root / where["file"]
    text = path.read_text()
    closed = envelope.get(plan.read_text(), "status") != "open"
    for key, value in (("updated", dt.date.today().isoformat()),
                       ("branch", folder.raw(git(root, "branch", "--show-current") or "none")),
                       ("at", envelope.quote(git(root, "rev-parse", "--short", "HEAD") or "none")),
                       ("status", "closed" if closed else "open")):
        text = envelope.set_key(text, key, value)
    if line := masterplan_line(plan):
        text = with_masterplan_line(text, line)
    path.write_text(text)


def apply(root: Path) -> int:
    """`--apply`: the edit folder into the store and the handoff's sync trigger; nothing in the files home."""
    info = planhome.home(root)
    if info is None:
        return 0
    try:
        done = planhome.View(root, info, stable=True).apply()
        checkout = planhome.run(root, "checkout", "apply", "--repo", str(root))
    except planhome.HomeError as error:
        print(f"where.py: {error}", file=sys.stderr)
        return 1
    done = {**(done or {}), "checkout": {k: checkout.get(k) for k in ("handoff", "questions")}}
    synced = planhome.sync(root, "handoff")
    print(json.dumps({"applied": done, "synced": synced}))
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--stamp", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--root", type=Path, help="the checkout (default: the one of the current directory)")
    args = ap.parse_args(argv)
    if not shutil.which("git"):
        print("where.py: git is missing; run install-prerequisites.sh", file=sys.stderr)
        return 2
    root = (args.root or Path(git(None, "rev-parse", "--show-toplevel") or ".")).resolve()
    if args.apply:
        return apply(root)
    where = locate(root)
    if args.stamp:
        stamp(root, where)
    print(json.dumps(where) if args.json else where["file"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
