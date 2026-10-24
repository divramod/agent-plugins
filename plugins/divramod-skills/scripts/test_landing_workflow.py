"""landing_workflow.py picks the landing file by the setting; landing-workflow.sh agrees with it (plan 0423 D4)."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import landing_workflow as lw  # noqa: E402

SH = Path(__file__).resolve().parent / "landing-workflow.sh"


class Pick(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def files(self, *names):
        d = self.root / ".github" / "workflows"
        d.mkdir(parents=True, exist_ok=True)
        for n in names:
            (d / n).write_text("name: x\n")

    def toml(self, text):
        (self.root / ".hal").mkdir(exist_ok=True)
        (self.root / ".hal" / "landing.toml").write_text(text)

    def both(self, env=None):
        """The Python pick, and the bash pick (which must agree)."""
        py = lw.pick(self.root, env or {})
        run = subprocess.run(["bash", "-c", f'. "{SH}"; landing_workflow_pick "{self.root}"'], capture_output=True,
                             text=True, env={"PATH": "/usr/bin:/bin", **(env or {})})
        sh = run.stdout.strip() or None
        self.assertEqual(py, sh)
        return py

    def test_none(self):
        self.assertIsNone(self.both())

    def test_no_setting_local_first(self):
        self.files("merge-to-main-cloud.yml", "merge-to-main-local.yml")
        self.assertEqual(self.both(), "merge-to-main-local.yml")

    def test_cloud_setting(self):
        self.files("merge-to-main-cloud.yml", "merge-to-main-local.yml")
        self.toml('# x\nworkflow = "cloud"\n')
        self.assertEqual(self.both(), "merge-to-main-cloud.yml")

    def test_env_beats_file(self):
        self.files("merge-to-main-cloud.yml", "merge-to-main-local.yml")
        self.toml('workflow = "cloud"\n')
        self.assertEqual(self.both({"HAL2_LAND_WORKFLOW": "local"}), "merge-to-main-local.yml")

    def test_other_new_file_when_the_chosen_is_missing(self):
        self.files("merge-to-main-cloud.yml", "dev-merge-to-main.yml")
        self.toml('workflow = "local"\n')
        self.assertEqual(self.both(), "merge-to-main-cloud.yml")

    def test_old_names_last_dev_before_plain(self):
        self.files("merge-to-main.yml", "dev-merge-to-main.yml")
        self.assertEqual(self.both(), "dev-merge-to-main.yml")
        (self.root / ".github/workflows/dev-merge-to-main.yml").unlink()
        self.assertEqual(self.both(), "merge-to-main.yml")

    def test_unknown_setting_is_none(self):
        self.files("merge-to-main-cloud.yml", "merge-to-main-local.yml")
        self.toml('workflow = "mars"\n')
        self.assertEqual(self.both(), "merge-to-main-local.yml")

    def test_ref_pick_in_bash(self):
        self.files("merge-to-main-cloud.yml")
        git = ["git", "-C", str(self.root)]
        subprocess.run(git + ["init", "-q", "-b", "main"], check=True)
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"], check=True)
        run = subprocess.run(["bash", "-c", f'. "{SH}"; landing_workflow_pick "{self.root}" HEAD'],
                             capture_output=True, text=True)
        self.assertEqual(run.stdout.strip(), "merge-to-main-cloud.yml")


if __name__ == "__main__":
    unittest.main()
