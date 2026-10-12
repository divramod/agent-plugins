"""install-skills.py links skills into target folders without touching foreign entries."""
import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("install_skills", Path(__file__).with_name("install-skills.py"))
assert SPEC is not None and SPEC.loader is not None
install = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(install)


class InstallSkillsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.repo = base / "repo"
        for name in ("alpha", "beta"):
            (self.repo / "skills" / name).mkdir(parents=True)
            (self.repo / "skills" / name / "SKILL.md").write_text(f"---\nname: {name}\n---\n")
        (self.repo / "skills" / "old").mkdir()  # renamed away: folder without SKILL.md
        self.target = base / "agents" / "skills"
        setattr(install, "ROOT", self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def run_install(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = install.main(["--target", str(self.target), *args])
        return code, out.getvalue(), err.getvalue()

    def test_links_every_skill_and_is_idempotent(self):
        code, out, _ = self.run_install()
        self.assertEqual(code, 0)
        self.assertEqual((self.target / "alpha").resolve(), (self.repo / "skills/alpha").resolve())
        self.assertFalse((self.target / "old").exists())
        code, out, _ = self.run_install()
        self.assertEqual(out.count("keep"), 2)

    def test_removes_stale_repo_links_but_keeps_foreign_entries(self):
        self.target.mkdir(parents=True)
        (self.target / "grill-me").symlink_to(self.repo / "skills" / "old")
        foreign = Path(self.tmp.name) / "elsewhere"
        foreign.mkdir()
        (self.target / "tell").symlink_to(foreign)
        (self.target / "beta").mkdir()  # a real folder with a skill's name

        code, _, err = self.run_install()

        self.assertEqual(code, 1)  # the clash is reported
        self.assertFalse((self.target / "grill-me").is_symlink())
        self.assertTrue((self.target / "tell").is_symlink())
        self.assertTrue((self.target / "beta").is_dir() and not (self.target / "beta").is_symlink())
        self.assertIn("skip", err)

    def test_dry_run_changes_nothing(self):
        code, out, _ = self.run_install("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("link", out)
        self.assertFalse(self.target.exists())


if __name__ == "__main__":
    unittest.main()
