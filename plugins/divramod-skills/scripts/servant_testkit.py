"""A fake `hal2-cli-plans` for the skills' tests (hal2 plan 0594, step 6): never the user's installed or a branch CLI.

  from servant_testkit import install
  install(self)                      # in setUp: HAL2_CLI_PLANS names the fake until the test's cleanup

The fake answers only `servant show --repo <dir> --json`: the object the test wrote for `<dir>` with
`write(dir, foreman, plan, steps, finished)` (kept beside the fake, never in the checkout, so a checkout stays
clean), else, for a checkout whose LEAD file holds a plain `<NN> <plan> <step>[,<step>]` line (the git dir's, else
plans/), the object of that line with every step open, else `null` (a broken marker, as the real CLI answers). That
tiny parse is a test double only: the real parser is `hal2_plans::servant`, pinned in Rust.
"""
import json
import os
import stat
import tempfile
import unittest.mock
from pathlib import Path

SCRIPT = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
a = sys.argv[1:]
if a[:2] != ["servant", "show"] or "--json" not in a or "--repo" not in a:
    sys.exit(2)
f = Path(sys.argv[0]).resolve().parent / (os.path.realpath(a[a.index("--repo") + 1]).replace("/", "_") + ".json")
if f.is_file():
    print(f.read_text()); sys.exit(0)
root = Path(os.path.realpath(a[a.index("--repo") + 1]))
dot, mark = root / ".git", None
if dot.is_file() and dot.read_text().startswith("gitdir:"):
    git = Path(dot.read_text().split(":", 1)[1].strip()); git = git if git.is_absolute() else root / git
elif dot.is_dir():
    git = dot
else:
    git = None
for c in ([git / "hal" / "LEAD"] if git else []) + [root / "plans" / "LEAD"]:
    if c.is_file():
        mark = c.read_text().split()
        break
if mark and len(mark) >= 3 and len(mark[0]) == 2 and mark[0].isdigit():
    print(json.dumps({"schema": 1, "foreman": mark[0], "plan": mark[1], "finished": False,
                      "steps": [{"n": n, "title": "", "status": ""} for n in mark[2].split(",")]}))
else:
    print("null")
'''


def write(root, foreman: str, plan: str, steps: list[tuple], finished: bool = False) -> None:
    """The servant object the fake shows for the checkout `root`; `steps` are `(n, title, status)`."""
    servant = {"schema": 1, "foreman": foreman, "plan": plan, "finished": finished,
               "steps": [{"n": n, "title": t, "status": s} for n, t, s in steps]}
    here = Path(os.environ["HAL2_CLI_PLANS"]).resolve().parent
    (here / (os.path.realpath(root).replace("/", "_") + ".json")).write_text(json.dumps(servant))


def install(test) -> Path:
    """Puts the fake on `HAL2_CLI_PLANS` for `test` (a unittest.TestCase); returns its path."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    fake = Path(tmp.name) / "hal2-cli-plans"
    fake.write_text(SCRIPT)
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    patch = unittest.mock.patch.dict(os.environ, {"HAL2_CLI_PLANS": str(fake)})
    patch.start()
    test.addCleanup(patch.stop)
    return fake
