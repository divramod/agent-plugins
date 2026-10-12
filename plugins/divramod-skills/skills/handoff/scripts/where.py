#!/usr/bin/env python3
"""Where this checkout's handoff lives, and its stamp (hal2 plan 0206; hal2's decision record `record-formats`).

  where.py [--json]     the handoff's path below the repository root (--json: file, form, plan, decisions, questions)
  where.py --stamp      the same, after writing a missing `plans/<plan>/handoff.md` from the plan skill's template
                        and setting its `updated`, `branch`, `at` (the short sha of HEAD) and `status`

The current plan (`plans/CURRENT_PLAN`) in the record format (its plan.md has front matter with a `type`): the
handoff is the plan's committed `plans/<plan>/handoff.md` (form `record`), the decisions index is the plan's ledger
`decisions.md`. A legacy plan, work without a plan and a subservant's slot (`plans/LEAD`: the plan's files are the
lead's): the gitignored root `HANDOFF.md` with its own Decisions section (form `legacy`). `--stamp` changes nothing
of a legacy handoff: its header line is written by hand.

Exit 0 printed, 2 git missing.
"""

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plan" / "scripts"))

import checker  # noqa: E402  (the plan skill's)
import envelope  # noqa: E402
import folder  # noqa: E402

ROOT_FILE = "HANDOFF.md"


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


def stamp(root: Path, where: dict) -> None:
    """A record handoff exists and says when, on which branch and at which commit it was written."""
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
