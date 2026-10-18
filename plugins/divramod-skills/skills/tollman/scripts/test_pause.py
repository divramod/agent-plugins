"""Hal2 plan 0360 step 18 (D58, D59, D61, D62): a smuggle pauses the train's landing. The tollman reads `paused_by`
on the carrier's ticket and holds the train paused and frozen (one tick.log line per pause, no wake); a run the pause
cancelled is no red; a merged run lands as ever; on resume the newer run is watched; a resume conflict and a red
that touches a smuggle's files are fix orders to the smuggling field by code. gh is gh_fake.py's, git a temporary
repository: no real gh, queue, remote or session."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import pause
import smuggled
import train_state
import trains
import triage
from gh_fake import FakeGh, job, run

AT = "2026-10-17T10:00:00Z"
NAME = "07+09@" + AT
TOP, MAIN = "/no/such/farm/tollman-hal2", "/no/such/farm"
CARS = [{"field": "07", "branch": "07", "head": "7" * 40, "plan": "0360-tollman-and-skills"},
        {"field": "09", "branch": "09", "head": "9" * 40, "plan": ""}]
SINCE = "2026-10-17T10:20:00Z"
BY = {"slot": "03", "seq": 41, "since": SINCE}
OLD = run(501, "land/tollman-hal2", "2026-10-17T10:06:00Z", conclusion="cancelled")
NEW = run(502, "land/tollman-hal2", "2026-10-17T10:40:00Z", status="in_progress")


def line(kind, at=AT, **kw):
    return {"schema": 1, "at": at, "kind": kind, "slot": "tollman-hal2", "train": NAME, **kw}


FORMED = line("formed", cars=CARS, base="b" * 40)
STARTED = line("started", at="2026-10-17T10:05:00Z", pid=4711)
NOTED = line("run", at="2026-10-17T10:07:00Z", run=OLD["url"])
PAUSED = line("pause", at="2026-10-17T10:21:00Z", field="03", seq=41, since=SINCE, run=OLD["url"])


def mine(**kw):
    return {"slot": "tollman-hal2", "position": 0, "seq": 30, "pid": 4711, "state": "active", "covers": [], **kw}


def shape(actions):
    return [(a["kind"], a["do"], a["key"]) for a in actions]


def plan(rows, tickets, alive=(4711,), result=None):
    return trains.plan(TOP, MAIN, list(tickets), list(rows), {}, alive=lambda pid: pid in alive,
                       result=lambda main: result)


class Paused(unittest.TestCase):
    def setUp(self):
        self.gh = FakeGh([OLD]).start(self)

    def test_a_ticket_paused_by_a_smuggle_pauses_the_train_and_plan_acts_nothing_but_one_line(self):
        self.assertEqual(pause.of(mine(paused_by=BY)), BY)
        self.assertIsNone(pause.of(mine(paused_by=None)))
        out = plan([FORMED, STARTED, NOTED], [mine(paused_by=BY)])
        self.assertEqual(shape(out), [("train-paused", "run", f"pause:{NAME}:41")])
        self.assertEqual(out[0]["text"], f"train {NAME} is paused by smuggle 03 since {SINCE}")
        self.assertEqual(out[0]["argv"][2:], ["pause", "--field", "03", "--seq", "41", "--since", SINCE, "--run",
                                              OLD["url"], "--repo", TOP])
        rows = [FORMED, STARTED, NOTED, PAUSED]
        self.assertEqual(train_state.standing(rows)["state"], "paused")
        self.assertEqual(plan(rows, [mine(paused_by=BY)]), [], "recorded: nothing more, no wake")
        self.assertEqual(plan(rows, [mine(paused_by=BY)], alive=()), [], "its process ended paused: no restart yet")
        later = dict(BY, seq=42)
        self.assertEqual(shape(plan(rows, [mine(paused_by=later)])), [("train-paused", "run", f"pause:{NAME}:42")],
                         "a second smuggle: its own line")
        self.assertIn("pause", train_state.KINDS)

    def test_a_run_the_pause_cancelled_is_no_red(self):
        cancelled = {"id": "501", "url": OLD["url"], "cancelled": True}
        pauses = [{"field": "03", "seq": 41, "since": SINCE, "run": OLD["url"]}]
        self.assertEqual(triage.paused_by(cancelled, pauses), "03")
        self.assertIsNone(triage.paused_by(dict(cancelled, cancelled=False), pauses), "a real red is red")
        self.assertIsNone(triage.paused_by(dict(cancelled, id="9"), pauses), "another run")
        resumed = [FORMED, STARTED, NOTED, PAUSED, line("resumed", at="2026-10-17T10:30:00Z", field="03")]
        train = train_state.standing(resumed)
        FakeGh([OLD], jobs={"501": [job("d1-01-rust-test", "cancelled"), job("d1-02-ts-test", "cancelled")]},
               logs={"501": "The operation was canceled."}).start(self)
        out = trains.settle(TOP, train, {"status": "gate_failed", "run": OLD["url"], "red": [{"name": "d1-01-rust-test"}]},
                            {})
        self.assertEqual([(a["kind"], a["do"]) for a in out], [("restart", "run")], "no red, no wake, no runner retry")
        self.assertNotIn("retry", [a["argv"][2] for a in out])

    def test_a_merged_run_during_the_pause_lands_the_normal_way(self):
        out = plan([FORMED, STARTED, NOTED, PAUSED], [mine(paused_by=BY, pid=0)], alive=(),
                   result={"status": "landed", "commit": "c1", "run": OLD["url"]})
        self.assertEqual(out[0]["kind"], "landed")
        self.assertIn("in-the-barn", [a["kind"] for a in out])

    def test_resume_watches_the_newer_run_and_clears_paused(self):
        rows = [FORMED, STARTED, NOTED, PAUSED]
        FakeGh([NEW, OLD], jobs={"502": [job("d1-01-rust-test", None)]}).start(self)
        out = plan(rows, [mine(paused_by=None)])
        self.assertEqual(shape(out), [("train-resumed", "run", f"resumed:{NAME}:41"),
                                      ("train-run", "run", f"train-run:{NAME}:502")])
        self.assertEqual(out[0]["text"], f"train {NAME} resumed after smuggle 03")
        done = train_state.standing(rows + [line("resumed", at="2026-10-17T10:41:00Z", field="03")])
        self.assertEqual((done["state"], done["land_run"]), ("landing", None))
        self.assertEqual(shape(plan(rows + [line("resumed", at="2026-10-17T10:41:00Z", field="03")],
                                    [mine(paused_by=None)])), [("train-run", "run", f"train-run:{NAME}:502")])


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


class Smuggles(unittest.TestCase):
    """A barn with two smuggles on it: 03 changed a.txt (from b0), then 05 changed b.txt (from 03's)."""

    def setUp(self):
        self.main = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.main, True)
        git(self.main, "init", "-q", "-b", "main")
        git(self.main, "config", "user.email", "t@t")
        git(self.main, "config", "user.name", "t")
        git(self.main, "commit", "-q", "--allow-empty", "-m", "base")
        self.b0 = git(self.main, "rev-parse", "HEAD")
        for f in ("a.txt", "b.txt"):
            Path(self.main, f).write_text(f)
            git(self.main, "add", f)
            git(self.main, "commit", "-q", "-m", f)
        self.s1 = git(self.main, "rev-parse", "HEAD~1")
        git(self.main, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.tickets = [mine(covers=["03", "05"], gate_base=self.b0),
                        {"slot": "03", "seq": 41, "smuggle": {"phase": "unverified", "gate_base": self.b0}},
                        {"slot": "05", "seq": 44, "smuggle": {"phase": "unverified", "gate_base": self.s1}},
                        {"slot": "11", "seq": 45, "smuggle": {"phase": "checking", "gate_base": self.s1}}]
        self.top = str(Path(self.main) / "tollman-hal2")
        self.train = dict(train_state.standing([FORMED, STARTED, NOTED, PAUSED]), state="landing")
        p = mock.patch.object(triage.mtm_scan, "main_checkout", lambda top: self.main)
        p.start()
        self.addCleanup(p.stop)

    def test_the_smuggles_newest_first_with_their_files(self):
        self.assertEqual(smuggled.smuggles(self.main, self.tickets),
                         [{"slot": "05", "seq": 44, "files": ["b.txt"]}, {"slot": "03", "seq": 41, "files": ["a.txt"]}])
        covers = [mine(covers=["05"])] + self.tickets[1:]
        self.assertEqual(smuggled.smuggles(self.main, covers, carrier="tollman-hal2"),
                         [{"slot": "05", "seq": 44, "files": ["b.txt"]}], "the carrier's candidate covers 05 only")

    def test_a_resume_conflict_orders_the_smuggle_whose_files_conflict(self):
        FakeGh().start(self)
        result = {"status": "conflict", "files": ["a.txt"], "message": "a.txt conflicts"}
        out = trains.settle(self.top, self.train, result, {}, self.tickets)
        self.assertEqual([(a["kind"], a["do"]) for a in out], [("red", "run"), ("fix-order", "run")])
        order = out[1]
        self.assertEqual(order["argv"][2:5], ["order", "03", "--smuggle"])
        self.assertEqual(order["after"], out[0]["key"])
        why = order["argv"][order["argv"].index("--why") + 1]
        self.assertIn("conflicts with your smuggle in a.txt", why)
        self.assertIn("on `03-train-fix` merge `origin/main` into the carrier's head", why)
        none = trains.settle(self.top, self.train, dict(result, files=["c.txt"]), {}, self.tickets)
        self.assertEqual(none[1]["argv"][3], "05", "no smuggle's files conflict: the newest smuggle")
        alone = trains.settle(self.top, dict(self.train, pauses=[]), result, {})
        self.assertEqual(alone[1]["kind"], "train-failed", "no smuggle: the old wake")

    def test_a_smuggled_red_is_an_order_to_that_field_not_a_main_red_wake(self):
        url = "https://github.com/x/actions/runs/601"
        FakeGh([run(601, "land/tollman-hal2", "2026-10-17T10:50:00Z")],
               jobs={"601": [job("d1-01-rust-test")]},
               logs={"601": "test hub::tenant ... FAILED\nthread panicked at a.txt:3\n"}).start(self)
        out = trains.settle(self.top, self.train, {"status": "gate_failed", "run": url,
                                                   "red": [{"name": "d1-01-rust-test"}]}, {}, self.tickets)
        self.assertEqual([(a["kind"], a["do"]) for a in out], [("red", "run"), ("fix-order", "run")])
        self.assertEqual(out[1]["argv"][2:5], ["order", "03", "--smuggle"])
        self.assertIn("a.txt", out[1]["argv"][out[1]["argv"].index("--why") + 1])
        verdict = triage.classify({"id": "601"}, [job("d1-01-rust-test")], "panicked at nine.rs",
                                  {"smuggles": [{"slot": "03", "seq": 41, "files": ["a.txt"]}]})
        self.assertEqual(verdict["kind"], "car", "the red touches no smuggled file: D29 as before")


if __name__ == "__main__":
    unittest.main()
