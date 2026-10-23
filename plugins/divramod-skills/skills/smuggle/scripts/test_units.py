"""Tests of units.py against a scratch repository: a bare origin, a clone with `.hal/smuggle.toml` on main and a
branch that changes files; hal2-cli-git faked on PATH (hal2 plan 0360 step 19)."""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
UNITS = HERE / "units.py"
sys.path.insert(0, str(HERE))

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
    case " $* " in *" --keys "*) cat "$FAKE_KEYS"; exit 0;; esac
    echo '{"jobs":[{"name":"rust-test","run":true},{"name":"bash-lint","run":false},{"name":"ts-lint","run":true}]}'
''')


FAKE_GATE = textwrap.dedent('''\
    #!/usr/bin/env bash
    # the fake gate: list, green check|mark|restore|save, and a job (red when named in $FAIL_JOB)
    echo "gate $* pkgs=${HAL_CHANGED_PACKAGES-unset} keys=${HAL_PACKAGE_KEYS-unset}" >> "$FAKE_LOG"
    case "$1" in
      list) printf '%s\\n' rust-test ts-test bash-lint; exit 0 ;;
      green)
        if [ "$2" = check ]; then grep -qx "$3 $4" "$GREEN_HITS" 2>/dev/null && echo hit || echo miss; fi
        exit 0 ;;
    esac
    [ "$1" != "$FAIL_JOB" ]
