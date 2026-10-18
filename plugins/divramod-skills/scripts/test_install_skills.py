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


CATEGORY = {"alpha": "actions", "beta": "roles", "gamma": "shortcuts"}


class InstallSkillsTest(unittest.TestCase):
    LAYOUT = "flat"  # "flat": skills/<name>/; "category": skills/<category>/<name>/

    def skill_dir(self, name):
        sub = CATEGORY[name] if self.LAYOUT == "category" else ""
        return self.repo / "skills" / sub / name

    def add_skill(self, name):
        self.skill_dir(name).mkdir(parents=True)
        (self.skill_dir(name) / "SKILL.md").write_text(f"---\nname: {name}\n---\n")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.repo = base / "repo"
        for name in ("alpha", "beta"):
            self.add_skill(name)
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
        self.assertEqual((self.target / "alpha").resolve(), self.skill_dir("alpha").resolve())
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

        self.assertEqual(code, 0)  # the clash only warns
        self.assertFalse((self.target / "grill-me").is_symlink())
        self.assertTrue((self.target / "tell").is_symlink())
        self.assertTrue((self.target / "beta").is_dir() and not (self.target / "beta").is_symlink())
        self.assertIn("warning", err)

    def test_dry_run_changes_nothing(self):
        code, out, _ = self.run_install("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("link", out)
        self.assertFalse(self.target.exists())

    def test_new_skill_is_linked_and_removed_one_unlinked(self):
        self.run_install()
        self.add_skill("gamma")
        (self.skill_dir("beta") / "SKILL.md").unlink()
        self.run_install()
        self.assertTrue((self.target / "gamma").is_symlink())
        self.assertFalse((self.target / "beta").is_symlink())

    def test_second_apply_changes_nothing_and_quiet_prints_nothing(self):
        self.run_install()
        code, out, err = self.run_install("--quiet")
        self.assertEqual((code, out, err), (0, "", ""))

    def test_check_exits_1_on_missing_and_0_when_linked(self):
        code, out, _ = self.run_install("--check")
        self.assertEqual(code, 1)
        self.assertIn("missing", out)
        self.assertFalse(self.target.exists())  # changed nothing
        self.run_install()
        code, out, _ = self.run_install("--check")
        self.assertEqual(code, 0)
        self.assertIn("all 2 skills linked", out)

    def test_check_names_clash_and_stale(self):
        self.run_install()
        (self.target / "alpha").unlink()
        (self.target / "alpha").mkdir()
        (self.target / "gone").symlink_to(self.repo / "skills" / "old")
        code, out, _ = self.run_install("--check")
        self.assertEqual(code, 1)
        self.assertIn("clash", out)
        self.assertIn("stale", out)

    def test_a_link_into_the_old_flat_path_is_relinked_not_left_dangling(self):
        self.target.mkdir(parents=True)
        old = self.repo / "skills" / "alpha"  # where alpha lived before the move
        (self.target / "alpha").symlink_to(old)
        if self.LAYOUT == "category":
            self.assertFalse(old.exists())  # the link is dangling now
        code, out, _ = self.run_install()
        self.assertEqual(code, 0)
        self.assertEqual((self.target / "alpha").resolve(), self.skill_dir("alpha").resolve())
        self.assertTrue((self.target / "alpha" / "SKILL.md").is_file())

    def test_unlink_removes_only_links_into_the_repo(self):
        self.run_install()
        foreign = Path(self.tmp.name) / "elsewhere"
        foreign.mkdir()
        (self.target / "tell").symlink_to(foreign)
        code, _, _ = self.run_install("--unlink")
        self.assertEqual(code, 0)
        self.assertEqual(sorted(p.name for p in self.target.iterdir()), ["tell"])

    def test_a_dangling_link_of_a_skill_that_is_gone_is_removed(self):
        self.target.mkdir(parents=True)
        (self.target / "vanished").symlink_to(self.repo / "skills" / "actions" / "vanished")
        self.run_install()
        self.assertFalse((self.target / "vanished").is_symlink())


class MovedUnitTest(unittest.TestCase):
    """A unit moved to another code/ category (plan 0360: the claude-code folder became agents) relinks its old links."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.repo, self.other = base / "repo", base / "other"
        for repo in (self.repo, self.other):
            (repo / ".git").mkdir(parents=True)
        self.unit = self.repo / "code" / "agents" / "apps" / "skills"
        for name in ("alpha", "beta"):
            (self.unit / "skills" / name).mkdir(parents=True)
            (self.unit / "skills" / name / "SKILL.md").write_text(f"---\nname: {name}\n---\n")
        self.target = base / "agents" / "skills"
        self.target.mkdir(parents=True)
        setattr(install, "ROOT", self.unit)

    def tearDown(self):
        self.tmp.cleanup()

    def test_links_into_the_old_unit_folder_are_relinked_and_other_repos_untouched(self):
        old = self.repo / "code" / "claude-code" / "apps" / "skills" / "skills"
        for name in ("alpha", "beta", "gone"):
            (self.target / name).symlink_to(old / name)  # dangling: the unit moved
        foreign = self.other / "code" / "claude-code" / "apps" / "skills" / "skills" / "tell"
        (self.target / "tell").symlink_to(foreign)
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = install.main(["--target", str(self.target), "--quiet"])
        self.assertEqual(code, 0)
        for name in ("alpha", "beta"):
            self.assertEqual((self.target / name).resolve(), (self.unit / "skills" / name).resolve())
        self.assertFalse((self.target / "gone").is_symlink())
        self.assertEqual(Path((self.target / "tell").readlink()), foreign)
        dangling = [p.name for p in self.target.iterdir() if p.is_symlink() and not p.exists()]
        self.assertEqual(dangling, ["tell"])  # the other repository's link is not ours to touch


class LinkSkillsWrapperTest(unittest.TestCase):
    def test_link_skills_sh_runs_the_installer_into_a_temporary_home(self):
        import os
        import subprocess
        with tempfile.TemporaryDirectory() as home:
            wrapper = Path(__file__).with_name("link-skills.sh")
            run = subprocess.run(["bash", str(wrapper), "--quiet"], env={**os.environ, "HOME": home},
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertTrue((Path(home) / ".claude" / "skills" / "plan" / "SKILL.md").is_file())
            self.assertTrue((Path(home) / ".agents" / "skills" / "plan").is_symlink())
            run = subprocess.run(["bash", str(wrapper), "--unlink"], env={**os.environ, "HOME": home},
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertFalse((Path(home) / ".claude" / "skills" / "plan").exists())


class InstallSkillsCategoryTest(InstallSkillsTest):
    LAYOUT = "category"

    def test_same_name_in_two_categories_links_nothing(self):
        other = self.repo / "skills" / "shortcuts" / "alpha"
        other.mkdir(parents=True)
        (other / "SKILL.md").write_text("---\nname: alpha\n---\n")
        code, out, err = self.run_install()
        self.assertEqual(code, 1)
        self.assertIn("alpha", err)
        self.assertIn("actions", err)
        self.assertIn("shortcuts", err)
        self.assertFalse(self.target.exists())

    def test_a_category_folder_is_not_a_skill(self):
        self.run_install()
        self.assertFalse((self.target / "actions").exists())
        self.assertEqual(sorted(p.name for p in self.target.iterdir()), ["alpha", "beta"])


if __name__ == "__main__":
    unittest.main()
