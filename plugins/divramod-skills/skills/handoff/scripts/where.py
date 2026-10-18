#!/usr/bin/env python3
"""Where this checkout's handoff lives, and its stamp (hal2 plan 0206; hal2's decision record `record-formats`).

  where.py [--json]     the handoff's path below the repository root (--json: file, form, plan, decisions, questions)
  where.py --stamp      the same, after writing a missing `plans/<plan>/handoff.md` from the plan skill's template
                        and setting its `updated`, `branch`, `at` (the short sha of HEAD) and `status`; the handoff of
                        a plan of a masterplan also gets, under its heading, the line `Row <n> of [masterplan
                        <NNNN>](../<slug>/plan.md)` (hal2 plan 0275 step 5): written when missing, its row and link
                        kept current, the words after the link left as they are

The current plan (`plans/CURRENT_PLAN`) in the record format (its plan.md has front matter with a `type`): the
handoff is the plan's committed `plans/<plan>/handoff.md` (form `record`), the decisions index is the plan's ledger
`decisions.md`. A legacy plan, work without a plan and a servant's worktree (`plans/LEAD`: the plan's files are the
foreman's): the gitignored root `HANDOFF.md` with its own Decisions section (form `legacy`). `--stamp` changes nothing
of a legacy handoff: its header line is written by hand.

Exit 0 printed, 2 git missing.
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

ROOT_FILE = "HANDOFF.md"
MASTER_LINE = re.compile(r"^Row \S+ of \[masterplan \d{4}\]\(\.\./[^)\s]+/plan\.md\)")


def git(root: Path | None, *args: str) -> str:
    cmd = ["git", *(["-C", str(root)] if root else []), *args]
    return subprocess.run(cmd, text=True, capture_output=True).stdout.strip()


def current_plan(root: Path) -> Path | None:
    """The plan.md `plans/CURRENT_PLAN` names; None for a shot, a task name or no pointer."""
    pointer = root / "plans" / "CURRENT_PLAN"
    slug = pointer.read_text().strip() if pointer.is_file() else ""
    plan = root / "plans" / slug / "plan.md"
    return plan if slug and "/" not in slug and plan.is_file() else None


def locate(root: Path) -> dict:
    plan = current_plan(root)
    record = bool(plan) and folder.is_record(plan.read_text()) and not (root / "plans" / "LEAD").is_file()
    rel = lambda name: str((plan.parent / name).relative_to(root))  # noqa: E731
    return {"file": rel("handoff.md") if record else ROOT_FILE, "form": "record" if record else "legacy",
            "plan": rel("plan.md") if plan else None,
            "decisions": rel("decisions.md") if record else None,
            "questions": rel("questions.md") if plan else "plans/questions.md"}


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


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--stamp", action="store_true")
    ap.add_argument("--root", type=Path, help="the checkout (default: the one of the current directory)")
    args = ap.parse_args(argv)
    if not shutil.which("git"):
        print("where.py: git is missing; run install-prerequisites.sh", file=sys.stderr)
        return 2
    root = (args.root or Path(git(None, "rev-parse", "--show-toplevel") or ".")).resolve()
    where = locate(root)
    if args.stamp:
        stamp(root, where)
    print(json.dumps(where) if args.json else where["file"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
