"""pause.py keys the record by checkout, lists the session's processes and freezes/thaws process trees."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "pause.py"


def stat(pid):
    return subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()


class PauseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.env = {**os.environ, "PAUSE_ROOT": str(self.dir / "root")}
        self.children = []

    def tearDown(self):
        for c in self.children:
            c.kill()
            c.wait()
        self.tmp.cleanup()

    def run_(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.dir, env=self.env,
                              text=True, capture_output=True)

    def spawn(self):
        # A shell with a child, like a background task: `sleep` is the grandchild of this test.
        c = subprocess.Popen(["bash", "-c", "sleep 60; true"])
        self.children.append(c)
        time.sleep(0.2)
        return c

    def test_path_is_keyed_by_the_directory(self):
        out = self.run_("path").stdout.strip()
        slug = "".join(ch if ch.isalnum() else "-" for ch in os.path.realpath(self.dir))
        self.assertEqual(Path(out).name, f"{slug}.md")
        self.assertTrue(out.startswith(str(self.dir / "root")))

    def test_status_without_a_record_exits_1(self):
        self.assertEqual(self.run_("status").returncode, 1)

    def test_procs_lists_descendants_of_the_root(self):
        c = self.spawn()
        # Through a shell of its own, as the agent's Bash tool runs it: that shell's pipeline is left out.
        out = subprocess.run(["bash", "-c", f'"{sys.executable}" "{SCRIPT}" procs --root {os.getpid()} | cat'],
                             cwd=self.dir, env=self.env, text=True, capture_output=True).stdout
        self.assertIn(f"{c.pid}\t{os.getpid()}", out)
        self.assertIn("sleep 60", out)
        self.assertNotIn("procs --root", out)

    def test_freeze_and_thaw_a_tree(self):
        c = self.spawn()
        r = self.run_("freeze", str(c.pid))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("sleep 60", r.stdout)
        self.assertTrue(stat(c.pid).startswith("T"))
        r = self.run_("thaw")
        self.assertIn(f"thawed {c.pid}", r.stdout)
        self.assertFalse(stat(c.pid).startswith("T"))
        self.assertFalse(list((self.dir / "root").glob("*.procs.json")))

    def test_thaw_reports_gone_processes(self):
        c = self.spawn()
        self.run_("freeze", str(c.pid))
        c.kill()
        c.wait()
        self.children.remove(c)
        time.sleep(0.2)
        self.assertIn(f"gone {c.pid}", self.run_("thaw").stdout)

    def test_finish_moves_the_record_to_history(self):
        rec = Path(self.run_("path").stdout.strip())
        rec.parent.mkdir(parents=True)
        rec.write_text("# Paused\n")
        self.assertEqual(self.run_("status").returncode, 0)
        out = Path(self.run_("finish").stdout.strip())
        self.assertFalse(rec.exists())
        self.assertEqual(out.read_text(), "# Paused\n")
        self.assertEqual(out.parent.name, "history")


if __name__ == "__main__":
    unittest.main()