''')

KEYS = {"jobs": [{"name": "rust-test", "run": True, "packages": ["hal2-core", "hal2-git"]},
                 {"name": "ts-test", "run": True}, {"name": "bash-lint", "run": False}, {"name": "gone", "run": True}],
        "keys": [{"name": "rust-test", "key": "k-rust", "packages": {"hal2-core": "p1", "hal2-git": "p2"}},
                 {"name": "ts-test", "key": "k-ts"}, {"name": "bash-lint", "key": "k-bash"}]}


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
        self.env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", FAKE_LOG=str(self.tmp / "cli.log"),
                        SMUGGLE_SCCACHE="")
        self.env.pop("SMUGGLE_RUN_LOGS", None)
        # CI sets these for its own gate steps; the fake gate reports them as `unset` when the job map gave none.
        self.env["HAL_CHANGED_PACKAGES"] = "ambient"

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

    def job_map(self, **extra):
        """A repository with the job map, the fake gate and the keys; the env of a `run checks`."""
        self.write(".github/hal2-changes.toml", "version = 1\n")
        self.commit("skills/a/SKILL.md")
        (self.tmp / "keys.json").write_text(json.dumps(KEYS))
        (self.tmp / "hits").write_text("")
        gate = self.tmp / "gate.sh"
        gate.write_text(FAKE_GATE)
        gate.chmod(0o755)
        self.env.update(FAKE_KEYS=str(self.tmp / "keys.json"), SMUGGLE_GATE=str(gate), SMUGGLE_SALT="tc",
                        GREEN_HITS=str(self.tmp / "hits"), **extra)

    def cli_log(self):
        return (self.tmp / "cli.log").read_text()

    def test_job_map_selection_runs_instead_of_the_units_commands(self):
        self.job_map()
        report = self.tmp / "report.jsonl"
        out = self.units("run", "checks", "--report", str(report))
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertNotIn("skills-check", out.stdout)
        log = self.cli_log()
        self.assertIn("changes --base origin/main --head HEAD --keys --salt tc --json", log)
        self.assertIn("gate rust-test --branch origin/main --green .gate/green-rust-test pkgs=hal2-core hal2-git keys=hal2-core=p1 hal2-git=p2", log)
        self.assertIn("gate ts-test --branch origin/main pkgs=unset keys=unset", log)
        self.assertIn("gate green restore rust-test", log)
        self.assertIn("gate green save rust-test", log)
        self.assertNotIn("gate bash-lint", log)  # run: false
        self.assertNotIn("gate gone", log)  # not a gate job
        self.assertIn("gate green mark rust-test k-rust ", log)
        self.assertIn("gate green mark ts-test k-ts ", log)
        line = json.loads(report.read_text())
        self.assertEqual((line["lane"], line["status"], line["jobs"]), ("checks", "ok", ["rust-test", "ts-test"]))

    def test_job_green_before_is_skipped_and_reported(self):
        self.job_map()
        (self.tmp / "hits").write_text("ts-test k-ts\n")
        report = self.tmp / "report.jsonl"
        out = self.units("run", "checks", "--report", str(report))
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("ts-test: green before (k-ts)", out.stdout)
        self.assertNotIn("gate ts-test --branch", self.cli_log())
        self.assertNotIn("green mark ts-test", self.cli_log())
        line = json.loads(report.read_text())
        self.assertEqual(line["skipped"], [{"job": "ts-test", "key": "k-ts"}])
        self.assertEqual(line["jobs"], ["rust-test", "ts-test skipped (green before k-ts)"])

    def test_red_job_is_not_marked_and_stops_the_run(self):
        self.job_map(FAIL_JOB="rust-test")
        out = self.units("run", "checks")
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("rust-test: red", out.stdout)
        self.assertNotIn("green mark", self.cli_log())
        self.assertNotIn("gate ts-test", self.cli_log())

    def test_dirty_tree_is_not_marked(self):
        self.job_map()
        self.write("untracked.txt", "x\n")
        out = self.units("run", "checks")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("ts-test not marked green", out.stdout)
        self.assertNotIn("green mark", self.cli_log())

    def test_dry_run_lists_skips_and_runs_nothing(self):
        self.job_map()
        (self.tmp / "hits").write_text("ts-test k-ts\n")
        out = self.units("run", "checks", "--dry-run")
        self.assertIn("would skip ts-test: green before (k-ts)", out.stdout)
        self.assertIn("would run: rust-test", out.stdout)
        self.assertNotIn("gate rust-test --branch", self.cli_log())

    def test_keys_failure_falls_back_to_the_units_commands(self):
        self.job_map()
        (self.tmp / "keys.json").write_text("not json")
        out = self.units("run", "checks")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("skills-check origin/main", out.stdout)

    def test_build_and_install_ignore_the_job_map(self):
        self.job_map()
        out = self.units("run", "install")
        self.assertIn(f"yard={self.repo}", out.stdout)

    def run_logs(self, lane, ext):
        return (self.tmp / "runlogs" / f"{lane}.{ext}").read_text()

    def test_job_map_jobs_are_run_steps_with_their_measures(self):
        self.job_map(SMUGGLE_RUN_LOGS=str(self.tmp / "runlogs"))
        (self.tmp / "hits").write_text("ts-test k-ts\n")
        out = self.units("run", "checks")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        jobs = self.run_logs("checks", "jobs").splitlines()
        self.assertRegex(jobs[0], r"^rust-test start \S+Z$")
        self.assertRegex(jobs[1], r"^rust-test end \S+Z 0 cpu=\d+\.\d( load0=\S+ load1=\S+)? key=k-rust$")
        self.assertRegex(jobs[2], r"^ts-test skipped \S+Z key=k-ts$")
        self.assertIn("== rust-test\n", self.run_logs("checks", "log"))

    def test_unit_commands_are_run_steps_their_output_in_the_lane_log_printed_when_red(self):
        self.commit("skills/a/SKILL.md", "nvim/x.lua")
        self.write("red", "")
        self.env["SMUGGLE_RUN_LOGS"] = str(self.tmp / "runlogs")
        out = self.units("run", "checks")
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        skills = self.run_logs("skills", "jobs").splitlines()
        self.assertRegex(skills[0], r"^echo-skills-check-SMUGGLE_BASE start \S+Z$")
        self.assertRegex(skills[1], r"^echo-skills-check-SMUGGLE_BASE end \S+Z 0 cpu=")
        self.assertIn("== echo-skills-check-SMUGGLE_BASE\nskills-check origin/main\n", self.run_logs("skills", "log"))
        self.assertNotIn("skills-check origin/main", out.stdout)  # green: its output in the lane log only
        self.assertRegex(self.run_logs("nvim", "jobs"), r"(?m)^test-e-red end \S+Z 1 ")
        self.assertIn("nvim-check", out.stdout)  # red: the lane's output printed
        self.assertNotIn("after-red", self.run_logs("nvim", "log"))

    def test_step_names_are_one_word(self):
        import runsteps
        self.assertEqual(runsteps.step_name("bun run --cwd x tsc"), "bun-run-cwd-x-tsc")
        self.assertEqual(runsteps.step_name("$$$"), "step")
        self.assertLessEqual(len(runsteps.step_name("x" * 100)), 48)

    def test_usage_errors_exit_64(self):
        self.assertEqual(self.units("run", "deploy").returncode, 64)
        self.assertEqual(self.units("nothing").returncode, 64)


if __name__ == "__main__":
    unittest.main()
