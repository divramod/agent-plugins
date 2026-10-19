#!/usr/bin/env python3
"""The role skill a continued session loads first (hal2 plan 0383, D15, D16).

  session_role.py [--repo DIR] [--json]   prints `/foreman duties` or `/servant duties`, nothing for any other session

A foreman and a servant lose their role in a clear, so `/handoff c` loads it again before anything else. The role comes from
the checkout, never from the field's number (D16: a foreman may work in any field 00-99): a field holding `plans/LEAD`
is a servant's, a field whose `plans/CURRENT_PLAN` names a plan (a `plan.md`) without it is a foreman's. Whether the
checkout is a field at all, and not the main checkout, a farmer's, a tollman's or an upper role's place, is get-state's
detection (`role.detect`, which the pages of `/s` use): those roles load their own skill (`/farmer act`, `/tollman act`).
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import sibling  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)

sys.path.insert(0, str(sibling("get-state") / "scripts"))
import role as state_role  # noqa: E402  (get-state's role detection)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import where  # noqa: E402  (this skill's: the current plan)


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], text=True, capture_output=True).stdout.strip()


def session_role(root: Path) -> str | None:
    """`foreman`, `servant` or None for the checkout `root`."""
    top = git(root, "rev-parse", "--show-toplevel")
    common = git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    main = str(Path(common).parent) if common else None
    if state_role.detect(top, main) not in ("foreman", "servant"):  # a field only (by its folder), not its role
        return None
    if (Path(top) / "plans" / "LEAD").is_file():
        return "servant"
    return "foreman" if where.current_plan(Path(top)) else None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    role = session_role(Path(args.repo).resolve())
    command = f"/{role} duties" if role else None
    if args.json:
        print(json.dumps({"role": role, "command": command}))
    elif command:
        print(command)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
