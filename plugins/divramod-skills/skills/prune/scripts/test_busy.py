"""busy.py (hal2 plan 0472 step 1, D1): a live workqueue hold means a train builds; no walk then (facts) and no trim
(executor); a missing CLI or an unreadable answer is not busy. No real hal2-cli-workqueue."""

import json
import subprocess
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import busy
import fake_clis
import executor
import facts
import test_executor
from test_farmer import git


def answer(holds, code=0, text=None):
    out = json.dumps({"holds": holds}) if text is None else text
    return lambda *a, **k: subprocess.CompletedProcess(a[0], code, out, "")


HOLD = {"id": "h1", "field": "31", "state": "holding", "class": "landing", "seq": 1, "since": "x", "pid": 1}


class Reason(unittest.TestCase):
    def test_a_live_hold_is_busy_none_is_not(self):
        self.assertIn("train building (hold h1 of field 31", busy.reason("/m", answer([HOLD])))
        self.assertTrue(busy.reason("/m", answer([HOLD])).startswith(busy.DEFERRED))
        self.assertIsNone(busy.reason("/m", answer([])))

    def test_a_missing_cli_or_a_bad_answer_is_not_busy(self):
        def gone(*a, **k):
            raise FileNotFoundError("hal2-cli-workqueue")
        self.assertIsNone(busy.reason("/m", gone))
        self.assertIsNone(busy.reason("/m", answer([HOLD], code=1)))
        self.assertIsNone(busy.reason("/m", answer([], text="not json")))
        self.assertIsNone(busy.reason("/m", answer([], text="[]")))

    def test_the_answer_as_a_program_for_the_tollman(self):
        """Plan 0480 D4: the tollman's prune duty runs busy.py live (it never imports /prune)."""
        import contextlib
        import io
        for value, want in (("deferred: train building (hold h1 of field 31, holding)", "deferred: train building "
                             "(hold h1 of field 31, holding)\n"), (None, "\n")):
            out = io.StringIO()
            with mock.patch.object(busy, "reason", return_value=value) as reason, contextlib.redirect_stdout(out):
                self.assertEqual(busy.main(["--repo", "/m"]), 0)
            reason.assert_called_once_with("/m")
            self.assertEqual(out.getvalue(), want)


class Trims(fake_clis.Farm):
    """The executor on the scratch farm: no trim, no muck out and no size walk while a hold is live, trims after it."""

    def short_farm(self):
        git(self.add("25"), "commit", "-q", "--allow-empty", "-m", "work")  # not free: phase 2's
        target = self.base / "25/code/rust/target"
        target.mkdir(parents=True)
        (target / "x.o").write_text("x" * 100)
        self.disk = dict(test_executor.SHORT)
        return target

    def test_no_trim_and_no_size_walk_while_a_hold_is_active_then_the_trim_runs(self):
        target = self.short_farm()
        self.busy = "deferred: train building (hold h1 of field 31, holding)"
        with mock.patch.object(executor.sizes, "walk") as walk:
            code, lines = self.prune()
        self.assertEqual(code, 0, lines)
        walk.assert_not_called()
        self.assertTrue(target.exists(), "nothing trimmed during the hold")
        self.assertTrue(any(l.startswith("skipped: deferred: train building") for l in lines), lines)
        self.busy = None
        code, lines = self.prune()
        self.assertEqual(code, 0, lines)
        self.assertFalse(target.exists(), "the gap between trains: the trim runs")

    def test_a_hold_that_starts_between_two_trims_stops_the_phase(self):
        target = self.short_farm()
        holds = iter([None])  # the run's facts see no hold; the check before the first trim does
        with mock.patch.object(executor.busy, "reason",
                               side_effect=lambda main: next(holds, "deferred: train building (hold h2)")):
            code, lines = self.prune()
        self.assertEqual(code, 0, lines)
        self.assertTrue(target.exists())
        self.assertTrue(any(l.startswith("stopped: deferred: train building") for l in lines), lines)


if __name__ == "__main__":
    unittest.main()
