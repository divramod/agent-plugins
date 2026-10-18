"""changed_tests.py: which tests a change's paths run (hal2 plan 0360 step 19)."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import changed_tests  # noqa: E402

HERE = Path(__file__).resolve().parent


class Parts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.unit = Path(self.tmp.name) / "unit"
        for skill in ("skills/flat", "skills/roles/inner"):
            (self.unit / skill / "scripts").mkdir(parents=True)
            (self.unit / skill / "SKILL.md").write_text("---\n---\n")
        (self.unit / "skills/flat/scripts/test_a.py").write_text("")
        (self.unit / "skills/flat/scripts/test_b.bats").write_text("")
        (self.unit / "skills/roles/inner/scripts/test_c.py").write_text("")
        (self.unit / "skills/nodir").mkdir()
        (self.unit / "skills/nodir/SKILL.md").write_text("")
        (self.unit / "scripts").mkdir()
        (self.unit / "scripts/test_d.py").write_text("")

    def tearDown(self):
        self.tmp.cleanup()

    def parts(self, *names):
        return [(kind, str(path.relative_to(self.unit)))
                for kind, path in changed_tests.parts([self.unit / n for n in names], self.unit)]

    def test_a_skill_flat_or_in_a_category_once_the_plugin_scripts_and_nothing_else(self):
        got = self.parts("skills/flat/SKILL.md", "skills/flat/scripts/x.py", "skills/roles/inner/refs/a.md",
                         "scripts/gen.py", "README.md", "skills/nodir/SKILL.md", "../other/file")
        self.assertEqual(got, [("skill", "skills/flat/scripts"), ("skill", "skills/roles/inner/scripts"),
                               ("plugin", "scripts")])

    def test_commands_unittest_and_bats_by_what_the_folder_has(self):
        flat = changed_tests.commands("skill", self.unit / "skills/flat/scripts")
        self.assertEqual([c[0] for c in flat], ["python3", "bats"])
        inner = changed_tests.commands("skill", self.unit / "skills/roles/inner/scripts")
        self.assertEqual([c[0] for c in inner], ["python3"])


class Main(unittest.TestCase):
    def run_it(self, stdin, *args):
        return subprocess.run([sys.executable, str(HERE / "changed_tests.py"), *args], input=stdin,
                              capture_output=True, text=True, check=False)

    def test_dry_run_names_the_real_skill_and_runs_nothing(self):
        top = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--show-prefix"], capture_output=True, text=True,
                             check=True).stdout.strip()
        unit = top.rsplit("scripts/", 1)[0]
        out = self.run_it(f"{unit}skills/actions/get-open-questions/SKILL.md\nINTENT.md\n", "--dry-run")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("would run: get-open-questions: python3 -m unittest discover", out.stdout)
        self.assertEqual(len(out.stdout.splitlines()), 1)

    def test_usage_and_nothing_to_run(self):
        self.assertEqual(self.run_it("", "--now").returncode, 64)
        out = self.run_it("INTENT.md\n")
        self.assertEqual((out.returncode, out.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
