import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import scan  # noqa: E402


def run(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def lines(n):
    return "".join(f"let v{i} = {i};\n" for i in range(n))


def scratch_repo(base):
    """origin (bare) + a clone with two units, one file over the limit of 10 in each, one busy branch."""
    origin, repo = Path(base, "origin.git"), Path(base, "repo")
    run(base, "git", "init", "-q", "--bare", "-b", "main", str(origin))
    run(base, "git", "clone", "-q", str(origin), str(repo))
    for args in (["user.email", "t@t"], ["user.name", "t"]):
        run(repo, "git", "config", *args)
    files = {
        "code/typescript/apps/big/src/a.ts": lines(40),
        "code/typescript/apps/big/src/b.ts": lines(5),
        "code/typescript/apps/big/src/a.test.ts": lines(99),
        "code/typescript/apps/small/src/c.ts": lines(12),
        "code/typescript/apps/busy/src/d.ts": lines(60),
        ".hal/fix-loc.toml": "limit = 10\n",
    }
    for path, text in files.items():
        Path(repo, path).parent.mkdir(parents=True, exist_ok=True)
        Path(repo, path).write_text(text)
    run(repo, "git", "add", "-A")
    run(repo, "git", "commit", "-q", "-m", "init")
    run(repo, "git", "push", "-q", "origin", "main")
    run(repo, "git", "remote", "set-head", "origin", "main")
    run(repo, "git", "worktree", "add", "-q", "-b", "07", str(Path(base, "wt07")))
    Path(base, "wt07/code/typescript/apps/busy/src/d.ts").write_text(lines(61))
    return repo


@unittest.skipIf(shutil.which("scc") is None, "scc is not installed")
class Scan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["FIX_LOC_ROOT"] = str(Path(self.tmp.name, "state"))
        self.repo = scratch_repo(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_units_over_the_limit_hotspot_first_busy_last(self):
        result = scan.scan(self.repo)
        self.assertEqual(result["limit"], 10)
        order = [(u["unit"].split("/")[-1], u["busy"]) for u in result["units"]]
        self.assertEqual(order, [("big", False), ("small", False), ("busy", True)])
        big = result["units"][0]
        self.assertEqual([f["path"].split("/")[-1] for f in big["files"]], ["a.ts"], "tests and small files left out")
        self.assertEqual(big["files"][0]["over"], 30)

    def test_a_skipped_branch_is_not_busy(self):
        units = scan.scan(self.repo, skip_branches=["07"])["units"]
        self.assertFalse(any(u["busy"] for u in units))

    def test_check_passes_once_every_file_is_within_the_limit(self):
        unit = "code/typescript/apps/big"
        self.assertEqual(scan.main(["check", "--repo", str(self.repo), unit, "--worktree"]), 1)
        Path(self.repo, unit, "src/a.ts").write_text(lines(10))
        self.assertEqual(scan.main(["check", "--repo", str(self.repo), unit, "--worktree"]), 0)


if __name__ == "__main__":
    unittest.main()
