"""Hal2 plan 0360 step 25 (D74 to D76): the merge queue's two modes. In smuggle mode the tollman sleeps: no train
formed, no land run started, no ci-check let through, one `asleep` line per round, no wake; a train already landing
is never cut (its run watched, its landing settled when it lands; a red one waits frozen, no fix order or wake until
production). Back in production, the first round drops the cars already in the barn (smuggled): a waiting hitch is
cleared, a car of a formed train leaves it, a car of a running train is recorded only; a `barn` line each, its foreman
told once. gh is gh_fake.py's, the queue engine_farm's Gate, git a temporary repository: no real gh, queue or session."""

import unittest

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import checks
import modes
import train_state
import trains
import wake
import tollman
from engine_farm import OWN, Farm, Gate
from gh_fake import FakeGh, job, run
from test_farmer import git

AT = "2026-10-17T10:00:00Z"
NAME = "07+09@" + AT
TOP, MAIN = "/no/such/farm/tollman-hal2", "/no/such/farm"
CARS = [{"field": "07", "branch": "07", "head": "7" * 40, "plan": "0360-tollman-and-skills"},
        {"field": "09", "branch": "09", "head": "9" * 40, "plan": ""}]
SMUGGLE = {"mode": "smuggle", "by": "user", "at": "2026-10-17T12:00:00Z", "why": "the runners are down"}
ASLEEP = "asleep: smuggle mode since 2026-10-17T12:00:00Z (by user)"
OURS = run(501, "land/tollman-hal2", "2026-10-17T10:06:00Z", status="in_progress")


def line(kind, at=AT, **kw):
    return {"schema": 1, "at": at, "kind": kind, "slot": "tollman-hal2", "train": NAME, **kw}


FORMED = line("formed", cars=CARS, base="b" * 40)
STARTED = line("started", at="2026-10-17T10:05:00Z", pid=4711)
HITCHED = {"slot": "11", "state": "waiting", "position": 1, "worktree": "/no/such/farm/11",
           "ready": {"head": "1" * 40, "at": AT}}


def kinds(actions):
    return [(a["kind"], a["do"]) for a in actions]


def plan(rows, tickets=(), alive=(4711,), result=None, mode=SMUGGLE):
    return trains.plan(TOP, MAIN, list(tickets), list(rows), {}, alive=lambda pid: pid in alive,
                       result=lambda main: result, mode=mode)


class Asleep(unittest.TestCase):
    def setUp(self):
        self.gh = FakeGh([OURS], jobs={"501": [job("d1-01-rust-test", "failure")]},
                         logs={"501": "test hub::tenant_rls ... FAILED"}).start(self)

    def test_smuggle_mode_forms_no_train_and_says_so_once_per_round(self):
        out = plan([], [HITCHED])
        self.assertEqual(kinds(out), [("asleep", "record")])
        self.assertEqual(out[0]["text"], ASLEEP)
        self.assertNotIn("key", out[0], "one line every round")
        self.assertEqual(kinds(plan([FORMED], alive=())), [("asleep", "record")], "a formed train is not started")
        red = line("red", status="gate_failed", why="d1-01-rust-test")
        self.assertEqual(kinds(plan([FORMED, STARTED, red])), [("asleep", "record")], "a red train: no retry")
        self.assertNotIn(("asleep", "record"), kinds(plan([], [HITCHED], mode=None)), "production: the draft")

    def test_a_running_train_is_never_cut_but_wakes_nobody_while_asleep(self):
        awake = plan([FORMED, STARTED], mode=None)
        self.assertEqual(kinds(awake), [("train-run", "run"), ("train-red", "wake")])
        asleep = plan([FORMED, STARTED])
        self.assertEqual(kinds(asleep), [("asleep", "record"), ("train-run", "run")], "watched, no wake, no fix order")

    def test_a_landing_that_ends_while_asleep_lands_or_waits_for_production(self):
        landed = plan([FORMED, STARTED], alive=(), result={"status": "landed", "commit": "c1", "run": OURS["url"]})
        self.assertEqual(kinds(landed)[:2], [("asleep", "record"), ("landed", "run")])
        self.assertIn(("in-the-barn", "send"), kinds(landed))
        red = plan([FORMED, STARTED], alive=(), result={"status": "gate_failed", "run": OURS["url"],
                                                         "red": [{"name": "d1-01-rust-test"}]})
        self.assertEqual(kinds(red), [("asleep", "record")], "no red line, no wake, no order: settled in production")
        again = plan([FORMED, STARTED], alive=(), result={"status": "interrupted"})
        self.assertEqual(kinds(again), [("asleep", "record")], "no land run started")

    def test_the_checks_duty_lets_no_check_through(self):
        def run_json(args, cwd=None):
            return {"queue": [], "mode": SMUGGLE} if args[:3] == ["hal2-cli-git", "worktree", "queue"] else []
        s = checks.state("/no/such/farm", run_json, sessions=set())
        self.assertEqual(s["busy"]["reason"], "smuggle mode since 2026-10-17T12:00:00Z (by user): the tollman sleeps")
        self.assertIsNone(checks.state("/no/such/farm", lambda a, cwd=None: {"queue": []} if a[0] != "gh" else [],
                                       sessions=set())["busy"])


