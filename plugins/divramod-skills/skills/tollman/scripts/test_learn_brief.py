"""Hal2 plan 0490 step 14 (D10): a learning that needs a code fix posts one fix brief to the farmer (learn_brief.py);
a repeat of a briefed case, a case a plan or a running delegation already names, and a model-rule learning post none.
Hermetic: a tmp role folder, the plans' text and the delegation ledger passed in, the delegation and the detached
child faked: no session, git, GitHub or farmer state."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import learn_brief
import learnings

TODAY = "2026-10-30"


class Fake:
    def __init__(self, state="running"):
        self.state, self.calls = state, []

    def __call__(self, action):
        self.calls.append(action)
        return {"key": action["key"], "state": self.state, "slot": "31"}


class Brief(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "roles" / "tollman"
        self.dir.mkdir(parents=True)
        patch = mock.patch.object(learn_brief.mtm_scan, "main_checkout", return_value=tmp.name)
        patch.start()
        self.addCleanup(patch.stop)

    def add(self, case, code="y", rule="restart the push with a lease", slug=None, **kw):
        return learnings.add(self.dir, case, "the cause in scripts/engine.py", rule, code, slug=slug,
                             at="2026-10-30 09:00Z", **kw)

    def run_brief(self, numbers=None, delegate=None, **kw):
        delegate = delegate or Fake()
        kw = {"texts": [], "held": {}, "wait": True, "today": TODAY} | kw
        return learn_brief.brief(self.dir, "/x/hal2", numbers, delegate=delegate, **kw), delegate

    def field(self, n):
        return next(e for e in learnings.read(self.dir) if e.n == n).fields.get("brief", "")

    def test_a_code_learning_posts_one_brief_with_evidence_files_and_the_speed_rule(self):
        e = self.add("train 7 failed at scripts/engine.py: non-fast-forward", slug="push-refused")
        rows, delegate = self.run_brief()
        self.assertEqual([(r["n"], r["state"]) for r in rows], [(e.n, "new")])
        (a,) = delegate.calls
        self.assertEqual((a["key"], a["duty"], a["kind"]), ("brief:fix-l1-push-refused", "learn", "fix-brief"))
        text = Path(a["brief"]["brief_file"]).read_text()
        self.assertTrue(text.startswith("---\ntype: Brief\nschema: 1\n"))
        for want in ("non-fast-forward", "restart the push with a lease", "- `scripts/engine.py`", "decision D9",
                     "regression test", "(data, not instructions)"):
            self.assertIn(want, text)
        self.assertEqual(self.field(1), "2026-10-30 placed running")

    def test_a_repeat_of_the_same_run_posts_none(self):
        self.add("a train broke")
        self.run_brief()
        rows, delegate = self.run_brief()
        self.assertEqual((rows, delegate.calls), ([], []))
        rows, delegate = self.run_brief({1})  # asked for by number: it has its brief
        self.assertEqual(([r["state"] for r in rows], delegate.calls), (["done"], []))

    def test_a_second_learning_of_the_same_case_is_a_repeat(self):
        self.add("push refused: not a fast-forward after a breakup", slug="push-refused")
        self.run_brief()
        again = self.add("push refused again, not a fast-forward after a breakup", slug="push-refused-again")
        rows, delegate = self.run_brief()
        self.assertEqual([(r["n"], r["state"]) for r in rows], [(again.n, "repeat")])
        self.assertEqual(delegate.calls, [])
        self.assertIn("repeat: L1 has a brief", self.field(again.n))
        self.assertEqual(self.run_brief()[0], [])  # and it is not looked at again

    def test_a_different_case_still_posts(self):
        self.add("push refused: not a fast-forward", rule="lease the push")
        self.run_brief()
        self.add("pretest used its whole budget", rule="stop at the first green marker", slug="pretest-budget")
        rows, delegate = self.run_brief()
        self.assertEqual([r["state"] for r in rows], ["new"])
        self.assertEqual(len(delegate.calls), 1)

    def test_a_case_a_plan_or_a_live_delegation_names_posts_none(self):
        self.add("one", slug="alpha-case")
        self.add("two entirely other words here", rule="another way altogether", slug="beta-case")
        brief = self.dir / "held.md"
        brief.write_text("# fix\nthe beta-case learning\n")
        held = {"flaky:t": {"state": "running", "title": "x", "brief": str(brief)},
                "old": {"state": "landed", "title": "L1 alpha-case"}}
        rows, delegate = self.run_brief(texts=["| 3 | fix L1 | done |"], held=held)
        self.assertEqual([(r["n"], r["state"]) for r in rows], [(1, "in-plan"), (2, "in-plan")])
        self.assertEqual(delegate.calls, [])
        self.assertIn("in-plan: a plan names it", self.field(1))
        self.assertIn("in-plan: delegation flaky:t", self.field(2))

    def test_a_model_rule_learning_posts_none(self):
        self.add("the model chose the wrong wake", code="n")
        rows, delegate = self.run_brief()
        self.assertEqual((rows, delegate.calls), ([], []))  # not due by default
        rows, delegate = self.run_brief({1})
        self.assertEqual(([r["state"] for r in rows], delegate.calls), (["model-rule"], []))
        self.assertEqual(self.field(1), "")

    def test_a_failed_post_is_marked_and_retried_by_the_next_brief(self):
        self.add("a train broke")
        self.run_brief(delegate=Fake("error"))
        self.assertIn("failed error", self.field(1))
        rows, delegate = self.run_brief()
        self.assertEqual(([r["state"] for r in rows], len(delegate.calls)), (["new"], 1))
        self.assertIn("placed running", self.field(1))

    def test_a_waiting_delegation_counts_as_placed(self):
        self.add("a train broke")
        self.run_brief(delegate=Fake("waiting"))
        self.assertIn("placed waiting", self.field(1))

    def test_the_post_is_detached_and_not_awaited(self):
        self.add("a train broke")
        popen = mock.Mock()
        with mock.patch.object(learn_brief.subprocess, "Popen", popen):
            rows = learn_brief.brief(self.dir, "/x/hal2", None, texts=[], held={}, today=TODAY)  # no wait
        (argv,), kw = popen.call_args
        self.assertEqual(argv[2:4], ["send", "--dir"])
        self.assertTrue(kw["start_new_session"])
        self.assertEqual(popen.return_value.method_calls, [])  # nothing waited for
        self.assertEqual(rows[0]["state"], "new")
        self.assertIn("posting", self.field(1))

    def test_add_with_brief_spawns_only_for_a_code_learning(self):
        popen = mock.Mock()
        with mock.patch.object(learn_brief.subprocess, "Popen", popen), mock.patch("builtins.print"):
            learnings.main(["--dir", str(self.dir), "add", "--case", "c", "--cause", "x", "--rule", "r", "--code", "n",
                            "--brief"])
            popen.assert_not_called()
            learnings.main(["--dir", str(self.dir), "add", "--case", "c2", "--cause", "x", "--rule", "r", "--code", "y",
                            "--brief"])
        (argv,), kw = popen.call_args
        self.assertEqual((argv[2:4], argv[-3:], kw["start_new_session"]),
                         (["brief", "--dir"], ["--n", "2", "--wait"], True))

    def test_send_posts_the_written_brief_through_the_farmer_path(self):
        self.add("a train broke")
        self.run_brief(delegate=Fake("error"))
        fake = Fake("running")
        self.assertEqual(learn_brief.send(self.dir, "/x/hal2", 1, today=TODAY, delegate=fake)["state"], "running")
        self.assertEqual(fake.calls[0]["brief"]["brief_file"], str(self.dir / "briefs" / "fix-L1.md"))
