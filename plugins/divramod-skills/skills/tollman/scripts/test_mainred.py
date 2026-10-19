"""Hal2 plan 0360 step 8 (D9, D29, D30): a red main is the tollman's, no longer the farmer's. The duty `mainred` reruns
a transient red by code, once per run, and wakes nobody; a real one wakes the session once with the log's tail. The
session's `order main` with no train standing makes the fix the first car of the next train (own_fix.py). Fakes
only: the CI scan and the failed log are data, the farm's origin is a bare repository, no real gh."""

import datetime as dt
import unittest

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mainred
import own_fix
import tick
import train_state
import transient
import triage
import wake
import tollman
from engine_farm import OWN, Farm, out
from test_farmer import git

NOW = dt.datetime(2026, 10, 17, 12, 0)


def red(run=9, kind="main-red", branch="main"):
    return {"kind": kind, "run": run, "workflow": "ci", "branch": branch, "url": f"u/{run}", "sha": "abc",
            "why": f"ci failure on {branch}", "failed_jobs": ["test: cargo nextest"]}


def ctx(**kw):
    return {"top": "/x/tollman-hal2", "main": "/x/hal2", "now": NOW, "log": [], "panes": {}, **kw}


def planned(findings, logs, rows=(), log=()):
    actions = mainred.plan({}, ctx(log=list(log)), {"findings": findings}, lambda run: logs, list(rows))
    return tick.fresh(actions, list(log), NOW, "tollman")


def logged(actions):
    return [{"at": NOW.isoformat(), "key": a["key"], "kind": a["kind"]} for a in actions if a.get("key")]


def standing(state):
    return [{"kind": "formed", "train": "07@x", "slot": OWN, "cars": [{"field": "07"}], "at": "x"}] + (
        [{"kind": "started", "train": "07@x", "pid": 1}] if state != "formed" else []) + (
        [{"kind": "red", "train": "07@x", "status": "gate_failed"}] if state == "red" else [])


class Duty(unittest.TestCase):
    def test_a_transient_main_red_is_rerun_once_by_code_and_wakes_nobody(self):
        first = planned([red()], "x\ncurl: ECONNRESET by peer\n")
        self.assertEqual([(a["do"], a["kind"]) for a in first], [("run", "main-red-rerun")])
        self.assertEqual(first[0]["argv"], ["gh", "run", "rerun", "9", "--failed"])
        again = planned([red()], "ECONNRESET", log=logged(first))
        self.assertEqual([(a["do"], a["kind"]) for a in again], [("wake", "main-red")],
                         "once per run: red again after its rerun, the session judges it")
        self.assertIn("red again after its one rerun", again[0]["text"])
        self.assertEqual(planned([red()], "ECONNRESET", log=logged(first) + logged(again)), [])
        self.assertEqual([a["kind"] for a in planned([red(10)], "ECONNRESET", log=logged(first))],
                         ["main-red-rerun"], "a new run is rerun again")

    def test_a_real_main_red_wakes_once_with_the_log_s_tail(self):
        tail = "noise\n" * 2000 + "assert 1 == 2 in hal2-core"
        first = planned([red()], tail)
        self.assertEqual([(a["do"], a["kind"], a["key"]) for a in first], [("wake", "main-red", "main-red:9")])
        evidence = first[0]["evidence"]
        self.assertTrue(evidence["log_tail"].endswith("assert 1 == 2 in hal2-core"))
        self.assertLessEqual(len(evidence["log_tail"]), triage.TAIL)
        self.assertIn("tollman.py order main", first[0]["text"])
        self.assertEqual(planned([red()], tail, log=logged(first)), [], "one wake per run")

    def test_only_main_red_findings_are_the_tollman_s(self):
        self.assertEqual(planned([red(kind="slot-red", branch="05"), red(kind="queued-long")], "assert"), [])

    def test_while_a_train_lands_the_wake_waits_a_red_train_takes_the_fix(self):
        self.assertEqual(planned([red()], "assert", standing("landing")), [], "the train's own triage first")
        self.assertEqual(planned([red()], "assert", standing("formed")), [])
        self.assertEqual([a["kind"] for a in planned([red()], "assert", standing("red"))], ["main-red"])
        self.assertEqual([a["kind"] for a in planned([red()], "ECONNRESET", standing("landing"))], ["main-red-rerun"])

    def test_the_transient_patterns_are_the_tollman_s_and_triage_uses_them(self):
        self.assertIs(triage.transient.TRANSIENT, transient.TRANSIENT)
        self.assertTrue(transient.TRANSIENT.search("The runner has received a shutdown signal"))


class NextTrain(Farm):
    """`order main` with no train standing: the fix waits for nobody and rides as the next train's first car."""

    def own_fix(self):
        git(self.wm, "switch", "-q", "-C", own_fix.orders.OWN_FIX, "HEAD")
        (self.wm / "barn-fix.txt").write_text("fixed")
        git(self.wm, "add", "barn-fix.txt")
        git(self.wm, "commit", "-qm", "the barn's fix")
        sha = out(self.wm, "rev-parse", "HEAD")
        git(self.wm, "switch", "-q", OWN)
        return sha

    def test_without_a_train_the_fix_is_the_first_car_of_the_next_train(self):
        code, text = self.call("order", "main", "--why", "the barn is red: linux / rust-test")
        self.assertEqual(code, 0, text)
        line = train_state.lines(str(self.main))[-1]
        self.assertEqual((line["kind"], line["field"], line["branch"], line.get("train")),
                         ("order", "main", "tollman-train-fix", None))
        items = wake.read(str(self.main), tollman.WIRING)["items"]
        self.assertEqual(items[-1]["kind"], "fix-order-main")
        self.assertIn("first car of the next train", items[-1]["text"])
        self.assertTrue(own_fix.carries(str(self.wm)), "the field holds the fix by design: the round goes on")
        self.crop("07", {"seven.txt": "7"}, plan="0294-tollman-role")
        self.round()
        self.assertEqual((self.last, self.train()), ([], None), "the next train waits for the open fix")
        code, text = self.call("fixed", "main", self.own_fix())
        self.assertEqual(code, 0, text)
        self.assertIn("first car of the next train", text)
        self.round()
        self.assertEqual(self.last[0][:2], ("form", "run"))
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["07"])
        subjects = out(self.cw, "log", "--first-parent", "--format=%s", "origin/main..HEAD").splitlines()  # plan 0375 D5
        self.assertEqual(subjects[-1], f"Merge {own_fix.orders.OWN_FIX} into {OWN} (fix order main-fix-1)",
                         "the fix lies first, under every car")
        self.assertIn("Merge branch '07'", subjects[-2])
        self.ends({"status": "landed", "run": "https://github.com/x/runs/1"}, land=True)
        self.round()
        self.assertFalse(own_fix.waiting(train_state.lines(str(self.main))), "in the barn: no fix waits")

    def test_a_second_own_order_while_one_is_open_and_a_fix_on_the_wrong_branch_are_refused(self):
        self.assertEqual(self.call("order", "main", "--why", "red")[0], 0)
        code, text = self.call("order", "main", "--why", "red again")
        self.assertEqual(code, 1, text)
        self.assertIn("main-fix-1", text)
        sha = self.own_fix()
        git(self.wm, "switch", "-q", own_fix.orders.OWN_FIX)
        code, text = self.call("fixed", "main", sha)
        self.assertEqual(code, 1, text)
        self.assertIn(f"switch back to {OWN}", text)
        git(self.wm, "switch", "-q", OWN)
        self.assertEqual(self.call("fixed", "main", sha)[0], 0)


if __name__ == "__main__":
    unittest.main()