class Woken(Farm):
    """The tollman's round on the test farm with the queue's mode (`self.mode`, None: no key, production)."""

    def setUp(self):
        super().setUp()
        self.mode = None
        self.gate.queue = lambda: {**Gate.queue(self.gate), **({"mode": self.mode} if self.mode else {})}

    def smuggled(self, field):
        """The field's crop smuggled into the barn: its head on origin's default branch."""
        git(self.fields[field], "push", "-q", "origin", "HEAD:main")

    def barn_lines(self):
        return [(e["slot"], e.get("how")) for e in train_state.lines(str(self.main)) if e["kind"] == "barn"]

    def test_smuggle_mode_round_forms_nothing_and_wakes_nobody(self):
        self.crop("07", {"seven.txt": "7"})
        self.mode = SMUGGLE
        self.round()
        self.assertEqual(self.last, [("seen-mode", "run", "-"), ("asleep", "record", "-")])
        self.assertEqual((self.spawned, self.train()), ([], None))
        self.assertEqual(wake.read(str(self.main), tollman.WIRING)["items"], [])
        self.round()
        self.assertEqual(self.last, [("asleep", "record", "-")], "one line per round, the mode noted once")
        self.assertEqual(modes.seen(str(self.main)), "smuggle")

    def test_back_in_production_a_smuggled_hitch_is_cleared_and_the_rest_forms(self):
        self.crop("07", {"seven.txt": "7"})
        self.crop("09", {"nine.txt": "9"})
        self.panes = {"09": "%9"}
        self.smuggled("09")
        self.mode = SMUGGLE
        self.round()
        self.mode = None
        self.round()
        self.assertEqual(self.last[:3], [("barn", "run", "09"), ("in-barn", "send", "09"), ("seen-mode", "run", "-")])
        self.assertEqual(self.barn_lines(), [("09", "hitch")])
        self.assertIsNone(self.gate.of("09"), "its hitch cleared")
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["07"], "the chain formed the rest")
        self.assertEqual([p for p, _ in self.typed], ["%9"])
        self.assertIn("already in the barn", self.typed[0][1])
        self.round()
        self.assertNotIn(("barn", "run", "09"), self.last, "told once")

    def test_a_car_of_a_formed_train_leaves_it(self):
        self.crop("07", {"seven.txt": "7"})
        self.crop("09", {"nine.txt": "9"})
        self.round()
        f = self.wm_state / train_state.FILE
        f.write_text("".join(x + "\n" for x in f.read_text().splitlines() if '"started"' not in x))  # its form died
        self.assertEqual(self.train()["state"], "formed")
        self.smuggled("09")
        self.mode = SMUGGLE
        self.round()
        self.assertEqual(self.spawned, [OWN], "asleep: the formed train is not started")
        self.mode = None
        self.round()
        self.assertEqual(self.barn_lines(), [("09", "formed")])
        train = self.train()
        self.assertEqual(([c["field"] for c in train["cars"]], train["in_barn"]), (["07"], ["09"]))
        self.assertEqual(self.gate.calls[-1], ["worktree", "queue", "train", OWN, "07"], "marked without 09")
        self.assertEqual(self.spawned, [OWN, OWN], "the rest landed again in the same round")

    def test_a_car_of_a_running_train_is_only_recorded(self):
        self.crop("07", {"seven.txt": "7"})
        self.crop("09", {"nine.txt": "9"})
        self.round()
        self.alive = {40001}
        self.smuggled("09")
        self.mode = SMUGGLE
        self.round()
        self.mode = None
        self.round()
        self.assertEqual(self.barn_lines(), [("09", "running")])
        train = self.train()
        self.assertEqual(([c["field"] for c in train["cars"]], train["in_barn"], train["state"]),
                         (["07", "09"], ["09"], "landing"), "nothing taken out of a running candidate")
        self.assertTrue(self.gate.of("09")["ready"], "its mark stays with the train")
        self.assertEqual(self.spawned, [OWN])


if __name__ == "__main__":
    unittest.main()
