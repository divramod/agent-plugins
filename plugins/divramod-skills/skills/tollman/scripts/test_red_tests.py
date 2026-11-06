"""Hal2 plan 0714 step 1 (D2-D4, tollman learning L262): a red test named only by its name (bats `not ok <n> <name>`,
unittest `FAIL: <test> (<dotted id>)`) is mapped to its test file, its unit and the car that touched them. The git
lookups run on a scratch repository in a temp dir, never the user's."""
# enforces .adr/deterministic-first.md and .adr/tollman.md

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import early_order
import red_tests

GATE = "code/bash/scripts/gate/"
PY = "code/python/scripts/codemap/"


def sh(cwd, *argv):
    return subprocess.run(argv, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Parse(unittest.TestCase):
    def test_bats_and_unittest_reds_are_read_through_stamps_and_colours(self):
        tail = "\n".join([
            "bash-test\tRun\t2026-11-06T04:50:36.1Z ok 1 fine",
            "bash-test\tRun\t2026-11-06T04:50:36.2Z \x1b[31mnot ok 3 abort keeps the queue\x1b[0m",
            "bash-test\tRun\t2026-11-06T04:50:36.3Z not ok 4 later skipped # skip no tty",
            "FAIL: test_x (test_main.TestY.test_x)",
            "ERROR: test_z (pkg.sub.test_mod.TestQ.test_z)",
            "FAIL: test_x (test_main.TestY.test_x)",
            "ERROR: test_z (pkg.sub.test_mod.TestQ.test_z) (i=2)"])
        self.assertEqual(red_tests.failing(tail), [
            ("bats", "abort keeps the queue"), ("module", "test_main"), ("module", "pkg/sub/test_mod")])
        self.assertEqual(red_tests.failing("error: test run failed\nok 1 fine"), [])

    def test_the_unit_is_the_apps_libs_scripts_folder_and_a_skills_own(self):
        self.assertEqual(red_tests.unit_of(GATE + "test-abort.bats"), GATE)
        self.assertEqual(red_tests.unit_of("code/agents/apps/skills/skills/roles/tollman/scripts/test_a.py"),
                         "code/agents/apps/skills/skills/roles/tollman/")
        self.assertIsNone(red_tests.unit_of("docs/ci.md"))


class Owners(unittest.TestCase):
    def rows(self, **cars):
        return [{"slot": k, "files": v} for k, v in cars.items()]

    def test_a_unittest_id_is_the_car_holding_its_test_file_else_the_one_touching_its_unit(self):
        tail = "FAIL: test_x (test_main.TestY.test_x)"
        held = self.rows(a=[PY + "test_main.py"], b=[PY + "main.py"])
        self.assertEqual(red_tests.owners(held, tail), {"a"}, "the file first")
        unit_only = self.rows(a=["code/lua/x.lua"], b=[PY + "test_main.py"])
        self.assertEqual(red_tests.owners(unit_only, tail, None), {"b"})
        self.assertEqual(red_tests.owners(self.rows(a=["docs/a.md"]), tail), set(), "no car's: the session's")

    def test_several_files_of_one_name_are_narrowed_by_the_paths_the_red_names_else_nobody_owns(self):
        rows = self.rows(a=[PY + "test_main.py"], b=["code/python/scripts/other/test_main.py"])
        tail = "FAIL: test_x (test_main.TestY.test_x)"
        self.assertEqual(red_tests.owners(rows, tail), {"a", "b"}, "both hold a file of that name")
        named = tail + '\n  File "/home/r/work/hal2/' + PY + 'test_main.py", line 12, in test_x'
        self.assertEqual(red_tests.owners(rows, named), {"a"})

    def test_a_python_module_path_is_matched_whole(self):
        rows = self.rows(a=["code/python/scripts/x/pkg/sub/test_mod.py"], b=["code/python/scripts/x/test_mod.py"])
        self.assertEqual(red_tests.owners(rows, "ERROR: t (pkg.sub.test_mod.C.t)"), {"a"})


class Clues(unittest.TestCase):
    def test_a_failing_test_is_named_by_its_name_its_file_and_its_unit_and_a_text_mentions_any(self):
        rows = [{"slot": "a", "files": [PY + "test_main.py"]}]
        clues = red_tests.clues("FAIL: test_x (test_main.TestY.test_x)", rows)
        self.assertEqual(clues, ["test_main.TestY.test_x", PY + "test_main.py", PY])
        for why in ("job: FAIL: test_x (test_main.TestY.test_x)", f"job: at {PY}main.py:3",
                    f"job: File \"/w/{PY}test_main.py\", line 2", "job: codemap/test_main.py failed"):
            self.assertTrue(red_tests.mentions(why, clues), why)
        for why in ("job: nothing", "job: other/test_main.py failed", "job: code/python/scripts/codemapper/x.py"):
            self.assertFalse(red_tests.mentions(why, clues), why)
        self.assertEqual(red_tests.clues("error: test run failed", rows), [])

    def test_a_bats_name_without_a_checkout_has_only_its_name(self):
        self.assertEqual(red_tests.clues("not ok 3 abort keeps the queue", []), ["abort keeps the queue"])


class Git(unittest.TestCase):
    """A scratch repository: the base holds two `.bats` files, car A changes one, car B a script of the other's unit."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        sh(self.dir, "git", "init", "-q", "-b", "main")
        sh(self.dir, "git", "config", "user.email", "t@localhost")
        sh(self.dir, "git", "config", "user.name", "t")
        self.put(GATE + "test-abort.bats", '@test "abort keeps the queue" {\n  run true\n}\n')
        self.put(GATE + "main.sh", "echo\n")
        self.put("code/bash/scripts/other/test-other.bats", "@test 'other works' {\n  run true\n}\n")
        self.put(PY + "main.py", "x = 1\n")
        self.put(PY + "test_main.py", "import unittest\n")
        self.base = self.commit("base")
        red_tests.SEEN.clear()

    def put(self, path, text):
        (self.dir / path).parent.mkdir(parents=True, exist_ok=True)
        (self.dir / path).write_text(text)

    def commit(self, msg):
        sh(self.dir, "git", "add", "-A")
        sh(self.dir, "git", "commit", "-qm", msg)
        return sh(self.dir, "git", "rev-parse", "HEAD")

    def lookup(self, **heads):
        return red_tests.repo(str(self.dir), {"base": self.base, "cars": [{"field": k, "head": v}
                                                                          for k, v in heads.items()]})

    def test_a_bats_name_is_found_by_one_git_grep_in_the_base_or_a_cars_new_test(self):
        repo = self.lookup()
        rows = [{"slot": "a", "files": [GATE + "test-abort.bats"]}, {"slot": "b", "files": [GATE + "main.sh"]}]
        self.assertEqual(red_tests.owners(rows, "not ok 3 abort keeps the queue", repo), {"a"}, "its file's car")
        self.assertEqual(red_tests.owners([rows[1]], "not ok 3 abort keeps the queue", repo), {"b"}, "else its unit")
        self.assertEqual(red_tests.owners(rows, "not ok 1 other works", repo), set(), "its file and unit are no car's")
        self.assertEqual(red_tests.owners(rows, "not ok 2 nobody knows this", repo), set())
        self.put(GATE + "test-new.bats", '@test "a new test" {\n  run true\n}\n')
        head = self.commit("car a adds a test")
        rows[0]["files"].append(GATE + "test-new.bats")
        self.assertEqual(red_tests.owners(rows, "not ok 5 a new test", self.lookup(a=head)), {"a"})

    def test_without_a_checkout_only_the_cars_files_resolve_and_a_git_stall_never_raises(self):
        rows = [{"slot": "a", "files": [GATE + "test-abort.bats"]}]
        self.assertEqual(red_tests.owners(rows, "not ok 3 abort keeps the queue", None), set())
        broken = red_tests.repo(str(self.dir / "missing"), {"base": self.base})
        self.assertEqual(red_tests.owners(rows, "not ok 3 abort keeps the queue", broken), set())

    def test_a_unittest_module_no_car_touched_is_found_in_the_bases_tree(self):
        rows = [{"slot": "b", "files": [PY + "main.py"]}, {"slot": "a", "files": ["docs/x.md"]}]
        self.assertEqual(red_tests.owners(rows, "FAIL: test_x (test_main.TestY.test_x)", self.lookup()), {"b"})

    def test_one_grep_per_unmapped_name_is_cached(self):
        repo = self.lookup()
        rows = [{"slot": "a", "files": [GATE + "main.sh"]}]
        calls = []
        real = repo.git
        repo.git = lambda *a: calls.append(a) or real(*a)
        for _ in range(3):
            red_tests.owners(rows, "not ok 3 abort keeps the queue", repo)
        self.assertEqual(len(calls), 1)

    def test_a_red_with_five_names_starts_one_git_process_per_ref_set(self):
        """Plan 0714 D7: all the unmapped bats names of a red go into one `git grep`, not one each."""
        self.put(GATE + "test-new.bats", '@test "a new test" {\n  run true\n}\n@test "second new" {\n}\n')
        head = self.commit("car a adds tests")
        repo = self.lookup(a=head)
        rows = [{"slot": "a", "files": [GATE + "test-new.bats"]}, {"slot": "b", "files": [GATE + "main.sh"]}]
        tail = "\n".join(f"not ok {i} {n}" for i, n in enumerate(
            ["abort keeps the queue", "a new test", "other works", "second new", "nobody knows this"], 1))
        runs = []
        real = red_tests.bounded.run
        with mock.patch.object(red_tests.bounded, "run", lambda argv, **kw: runs.append(argv) or real(argv, **kw)):
            self.assertEqual(red_tests.owners(rows, tail, repo), {"a", "b"})
            self.assertIn("a new test", red_tests.clues(tail, rows, repo), "a second ask is cached")
        self.assertEqual(len(runs), 1, runs)
        self.assertEqual(runs[0][:3], ["git", "grep", "-nF"])
        found = repo.grep(["abort keeps the queue", "a new test", "other works", "second new", "nobody knows this"],
                          [self.base, head])
        self.assertEqual(found["a new test"], [GATE + "test-new.bats"])
        self.assertEqual(found["second new"], [GATE + "test-new.bats"])
        self.assertEqual(found["other works"], ["code/bash/scripts/other/test-other.bats"])
        self.assertEqual(found["abort keeps the queue"], [GATE + "test-abort.bats"])
        self.assertEqual(found["nobody knows this"], [])
        self.assertEqual(len(runs), 1)

    def test_split_looks_a_red_with_several_failures_up_in_one_git_grep(self):
        """The early order splits a red per failure; the bats names of the whole red still cost one grep."""
        self.put(GATE + "test-new.bats", '@test "a new test" {\n  run true\n}\n')
        head = self.commit("car a adds a test")
        cars = [{"field": "a", "head": head, "files": [GATE + "test-new.bats"]},
                {"field": "b", "head": head, "files": [PY + "main.py"]}]
        tail = "\n".join(["noise", "not ok 1 a new test", "not ok 2 abort keeps the queue", "not ok 3 other works",
                          "FAIL: test_x (test_main.TestY.test_x)"])
        train = {"base": self.base, "cars": cars, "orders": {}}
        runs = []
        real = red_tests.bounded.run
        with mock.patch.object(red_tests.bounded, "run", lambda argv, **kw: runs.append(argv) or real(argv, **kw)):
            got, rest = early_order.split(train, {"kind": "car", "evidence": {"cars": cars, "tests": []}}, tail,
                                          main=str(self.dir))
        self.assertEqual(sorted(got), ["a", "b"])
        self.assertEqual([r[1] for r in runs].count("grep"), 1, runs)
        self.assertEqual([r[1] for r in runs].count("ls-tree"), 1, "the unittest module: one tree per train")


if __name__ == "__main__":
    unittest.main()
