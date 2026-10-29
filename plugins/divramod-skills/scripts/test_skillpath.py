"""skillpath.py and skillpath.sh find a sibling skill flat and in categories (plan 0360, D20)."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import skillpath  # noqa: E402

HERE = Path(__file__).resolve().parent
CATEGORY = {"alpha": "actions", "beta": "roles", "gamma": "roles", "c": "shortcuts"}


class Base(unittest.TestCase):
    CATEGORIES = False

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.unit = Path(tmp.name).resolve() / "unit"
        (self.unit / ".claude-plugin").mkdir(parents=True)
        for name in ("alpha", "beta", "gamma", "c"):
            self.skill(name)
        self.script = self.skill_dir("alpha") / "scripts" / "run.py"
        self.script.parent.mkdir()
        self.script.write_text("")

    def skill_dir(self, name: str) -> Path:
        return self.unit / "skills" / (CATEGORY[name] if self.CATEGORIES else "") / name

    def skill(self, name: str) -> None:
        self.skill_dir(name).mkdir(parents=True)
        (self.skill_dir(name) / "SKILL.md").write_text(f"---\nname: {name}\n---\n")

    def test_finds_a_skill_beside_or_in_another_category(self):
        for name in ("beta", "gamma", "c"):
            self.assertEqual(skillpath.sibling(name, self.script), self.skill_dir(name))

    def test_the_skill_beside_wins_over_one_of_the_same_name_elsewhere(self):
        if not self.CATEGORIES:
            self.skipTest("one folder per name when flat")
        twin = self.unit / "skills" / "actions" / "gamma"
        twin.mkdir()
        (twin / "SKILL.md").write_text("")
        self.assertEqual(skillpath.sibling("gamma", self.script), twin)

    def test_a_shortcut_stub_is_a_skill_too(self):
        self.assertEqual(skillpath.sibling("c", self.script), self.skill_dir("c"))

    def test_a_missing_skill_raises_naming_it(self):
        with self.assertRaises(FileNotFoundError) as caught:
            skillpath.sibling("nope", self.script)
        self.assertIn("nope", str(caught.exception))

    def test_a_folder_without_skill_md_is_no_skill(self):
        (self.unit / "skills" / "empty").mkdir()
        with self.assertRaises(FileNotFoundError):
            skillpath.sibling("empty", self.script)

    def test_roots(self):
        self.assertEqual(skillpath.unit_root(self.script), self.unit)
        self.assertEqual(skillpath.skills_root(self.script), self.unit / "skills")
        self.assertEqual(skillpath.own_skill(self.script), self.skill_dir("alpha"))

    def test_a_symlinked_script_resolves_into_the_source(self):
        link_dir = self.unit.parent / "installed"
        link_dir.mkdir()
        (link_dir / "alpha").symlink_to(self.skill_dir("alpha"))
        self.assertEqual(skillpath.sibling("beta", link_dir / "alpha" / "scripts" / "run.py"), self.skill_dir("beta"))

    def bash(self, name: str) -> subprocess.CompletedProcess:
        script = f'. "{HERE}/skillpath.sh"; skill_dir {name} "{self.script.parent}"'
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True)

    def test_bash_skill_dir_agrees(self):
        for name in ("beta", "c"):
            run = self.bash(name)
            self.assertEqual((run.returncode, run.stdout.strip()), (0, str(self.skill_dir(name))), run.stderr)
        run = self.bash("nope")
        self.assertEqual(run.returncode, 1)
        self.assertIn("nope", run.stderr)

    def test_real_unit_scripts_find_each_other(self):
        real = skillpath.sibling("plan", HERE / "check-plugins.py")
        self.assertTrue((real / "SKILL.md").is_file())

    def test_pointers_load_the_plan_skills_module_or_the_files_home_stand_in(self):
        """hal2 plan 0409 step 12: the real plan skill's pointers.py; without a plan skill the bare plans/ stand-in."""
        real = skillpath.pointers(HERE / "check-plugins.py")
        self.assertTrue(hasattr(real, "git_path"))
        stand_in = skillpath._TreePointers  # what a copied script outside a skills unit gets
        root = self.unit.parent / "checkout"
        (root / "plans").mkdir(parents=True)
        self.assertEqual(stand_in.read(root, "LEAD"), "")
        stand_in.write(root, "LEAD", "07 0001-x 2")
        self.assertEqual((root / "plans/LEAD").read_text(), "07 0001-x 2\n")
        self.assertEqual(stand_in.read(root, "LEAD"), "07 0001-x 2")
        stand_in.remove(root, "LEAD")
        self.assertFalse(stand_in.exists(root, "LEAD"))


class TestCategories(Base):
    CATEGORIES = True


if __name__ == "__main__":
    unittest.main()
