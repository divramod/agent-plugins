import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import roles

RUST_ROLES = Path(__file__).resolve().parents[7] / "code/rust/libs/hal2-git/src/worktree/role.rs"


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Names(unittest.TestCase):
    def test_roles_are_the_ones_hal2_git_protects(self):
        """ROLES mirrors hal2_git::worktree::PROTECTED_SLOTS (same names, same order)."""
        if not RUST_ROLES.is_file():
            self.skipTest("the Rust source is not beside this checkout")
        block = re.search(r"PROTECTED_SLOTS: &\[&str\] = &\[(.*?)\];", RUST_ROLES.read_text(), re.S).group(1)
        self.assertEqual(tuple(re.findall(r'"([^"]+)"', block)), roles.ROLES)

    def test_wagon_master_is_a_role(self):
        self.assertIn("wagon-master", roles.ROLES)
        self.assertIn("farmer", roles.ROLES)

    def test_the_project_is_the_remote_s_last_segment(self):
        self.assertEqual(roles.project_of("git@github.com:divramod/my-repo.git"), "my-repo")


class Repo(unittest.TestCase):
    """A main checkout `a/hal2` with origin `hal2.git`; the home is tmp."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        origin, self.main = self.tmp / "hal2.git", self.tmp / "a" / "hal2"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(origin))
        git(self.tmp, "clone", "-q", str(origin), str(self.main))
        home = mock.patch.object(roles.Path, "home", return_value=self.tmp)
        home.start()
        self.addCleanup(home.stop)
        no_override = mock.patch.object(roles, "OVERRIDE", None)
        no_override.start()
        self.addCleanup(no_override.stop)

    def test_the_wagon_master_s_slot_and_state_folder(self):
        self.assertEqual(roles.slot_name(self.main, "wagon-master"), "wagon-master-hal2")
        slot = self.tmp / ".hal/git/worktree/hal2/wagon-master-hal2"
        self.assertEqual(roles.slot_dir(self.main, "wagon-master"), slot)
        self.assertEqual(roles.state_dir(self.main, role="wagon-master"), slot / "roles/wagon-master")
        self.assertFalse(slot.exists(), "the slot folder is never created here")

    def test_the_state_folder_of_an_existing_slot_gets_the_gitignore(self):
        slot = self.tmp / ".hal/git/worktree/hal2/wagon-master-hal2"
        slot.mkdir(parents=True)
        d = roles.state_dir(self.main, role="wagon-master")
        self.assertEqual((d / ".gitignore").read_text(), roles.GITIGNORE)

    def test_the_farmer_s_names_are_unchanged(self):
        self.assertEqual(roles.slot_name(self.main), "farmer-hal2")
        self.assertEqual(
            roles.state_dir(self.main), self.tmp / ".hal/git/worktree/hal2/farmer-hal2/roles/farmer")

    def test_is_slot_follows_the_role(self):
        slot = self.tmp / ".hal/git/worktree/hal2/wagon-master-hal2"
        self.assertEqual(roles.slot_name(self.main, "wagon-master"), slot.name)
        self.assertFalse(roles.is_farmer_label("wagon-master-hal2"))
        self.assertTrue(roles.is_farmer_label("farmer-hal2"))

    def test_the_boss_is_the_wagon_master_s_only_when_the_check_says_yes(self):
        def check(body: str) -> Path:
            f = self.tmp / "check.sh"
            f.write_text(body)
            return f
        self.assertEqual(roles.boss(self.main, check('echo "$1" > "$0.arg"\necho yes\n')),
                         "wagon-master (merge-to-main boss)")
        self.assertEqual((self.tmp / "check.sh.arg").read_text().strip(), str(self.main))
        for doubt in ("echo no\n", "echo yes\nexit 1\n", "echo yes please\n", "exit 0\n"):
            self.assertEqual(roles.boss(self.main, check(doubt)), "merge-to-main boss", doubt)
        self.assertEqual(roles.boss(self.main, self.tmp / "missing.sh"), "merge-to-main boss")

    def test_the_real_check_answers_no_outside_a_repository(self):
        self.assertTrue(roles.WAGON_MASTER_CHECK.is_file(), roles.WAGON_MASTER_CHECK)
        self.assertEqual(roles.boss(self.tmp / "nowhere"), "merge-to-main boss")

    def test_a_field_s_role_is_the_longest_role_name_that_fits(self):
        self.assertEqual([roles.role_of(n) for n in ("farmer-hal2", "farmer", "wagon-master-hal2", "i-hal2")],
                         ["farmer", "farmer", "wagon-master", "i"])
        self.assertEqual([roles.role_of(n) for n in ("07", "30", "farmers", "07-farmer", "index")], [None] * 5)


if __name__ == "__main__":
    unittest.main()
