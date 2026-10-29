#!/usr/bin/env python3
"""Tests for shots.py (offline; the CLI comparison runs only where hal2-cli-shooter is installed)."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("shots", HERE / "shots.py")
shots = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shots)

FILE = """# main

notes about the feature

## shot 3 newest
body three

## x shot 2 sent one (2026-09-25 17:33:42) [00]

```
## shot 9 fenced
```

## shot 1 oldest
"""


def run(args, items=None, cwd=None, path=None):
    env = dict(os.environ)
    if path is not None:
        env["PATH"] = path
    r = subprocess.run([sys.executable, str(HERE / "shots.py"), *args], input=json.dumps(items or []),
                       capture_output=True, text=True, cwd=cwd, env=env)
    if r.returncode != 0:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


def no_cli_path() -> str:
    """PATH with git and python only: a folder of links to them, never a system folder, where a machine with hal9k
    installed has hal2-cli-shooter too (the T460p's /usr/bin, plan 0263 row 30)."""
    folder = Path(tempfile.mkdtemp(prefix="no-cli-"))
    for tool in ("git", Path(sys.executable).name):
        found = shutil.which(tool) or sys.executable
        (folder / Path(found).name).symlink_to(Path(found).resolve())
    return str(folder)


class TestInsert(unittest.TestCase):
    def test_numbers_skip_fenced_and_decimal_headers(self):
        self.assertEqual(shots.next_number(FILE), 4)
        self.assertEqual(shots.next_number("## shot 2.1 a\n## shot ? b\n"), 3)
        self.assertEqual(shots.next_number("# empty\n"), 1)

    def test_new_shot_goes_above_the_first_shot(self):
        text, number, line = shots.insert_shot(FILE, "new  idea", "\ndo the thing  \n\n")
        self.assertEqual(number, 4)
        self.assertEqual(line, 5)
        self.assertIn("notes about the feature\n\n## shot 4 new idea\ndo the thing\n\n## shot 3 newest\n", text)

    def test_empty_shotfile_gets_the_shot_at_the_end(self):
        text, number, _ = shots.insert_shot("# ideas\n", "first", "")
        self.assertEqual((text, number), ("# ideas\n\n## shot 1 first\n", 1))

    def test_rejects_empty_and_header_bodies(self):
        with self.assertRaises(ValueError):
            shots.insert_shot(FILE, " ", "")
        with self.assertRaises(ValueError):
            shots.insert_shot(FILE, "t", "## shot 7 smuggled")

    def test_open_titles_drop_stamps_and_sent_shots(self):
        open_shots = [(n, t) for _, n, t, done in shots.headers(FILE.splitlines()) if not done]
        self.assertEqual(open_shots, [("3", "newest"), ("1", "oldest")])


class TestCommands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        (self.repo / "shotfiles").mkdir(parents=True)
        (self.repo / "shotfiles" / "main.md").write_text(FILE)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_targets_and_preview_number_items_in_order(self):
        t = run(["targets", "--repo", str(self.repo), "--no-global"])
        self.assertEqual([(f["name"], f["next"]) for f in t["repo"]["files"]], [("main", 4)])
        items = [{"shotfile": "main", "title": "a", "repo": str(self.repo)},
                 {"shotfile": "ideas", "title": "b", "repo": str(self.repo)},
                 {"shotfile": "main", "title": "c", "body": "x", "repo": str(self.repo)}]
        p = run(["preview"], items)
        self.assertEqual([(i["number"], i["new_file"]) for i in p], [(4, False), (1, True), (5, False)])
        self.assertEqual(p[2]["header"], "## shot 5 c")
        self.assertEqual((self.repo / "shotfiles" / "main.md").read_text(), FILE)  # preview writes nothing

    def test_repos_lists_git_repos_and_marks_the_current_one(self):
        root = Path(self.tmp.name)
        (root / "plain").mkdir()
        subprocess.run(["git", "init", "-q", str(root / "noshots")], check=True)
        r = run(["repos", "--root", str(root)], cwd=self.repo)
        self.assertEqual([(x["name"], x["shotfiles"], x["current"]) for x in r["repos"]],
                         [("noshots", False, False), ("repo", True, True)])

    def test_fallback_write_without_the_cli(self):
        items = [{"shotfile": "main", "title": "a", "body": "do a", "repo": str(self.repo), "number": 4},
                 {"shotfile": "ideas", "title": "b", "repo": str(self.repo)}]
        w = run(["write"], items, path=no_cli_path())
        self.assertEqual([(i["number"], i["via"]) for i in w], [(4, "shots.py"), (1, "shots.py")])
        self.assertNotIn("previewed", w[0])
        self.assertTrue((self.repo / "shotfiles" / "main.md").read_text().startswith(
            "# main\n\nnotes about the feature\n\n## shot 4 a\ndo a\n\n## shot 3 newest\n"))
        self.assertEqual((self.repo / "shotfiles" / "ideas.md").read_text(), "# ideas\n\n## shot 1 b\n")

    @unittest.skipUnless(shutil.which("hal2-cli-shooter"), "hal2-cli-shooter not installed")
    def test_fallback_writes_exactly_what_the_cli_writes(self):
        other = Path(self.tmp.name) / "other"
        shutil.copytree(self.repo, other)
        cases = [{"shotfile": "main", "title": "new  idea", "body": "\nline one\n\nline two  \n"},
                 {"shotfile": "topic-fresh", "title": "only a title", "body": ""}]
        w_cli = run(["write"], [{**c, "repo": str(self.repo)} for c in cases])
        w_py = run(["write"], [{**c, "repo": str(other)} for c in cases], path=no_cli_path())
        self.assertEqual([i["via"] for i in w_cli], ["hal2-cli-shooter"] * 2)
        self.assertEqual([i["number"] for i in w_cli], [i["number"] for i in w_py])
        for name in ("main.md", "topic-fresh.md"):  # a new shotfile needs a prefix (hal2 .adr/shotfiles.md)
            self.assertEqual((other / "shotfiles" / name).read_text(), (self.repo / "shotfiles" / name).read_text())


def debug_cli(name: str) -> Path | None:
    """This checkout's debug build of a hal2 CLI (the store home's commands are in it), else None."""
    for parent in HERE.parents:
        built = parent / "code/rust/target/debug" / name
        if built.is_file():
            return built
    return None


SHOOTER, PLANS = debug_cli("hal2-cli-shooter"), debug_cli("hal2-cli-plans")


@unittest.skipUnless(SHOOTER and PLANS, "no debug build of hal2-cli-shooter and hal2-cli-plans")
class TestStoreHome(unittest.TestCase):
    """A farm whose home is the plan store (plan 0409 step 10): no shotfiles/ folder, only the CLI."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="digest-store-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        env = {"HAL2_DATA_ROOT": str(self.tmp / "data"), "HAL2_STATE_DIR": str(self.tmp / "state"),
               "HAL2_CONFIG_DIR": str(self.tmp / "config"), "HOME": str(self.tmp / "home"),
               "HAL2_HOME": str(self.tmp / "home"), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)
        for args in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "init"]):
            subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)
        home = subprocess.run([str(PLANS), "home", "store", "--json"], cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(json.loads(home.stdout)["home"], "store", home.stderr)
        folder = Path(no_cli_path())
        (folder / "hal2-cli-shooter").symlink_to(SHOOTER)
        self.path = str(folder)

    def test_targets_preview_and_write_go_through_the_cli(self):
        items = [{"shotfile": "topic-x", "title": "first", "body": "why", "repo": str(self.repo)},
                 {"shotfile": "topic-x", "title": "second", "repo": str(self.repo)}]
        t = run(["targets", "--repo", str(self.repo), "--no-global"], path=self.path)
        self.assertEqual((t["repo"]["shotfiles"], t["repo"]["files"]), ("store:farm", []))
        p = run(["preview"], items, path=self.path)
        self.assertEqual([(i["number"], i["new_file"], i["path"]) for i in p],
                         [(1, True, "store:farm/topic-x.md"), (2, False, "store:farm/topic-x.md")])
        w = run(["write"], items, path=self.path)
        self.assertEqual([(i["number"], i["via"], i["path"]) for i in w],
                         [(1, "hal2-cli-shooter", "store:farm/topic-x.md"),
                          (2, "hal2-cli-shooter", "store:farm/topic-x.md")])
        self.assertNotIn("previewed", w[1])
        t = run(["targets", "--repo", str(self.repo), "--no-global"], path=self.path)
        files = t["repo"]["files"]
        self.assertEqual([(f["name"], f["next"], [o["title"] for o in f["open"]]) for f in files],
                         [("topic-x", 3, ["second", "first"])])
        self.assertFalse((self.repo / "shotfiles").exists())

    def test_repos_marks_a_store_home_repository_as_having_shotfiles(self):
        r = run(["repos", "--root", str(self.tmp)], cwd=self.repo, path=self.path)
        self.assertEqual([(x["name"], x["shotfiles"]) for x in r["repos"]], [("repo", True)])


if __name__ == "__main__":
    unittest.main()
