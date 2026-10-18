#!/usr/bin/env python3
"""Runs the tests of what a change touches in this plugin: the paths come on stdin, one a line, relative to the
repository's top (a smuggle's SMUGGLE_FILES, hal2 plan 0360 step 19). A path inside a skill (flat `skills/<name>/` or
in a category folder) runs that skill's tests: `python3 -m unittest discover` in its `scripts/` when it has a
`test_*.py`, `bats` on it when it has a `*.bats`; a path in the plugin's own `scripts/` runs their unittests. Each
part once, in path order; a red part does not stop the others.

  printf '%s\\n' "$SMUGGLE_FILES" | python3 scripts/changed_tests.py [--dry-run]

Exit: 0 green (also nothing to run), 1 a part red.
"""

import subprocess
import sys
from pathlib import Path

UNIT = Path(__file__).resolve().parent.parent


def repo_top():
    out = subprocess.run(["git", "-C", str(UNIT), "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                         check=True)
    return Path(out.stdout.strip())


def skill_of(path, unit=UNIT):
    """The skill folder holding <path> (the nearest folder with a SKILL.md under skills/), or None."""
    skills = unit / "skills"
    for folder in path.parents:
        if folder == skills or skills not in folder.parents:
            return None
        if (folder / "SKILL.md").is_file():
            return folder
    return None


def parts(paths, unit=UNIT):
    """The folders whose tests run, each once: ("skill", <scripts>) or ("plugin", <scripts>)."""
    seen, out = set(), []
    for path in paths:
        skill = skill_of(path, unit)
        if skill is not None:
            part = ("skill", skill / "scripts")
        elif unit / "scripts" in path.parents:
            part = ("plugin", unit / "scripts")
        else:
            continue
        if part not in seen and part[1].is_dir():
            seen.add(part)
            out.append(part)
    return out


def commands(kind, scripts):
    """The commands for one part: unittest when it has test_*.py, bats (skills) when it has *.bats."""
    out = []
    if any(scripts.glob("test_*.py")):
        out.append(["python3", "-m", "unittest", "discover", "-s", ".", "-p", "test_*.py"])
    if kind == "skill" and any(scripts.glob("*.bats")):
        out.append(["bats", "."])
    return out


def main(argv):
    dry = "--dry-run" in argv
    if [arg for arg in argv if arg != "--dry-run"]:
        print("usage: changed_tests.py [--dry-run] < paths", file=sys.stderr)
        return 64
    top = repo_top()
    paths = [top / line.strip() for line in sys.stdin if line.strip()]
    red = 0
    for kind, scripts in parts(paths):
        name = scripts.parent.name if kind == "skill" else "plugin scripts"
        for command in commands(kind, scripts):
            print(f"{'would run' if dry else '=='}: {name}: {' '.join(command)}", flush=True)
            if not dry and subprocess.run(command, cwd=scripts, check=False).returncode != 0:
                print(f"== {name}: red", flush=True)
                red = 1
    return red


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
