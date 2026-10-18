"""Tests of units.py against a scratch repository: a bare origin, a clone with `.hal/smuggle.toml` on main and a
branch that changes files; hal2-cli-git faked on PATH (hal2 plan 0360 step 19)."""

import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
UNITS = HERE / "units.py"

TOML = textwrap.dedent('''\
    free = ["plans", "CHANGELOG.md"]

    [[unit]]
    name = "skills"
    paths = ["skills"]
    checks = ["echo skills-check $SMUGGLE_BASE", "printf '%s\\\\n' \\"$SMUGGLE_FILES\\" > files.out"]
    install = ["echo yard=$SMUGGLE_YARD"]

    [[unit]]
    name = "nvim"
    paths = ["nvim/*.lua"]
    checks = ["echo nvim-check", "test ! -e red", "echo after-red"]
''')

FAKE_GIT_CLI = textwrap.dedent('''\
    #!/usr/bin/env bash
    # the fake hal2-cli-git: `changes --branch <rev> --json` names two jobs that run and one that does not
    echo "$*" >> "$FAKE_LOG"
    [ "$1" = changes ] || exit 2
    echo '{"jobs":[{"name":"rust-test","run":true},{"name":"bash-lint","run":false},{"name":"ts-lint","run":true}]}'
''')


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


class Units(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@t"}
        os.environ.update(env)
        git(self.tmp, "init", "-q", "--bare", "-b", "main", "origin.git")
        git(self.tmp, "clone", "-q", "origin.git", "repo")
        self.repo = self.tmp / "repo"
        (self.repo / ".hal").mkdir()
        (self.repo / ".hal/smuggle.toml").write_text(TOML)
        for name in ("skills/a/SKILL.md", "nvim/x.lua", "core/lib.rs"):
            self.write(name, "one\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "init")
        git(self.repo, "push", "-q", "origin", "HEAD:main")
        git(self.repo, "remote", "set-head", "origin", "main")
        git(self.repo, "checkout", "-q", "-b", "07")
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "hal2-cli-git").write_text(FAKE_GIT_CLI)
        (bin_dir / "hal2-cli-git").chmod(0o755)
        self.env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", FAKE_LOG=str(self.tmp / "cli.log"))

    def tearDown(self):
        subprocess.run(["rm", "-rf", str(self.tmp)], check=False)

    def write(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self, *names):
        for name in names:
            self.write(name, "two\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "change")

    def units(self, *args):
        return subprocess.run(["python3", str(UNITS), *args, "--repo", str(self.repo)], capture_output=True,
                              text=True, env=self.env, check=False)

    def test_touched_names_the_units_and_the_paths_outside(self):
        self.commit("skills/a/SKILL.md", "nvim/x.lua", "core/lib.rs", "plans/0001-x/plan.md")
        out = self.units("touched")
        self.assertEqual(out.returncode, 0, out.stderr)
        data = json.loads(out.stdout)
        self.assertEqual([u["name"] for u in data["units"]], ["skills", "nvim"])
        self.assertEqual(data["units"][0]["files"], ["skills/a/SKILL.md"])
        self.assertEqual(data["outside"], ["core/lib.rs"])

    def test_warn_inside_the_units_is_no_warning(self):
        self.commit("skills/a/SKILL.md", "plans/0001-x/plan.md", "CHANGELOG.md")
        out = self.units("warn")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("units: skills", out.stdout)
        self.assertNotIn("outside", out.stdout)

    def test_warn_outside_names_the_paths_and_the_ci_jobs_exit_4(self):
        self.commit("skills/a/SKILL.md", "core/lib.rs")
        out = self.units("warn")
        self.assertEqual(out.returncode, 4, out.stdout + out.stderr)
        self.assertIn("core/lib.rs", out.stdout)
        self.assertIn("rust-test, ts-lint", out.stdout)
        self.assertNotIn("bash-lint", out.stdout)
        self.assertIn("changes --branch origin/main --json", (self.tmp / "cli.log").read_text())

    def test_warn_outside_after_the_users_yes_goes_on(self):
        self.commit("core/lib.rs")
        out = self.units("warn", "--yes-outside")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("the user said yes", out.stdout)

    def test_uncommitted_and_untracked_changes_count(self):
        self.write("core/lib.rs", "dirty\n")
        self.write("core/new.rs", "new\n")
        out = json.loads(self.units("touched").stdout)
        self.assertEqual(out["outside"], ["core/lib.rs", "core/new.rs"])

    def test_the_list_comes_from_head_and_its_own_change_is_outside(self):
        self.commit("core/lib.rs")
        widened = TOML.replace('paths = ["skills"]', 'paths = ["skills", "core"]')
        self.write(".hal/smuggle.toml", widened)
        out = json.loads(self.units("touched").stdout)
        self.assertEqual(out["outside"], [".hal/smuggle.toml", "core/lib.rs"])

    def test_no_list_no_warning(self):
        git(self.repo, "rm", "-q", ".hal/smuggle.toml")
        self.commit("core/lib.rs")
        out = self.units("warn")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("no .hal/smuggle.toml", out.stdout)

    def test_run_checks_runs_the_touched_units_a_red_one_stops_and_reports(self):
        self.commit("skills/a/SKILL.md", "nvim/x.lua")
        self.write("red", "")
        report = self.tmp / "report.jsonl"
        out = self.units("run", "checks", "--report", str(report))
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("skills-check origin/main", out.stdout)
        self.assertIn("nvim-check", out.stdout)
        self.assertNotIn("after-red", out.stdout)
        self.assertEqual((self.repo / "files.out").read_text(), "skills/a/SKILL.md\n")
        lines = [json.loads(line) for line in report.read_text().splitlines()]
        self.assertEqual([(line["lane"], line["status"]) for line in lines], [("skills", "ok"), ("nvim", "red")])

    def test_run_install_gives_the_yard_and_dry_run_runs_nothing(self):
        self.commit("skills/a/SKILL.md")
        out = self.units("run", "install")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn(f"yard={self.repo}", out.stdout)
        out = self.units("run", "checks", "--dry-run")
        self.assertIn("would run: skills: echo skills-check", out.stdout)
        self.assertNotIn("skills-check origin/main", out.stdout.replace("would run: skills: echo skills-check", ""))

    def test_usage_errors_exit_64(self):
        self.assertEqual(self.units("run", "deploy").returncode, 64)
        self.assertEqual(self.units("nothing").returncode, 64)


if __name__ == "__main__":
    unittest.main()
