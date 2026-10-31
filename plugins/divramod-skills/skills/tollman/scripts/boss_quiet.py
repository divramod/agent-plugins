#!/usr/bin/env python3
"""The wakes the merge-to-main boss (boss.py) leaves out, because the tollman closed them by hand again and again
(hal2 plan 0490 step 11):

- L43: work not queued in a field running a research plan (slug `-research-`) whose landing is manual is no
  question: the plan waits for the user or for the implementation plan it lands with. A `record` line, no wake.
- L78: the skip list `skip.json` in the role's state folder, `{schema, fields: {<field>: {why, at, by}}}`: an
  orphan wake for a listed field is never planned (written only by this script's `skip` verbs).
- L94: a flaky wake is keyed by its test and the fields it failed in: a closed one stays closed until the test
  fails in a new field.

  boss_quiet.py skip add <field> --why <text> [--repo <dir>] [--role tollman]
  boss_quiet.py skip rm <field> [--repo <dir>]
  boss_quiet.py skip list [--repo <dir>]
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan

SKIP = "skip.json"
SCHEMA = 1
MANUAL = re.compile(r"(?im)^\W*landing\W*:\W*manual\b")
FLAKY_CLOSED = dt.timedelta(days=30)  # a flaky wake for the same test in the same fields stays closed this long


def skip_file(main: str, role: str) -> Path:
    return mtm_scan.state_dir(main, role) / SKIP


def skipped(main: str, role: str) -> dict:
    """The skip list's fields, {} when there is none or it cannot be read."""
    try:
        return json.loads(skip_file(main, role).read_text()).get("fields") or {}
    except (OSError, ValueError, AttributeError):
        return {}


def research_manual(path: str, plan: str, plan_dir) -> bool:
    """Is `plan` a research plan whose landing is manual? `plan_dir(checkout, slug)` finds its folder; a research
    plan without a readable plan.md counts as manual (every research plan's default)."""
    if "-research-" not in (plan or "") or "/" in plan:
        return False
    try:
        return bool(MANUAL.search((plan_dir(Path(path), plan) / "plan.md").read_text()))
    except OSError:
        return True


def flaky_key(test: str, fields: str) -> str:
    """The flaky wake's key: the test and the sorted fields it failed in (a new field makes a new key)."""
    return f"flaky:{test}:{','.join(sorted(x for x in fields.split(',') if x))}"


def write(main: str, role: str, fields: dict) -> None:
    """Atomic (temp file, rename) into the role's state folder."""
    file = skip_file(main, role)
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_name(f"{file.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"schema": SCHEMA, "fields": fields}, indent=1) + "\n")
    os.replace(tmp, file)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("what", choices=["skip"])
    p.add_argument("verb", choices=["add", "rm", "list"])
    p.add_argument("field", nargs="?")
    p.add_argument("--why", default="")
    p.add_argument("--repo", default=os.getcwd())
    p.add_argument("--role", default="tollman")
    a = p.parse_args(argv)
    main_dir = mtm_scan.main_checkout(a.repo)
    fields = skipped(main_dir, a.role)
    if a.verb == "list":
        print("\n".join(f"{k}: {v.get('why', '')} ({v.get('at', '')})" for k, v in sorted(fields.items()))
              or "no field on the skip list")
        return 0
    if not a.field or (a.verb == "add" and not a.why):
        print("boss_quiet.py skip add needs a field and --why; rm a field", file=sys.stderr)
        return 2
    if a.verb == "add":
        fields[a.field] = {"why": a.why, "at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                           "by": a.role}
    else:
        fields.pop(a.field, None)
    write(main_dir, a.role, fields)
    print(f"skip list: {', '.join(sorted(fields)) or 'empty'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
