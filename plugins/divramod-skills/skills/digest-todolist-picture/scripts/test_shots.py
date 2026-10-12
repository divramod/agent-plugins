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
    """PATH with git but without hal2-cli-shooter."""
    keep = {str(Path(shutil.which("git")).parent), str(Path(sys.executable).parent), "/usr/bin", "/bin"}
    cli = shutil.which("hal2-cli-shooter")
    if cli:
        keep.discard(str(Path(cli).parent))
    return os.pathsep.join(sorted(keep))


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


if __name__ == "__main__":
    unittest.main()
