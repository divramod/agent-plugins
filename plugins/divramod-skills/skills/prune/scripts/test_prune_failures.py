"""A failed field in a prune round (hal2 plan 0695 step 14 round 2, field 05's `.pytest_cache`): a session-less field's
trim of a self-ignored cache folder succeeds, a refusal is counted once per field with its reason, and the timer's state
and alarm carry that reason. Scratch farm and fake CLIs only (HAL_CLEANUP_CLI empty: cleanup.py's own fallback)."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fake_clis
import prune_act
import prune_timer as pt
import timer_state as ts
from fake_clis import parse
from executor_out import failure_lines, reason
from test_farmer import git
from test_executor import SHORT


class Failures(fake_clis.Farm):
    def rules(self, text: str, trim: str = "") -> None:
        (self.main / ".hal").mkdir(exist_ok=True)
        (self.main / ".hal/cleanup").write_text(text)
        git(self.main, "add", ".hal/cleanup")
        git(self.main, "commit", "-qm", "cleanup rules")
        git(self.main, "push", "-q", "origin", "main")
        if trim:
            (self.main / ".hal/prune.toml").write_text(f'[phases]\ntrim = ["{trim}"]\n')

    def cache(self, field: Path, name: str = ".pytest_cache") -> Path:
        """A cache folder that ignores itself with its own `.gitignore` (`*`), as pytest and ruff write them."""
        (field / name).mkdir()
        (field / name / ".gitignore").write_text("*\n")
        (field / name / "v").write_text("x")
        return field / name

    def test_a_session_less_trim_of_a_self_ignored_cache_succeeds(self):
        self.rules("**/.pytest_cache\n", trim=".pytest_cache")
        path = self.add("23")  # 10-99 free field: removed, so use a field that stays: a dirty one with a commit not pushed
        git(path, "commit", "-q", "--allow-empty", "-m", "not pushed")
        cache = self.cache(path)
        self.disk = dict(SHORT)
        code, lines = self.prune()
        out = parse(lines)
        self.assertEqual(code, 0, lines)
        self.assertEqual([(s[0], s[1]) for s in out["phase-2"]], [("field 23", "success")], lines)
        self.assertFalse(cache.exists())

    def test_a_field_failing_twice_is_counted_once_with_a_reason_per_action(self):
        self.rules("keepme\n", trim="keepme")
        (self.main / ".gitignore").write_text("target/\ncode/rust/target/\nkeepme/\n")
        (self.main / "keepme").mkdir()
        (self.main / "keepme/tracked.txt").write_text("tracked\n")
        git(self.main, "add", "-f", ".gitignore", "keepme/tracked.txt")
        git(self.main, "commit", "-qm", "ignore keepme")
        git(self.main, "push", "-q", "origin", "main")
        field = self.add("05")
        self.disk = dict(SHORT)
        refusal = ("failure", "skip    keepme: holds tracked files\nfreed 0B")  # muck out and trim both refuse it
        with mock.patch.object(prune_act, "clean", return_value=refusal):
            code, lines = self.prune()
        self.assertEqual(code, 1, lines)
        self.assertEqual([x for x in lines if x.startswith("failed:")], ["failed: 05"], lines)
        why = [x for x in lines if x.startswith("failure 05 ")]
        self.assertEqual([x.split(":")[0] for x in why], ["failure 05 muck-out", "failure 05 trim"], lines)
        self.assertTrue(all("keepme: holds tracked files" in x for x in why), why)
        self.assertTrue((field / "keepme/tracked.txt").exists())

    def test_the_reason_is_the_refusing_line_else_the_last(self):
        self.assertEqual(reason("a\nskip .ruff_cache: not git-ignored\nwould free 0B"), "skip .ruff_cache: not git-ignored")
        self.assertEqual(reason("one\ntwo"), "two")
        rows = [{"field": "05", "action": "muck-out", "status": "failure", "why": "w1"},
                {"field": "01", "action": "muck-out", "status": "success", "why": "ok"},
                {"field": "05", "action": "trim", "status": "failure", "why": "w2"}]
        self.assertEqual(failure_lines(rows), ["failed: 05", "failure 05 muck-out: w1", "failure 05 trim: w2"])


class ReasonInTheState(unittest.TestCase):
    def test_a_red_round_keeps_each_reason_in_its_state_and_the_alarm(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / pt.LOG).write_text("failed: 05\nfailure 05 trim: skip .pytest_cache: not git-ignored\n"
                                         "failure 05 muck-out: skip .pytest_cache: not git-ignored\n")
            self.assertEqual(pt.failures(folder), [
                {"field": "05", "action": "trim", "reason": "skip .pytest_cache: not git-ignored"},
                {"field": "05", "action": "muck-out", "reason": "skip .pytest_cache: not git-ignored"}])
            ts.save(folder, {"label": "x", "round": {"id": 7, "pid": 0, "started": 1.0, "ended": None, "rc": None},
                             "seen": {}})
            state = ts.load(folder)
            state["round"].update(ended=2.0, rc=1, failed=pt.failures(folder))
            ts.save(folder, state)
            alarms = []
            pt.tick("/nonexistent", folder, 100.0, start=lambda *a: 1, alarm=lambda c, r, repo: alarms.append((c, r)))
            self.assertEqual(alarms[0][0], "prune-failed")
            self.assertIn("05 trim: skip .pytest_cache: not git-ignored", alarms[0][1])
            self.assertIn("failed: 05 trim: skip .pytest_cache", ts.line(folder, 101.0))


if __name__ == "__main__":
    unittest.main()
