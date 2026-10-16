"""Hal2 plan 0294 step 6: what the duty `trains` plans. `draft` (steps 1 to 4) runs over one temporary git
repository whose branches are the fields' crops; the state machine (`plan`, `settle`) over data. Nothing is done
here: no queue, no landing, no session (test_engine.py runs whole rounds)."""

import functools
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import chain
import proof
import tick
import train_state
import trains
import trial

AT = "2026-10-13T10:00:00Z"


def ticket(field, pos, head, worktree, **kw):
    return {"slot": field, "position": pos, "state": "waiting", "branch": field, "worktree": str(worktree),
            "seq": pos + 1, "pid": 0, "ready": {"at": AT, "head": head, "by": f"hal2/{field}"}, "train": None,
            "rides_with": None, **kw}


class Crops(unittest.TestCase):
    """One repository: `main` is the barn, every other branch a field's crop (its head is what the field hitched)."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        green = mock.patch.object(trains, "PROVE", lambda *a: {"state": "green", "lines": []})  # Proof: the real one
        green.start()
        self.addCleanup(green.stop)
        self.g("init", "-q", "-b", "main")
        self.write("main", {"a.rs": "a\n", "INTENT.md": "log\n", ".github/workflows/merge-to-main.yml": "on: push\n"}, new=False)

    def g(self, *a):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=self.d, check=True,
                              capture_output=True, text=True).stdout.strip()

    def write(self, name, files, new=True):
        if new:
            self.g("checkout", "-q", "-b", name, "main")
        for f, text in files.items():
            (Path(self.d) / f).parent.mkdir(parents=True, exist_ok=True)
            (Path(self.d) / f).write_text(text)
        self.g("add", "-A")
        self.g("commit", "-q", "-m", name)
        return self.g("rev-parse", "HEAD")

    def queue(self, **crops):
        """field={file: text} in queue order -> the ready tickets."""
        return [ticket(f, n, self.write(f, files), self.d) for n, (f, files) in enumerate(crops.items())]

    def draft(self, tickets, own="wagon-master-hal2"):
        return trains.draft(self.d, tickets, own, "main", "main")

    def cars(self, d):
        return [c["field"] for c in d["cars"]]


class Trial(Crops):
    def test_a_real_trial_merge_moves_no_ref_and_names_the_files_that_conflict(self):
        q = self.queue(**{"05": {"a.rs": "five\n", "INTENT.md": "log\n05\n"}, "07": {"b.rs": "b\n"},
                          "09": {"a.rs": "other\n"}, "11": {"INTENT.md": "log\n11\n"}})
        five, b, a, intent = (t["ready"]["head"] for t in q)
        before = self.g("for-each-ref")
        commit, files = trial.merge(self.d, five, b)
        self.assertEqual((self.g("rev-list", "--parents", "-n", "1", commit).split()[1:], files), ([five, b], []))
        self.assertEqual(trial.merge(self.d, commit, a)[1], ["a.rs"])
        self.assertEqual(trial.merge(self.d, commit, intent)[1], ["INTENT.md"],
                         "an append-only file conflicts too: nothing resolves it for a foreman")
        self.assertEqual(trial.merge(self.d, "main", "0" * 40), (None, []), "git cannot say")
        self.assertEqual(self.g("for-each-ref"), before, "no ref moves")
        self.assertEqual(self.g("status", "--porcelain"), "")
        d = self.draft(q)
        self.assertEqual((self.cars(d), [u["field"] for u in d["unhitched"]]), (["05", "07"], ["09", "11"]))


class Draft(Crops):
    def test_two_ready_wagons_are_one_train_in_queue_order(self):
        q = self.queue(**{"07": {"seven.rs": "7\n"}, "09": {"nine.rs": "9\n"}})
        (Path(self.d) / "plans").mkdir()
        (Path(self.d) / "plans/CURRENT_PLAN").write_text("0294-wagon-master-role\n")
        d = self.draft(list(reversed(q)))
        self.assertEqual(d["cars"], [
            {"field": f, "branch": f, "head": t["ready"]["head"], "plan": "0294-wagon-master-role"}
            for f, t in zip(("07", "09"), q)])
        self.assertEqual((d["unhitched"], d["waiting"], d["alone"], d["base"]), ([], [], False, "main"))

    def test_no_ready_ticket_is_no_train_and_no_maximum(self):
        waiter = dict(ticket("03", 0, "x", self.d), ready=None)
        self.assertEqual(self.draft([waiter])["cars"], [])
        q = self.queue(**{f"0{n}": {f"f{n}.rs": "x\n"} for n in range(1, 9)})
        self.assertEqual(self.cars(self.draft(q)), [f"0{n}" for n in range(1, 9)])

    def test_what_cannot_ride_is_unhitched_at_once(self):
        q = self.queue(**{"31": {"servant.rs": "s\n"}, "07": {"seven.rs": "7\n"}, "05": {"gone.rs": "g\n"}})
        q[2]["worktree"] = str(Path(self.d) / "no-such-field")
        landed = ticket("04", 3, self.g("rev-parse", "main"), self.d)
        own = ticket("wagon-master-hal2", 4, q[1]["ready"]["head"], self.d)
        other = ticket("06", 5, q[1]["ready"]["head"], self.d, rides_with="08")
        d = self.draft([*q, landed, own, other])
        self.assertEqual(self.cars(d), ["07"], "the own field and a car of another carrier are not ours")
        self.assertEqual([(u["field"], u["tell"], u["why"]) for u in d["unhitched"]],
                         [("31", "servant", "a servant's field (30-99) never rides"),
                          ("05", None, "its worktree is gone"), ("04", None, "its head is in the barn already")])
        self.assertTrue(trains.servant("30") and trains.servant("99"))
        self.assertFalse(trains.servant("29") or trains.servant("farmer-hal2") or trains.servant("100"))

    def test_a_wagon_that_conflicts_is_unhitched_with_its_files_and_the_rest_rides(self):
        q = self.queue(**{"07": {"a.rs": "seven\n"}, "09": {"a.rs": "nine\n"}, "11": {"c.rs": "c\n"}})
        d = self.draft(q)
        self.assertEqual(self.cars(d), ["07", "11"])
        (u,) = d["unhitched"]
        self.assertEqual((u["field"], u["files"], u["ahead"], u["tell"]), ("09", ["a.rs"], ["07"], "conflict"))
        self.assertEqual(u["why"], "conflicts with the cars ahead in a.rs")

    def test_a_conflict_with_the_barn_is_named_so(self):
        q = self.queue(**{"07": {"seven.rs": "7\n"}, "09": {"a.rs": "nine\n"}})
        self.g("checkout", "-q", "main")
        self.write("main", {"a.rs": "the barn moved\n"}, new=False)
        (u,) = self.draft(q)["unhitched"]
        self.assertEqual((u["field"], u["ahead"], u["why"]), ("09", [], "conflicts with the barn in a.rs"))

    def test_the_alone_rule(self):
        # D11: the landing workflow, a gate job list, the runner setup.
        for path in (".github/workflows/merge-to-main.yml", ".github/hal2-runners.toml", "code/bash/scripts/gate/main.sh"):
            self.assertTrue(trains.ALONE.match(path), path)
        for path in (".github/dependabot.yml", ".github/hal2-x/y.toml", "code/bash/scripts/gatekeeper/x.sh", "a.rs"):
            self.assertFalse(trains.ALONE.match(path), path)
        q = self.queue(**{"07": {".github/workflows/merge-to-main.yml": "on: pull_request\n"}, "09": {"nine.rs": "9\n"},
                          "11": {"eleven.rs": "11\n"}})
        first = self.draft(q)
        self.assertEqual((self.cars(first), first["alone"]), (["07"], True))
        self.assertEqual(first["waiting"], [{"field": "09", "why": "rides in the next train, after the gate train"},
                                            {"field": "11", "why": "rides in the next train, after the gate train"}])
        later = self.draft([dict(q[1], position=0), dict(q[0], position=1), q[2]])
        self.assertEqual((self.cars(later), later["alone"], later["unhitched"]), (["09", "11"], False, []))
        self.assertEqual(later["waiting"],
                         [{"field": "07", "why": "rides in the next train, a gate train (.github/workflows/merge-to-main.yml)"}])

    def test_alone_cars_ride_as_one_gate_train(self):
        # Hal2 plan 0333 step 3 (D3), 2026-10-14: the gate cars 09, 05, 08, 14 and 21 rode as five trains of one.
        gate = {"09": ".github/workflows/nine.yml", "05": "code/bash/scripts/gate/five.sh",
                "08": ".github/hal2-caches.toml", "14": ".github/workflows/fourteen.yml",
                "21": "code/bash/scripts/gate/twentyone.sh"}
        crops = {f: {path: f + "\n"} for f, path in gate.items()}
        q = self.queue(**{"09": crops["09"], "05": crops["05"], "17": {"seventeen.rs": "17\n"}, "08": crops["08"],
                          "14": crops["14"], "21": crops["21"]})
        d = self.draft(q)
        self.assertEqual((self.cars(d), d["alone"], d["unhitched"]), (["09", "05", "08", "14", "21"], True, []))
        self.assertEqual(d["waiting"], [{"field": "17", "why": "rides in the next train, after the gate train"}])
        normal = [dict(t, position=n) for n, t in enumerate([q[2], *q[:2], *q[3:]])]
        later = self.draft(normal)
        self.assertEqual((self.cars(later), later["alone"], later["unhitched"]), (["17"], False, []))
        self.assertEqual(later["waiting"], [{"field": f, "why": f"rides in the next train, a gate train ({path})"}
                                            for f, path in gate.items()])
        acts = trains.train_actions("/f", d, {})
        self.assertEqual(acts[-1]["text"], "wagon train: 09, 05, 08, 14, 21 (gate train)")

    def test_what_the_field_holds_beyond_the_barn_is_under_the_cars(self):
        role = self.write("wm", {"roles/wagon-master/ROLE.md": "mine\n"})
        self.assertEqual(trains.base_of(self.d, "main", self.g("rev-parse", "main")), "main")
        self.assertEqual(trains.base_of(self.d, "main", None), "main")
        base = trains.base_of(self.d, "main", role)
        self.assertEqual(self.g("rev-list", "--parents", "-n", "1", base).split()[1:],
                         [self.g("rev-parse", "main"), role])


class Proof(Crops):
    """Hal2 plan 0333 step 4 (cause A): no car rides without its light gate checks green on its hitched head."""

    PLAN = "0255-plugin-tmux-2-move-tmux-plugin-here"

    def setUp(self):
        super().setUp()
        cache = Path(tempfile.mkdtemp()) / "cache" / "proof"
        self.addCleanup(shutil.rmtree, cache.parents[1], True)
        real = mock.patch.object(trains, "PROVE", functools.partial(proof.verdict, cache=cache))
        real.start()
        self.addCleanup(real.stop)
        names = Path(__file__).resolve().parents[7] / "code/python/scripts/names-inventory"
        files = {f"{proof.NAMES.rsplit('/', 1)[0]}/{p.name}": p.read_text() for p in names.glob("*.py")
                 if not p.name.startswith("test_")}
        files[f"plans/{self.PLAN}/plan.md"] = "---\nstatus: open\n---\n# Plan 0255\n"  # an open plan is no history
        self.g("checkout", "-q", "main")
        self.write("main", files, new=False)  # the barn's names check, as the field has it

    def test_06s_car_with_an_old_word_in_a_prose_line_is_unhitched_with_the_finding(self):
        # 2026-10-14 08:17: 06's car at d192125ca rode with "the slot's pane" in plan 0255's uat.md, and train
        # 38534070998 was red in python-lint's names check; one car's line cost the whole train's run.
        uat = f"plans/{self.PLAN}/uat.md"
        (q,) = self.queue(**{"06": {uat: "# UATs\n\nExpected: 1 shows the slot's pane (or a window in session "
                                         "`hosts`), no popup.\n"}})
        d = self.draft([q])
        self.assertEqual(self.cars(d), [], "the car does not ride")
        (u,) = d["unhitched"]
        self.assertEqual((u["field"], u["tell"]), ("06", "proof"))
        self.assertEqual(u["lines"], [f"names: {uat}:3: slot — use worktree"])
        (unhitch, told) = trains.train_actions("/f", d, {"06": "%6"})
        self.assertEqual((unhitch["kind"], told["kind"], told["pane"]), ("unhitch", "unhitched", "%6"))
        self.assertIn(f"{uat}:3: slot — use worktree", told["text"])
        self.assertTrue(told["text"].endswith("Fix it, push and report it ready again (`hal2-cli-git worktree "
                                              "queue ready`)."), told["text"])

    def test_a_clean_car_rides_and_one_not_at_its_hitched_head_waits(self):
        q = self.queue(**{"07": {"plans/0301-x/notes.md": "the worktree's pane\n"}, "09": {"nine.rs": "9\n"}})
        d = self.draft(q)  # the checkout is at 09's head: 07's field moved on
        self.assertEqual((self.cars(d), d["unhitched"]), (["09"], []))
        self.assertEqual(d["waiting"][0]["field"], "07")
        self.assertTrue(d["waiting"][0]["why"].startswith("no proof yet: the field is at "), d["waiting"])


TRAIN = {"train": "07+09@" + AT, "carrier": "wagon-master-hal2", "base": "b" * 40, "state": "landing", "starts": 1,
         "pid": 4711, "unhitched": [],
         "cars": [{"field": "07", "branch": "07", "head": "7" * 40, "plan": "0294-wagon-master-role"},
                  {"field": "09", "branch": "09", "head": "9" * 40, "plan": ""}]}


def shape(actions):
    return [(a["kind"], a["do"], a["slot"]) for a in actions]


class Settle(unittest.TestCase):
    def test_landed_tells_every_car_s_foreman_in_the_barn(self):
        out = trains.settle("/f", TRAIN, {"status": "landed", "commit": "c1", "run": "https://x/runs/9"}, {"07": "%7"})
        self.assertEqual(shape(out), [("landed", "run", "-"), ("in-the-barn", "send", "07"), ("in-the-barn", "send", "09"),
                                      ("chain", "run", "-")])
        go = out[-1]  # plan 0333 step 6: the same round goes on to the next train
        self.assertEqual((go["argv"][1:], go["after"], go["key"], go["on_fail"][0]["kind"]),
                         ([str(chain.CLI), "chain", "--in-tick", "--repo", "/f"], out[0]["key"],
                          "chain:" + out[0]["key"], "train-stuck"))
        self.assertEqual(out[0]["argv"][1:], [str(trains.ENGINE), "landed", "--run", "https://x/runs/9", "--commit",
                                              "c1", "--repo", "/f"])
        self.assertEqual((out[1]["pane"], out[2]["pane"]), ("%7", None))
        self.assertTrue(out[1]["text"].startswith("wagon-master (wagon train): your crop is in the barn (the train of "
                                                  "07, 09, https://x/runs/9). Restock (/mfm)"), out[1]["text"])
        self.assertEqual({a["after"] for a in out[1:]}, {out[0]["key"]})
        for result in ({"status": "nothing"}, {"status": "shipping", "commit": "c1"}):
            self.assertEqual(shape(trains.settle("/f", TRAIN, result, {}))[0], ("landed", "run", "-"), result)

    def test_red_is_one_wake_with_the_run_s_address_and_the_cars(self):
        result = {"status": "gate_failed", "run": "https://x/runs/9", "message": "the gate is red",
                  "red": [{"name": "linux / rust-test"}, {"name": "mac / swift"}]}
        out = trains.settle("/f", TRAIN, result, {})
        self.assertEqual(shape(out), [("red", "run", "-"), ("train-failed", "wake", "-")])
        self.assertEqual(out[0]["argv"][2:], ["red", "--status", "gate_failed", "--run", "https://x/runs/9", "--why",
                                              "linux / rust-test, mac / swift", "--repo", "/f"])
        for part in ("did not land (gate_failed): linux / rust-test, mac / swift", "Run: https://x/runs/9.",
                     "Cars: 07 (0294-wagon-master-role), 09 (09).", "wagon_master.py unhitch <field> --why",
                     "wagon_master.py retry --why"):
            self.assertIn(part, out[1]["text"])
        self.assertEqual(out[1]["after"], out[0]["key"])
        other = trains.settle("/f", TRAIN, {"status": "conflict", "message": "a.rs conflicts"}, {})
        self.assertEqual((shape(other), other[0]["argv"][2:6]),
                         ([("red", "run", "-"), ("train-failed", "wake", "-")], ["red", "--status", "conflict", "--why"]))

    def test_interrupted_starts_the_same_landing_again_a_few_times(self):
        for result in (None, {"status": "interrupted", "message": "its parent is gone"}, {"status": "testing"}):
            out = trains.settle("/f", TRAIN, result, {})
            self.assertEqual((shape(out), out[0]["argv"][2:]), ([("restart", "run", "-")], ["restart", "--repo", "/f"]))
        stuck = trains.settle("/f", dict(TRAIN, starts=trains.MAX_STARTS), None, {})
        self.assertEqual(shape(stuck), [("red", "run", "-"), ("train-failed", "wake", "-")])
        self.assertIn(f"its landing ended without a result {trains.MAX_STARTS} times", stuck[1]["text"])


class Plan(unittest.TestCase):
    """The state machine over data: the field `/f/wagon-master-hal2` does not exist, so nothing is drafted."""

    TOP = "/no/such/farm/wagon-master-hal2"
    FORMED = {"schema": 1, "at": AT, "kind": "formed", "slot": "wagon-master-hal2", "train": TRAIN["train"],
              "cars": TRAIN["cars"], "base": TRAIN["base"]}
    STARTED = {"schema": 1, "at": AT, "kind": "started", "slot": "wagon-master-hal2", "train": TRAIN["train"],
               "pid": 4711}

    def plan(self, rows, tickets=(), alive=(), result=None):
        return trains.plan(self.TOP, "/no/such/farm", list(tickets), rows, {}, alive=lambda pid: pid in alive,
                           result=lambda main: result)

    def line(self, kind, **kw):
        return {"schema": 1, "at": AT, "kind": kind, "slot": "wagon-master-hal2", "train": TRAIN["train"], **kw}

    def test_a_running_landing_is_never_touched(self):
        self.assertEqual(self.plan([self.FORMED, self.STARTED], alive={4711}), [])
        mine = {"slot": "wagon-master-hal2", "position": 0, "pid": 99, "state": "active"}
        self.assertEqual(self.plan([], [mine], alive={99}), [], "a landing of the field that is no train of ours")

    def test_a_red_train_waits_for_the_session_s_word(self):
        red = self.line("red", status="gate_failed")
        self.assertEqual(self.plan([self.FORMED, self.STARTED, red]), [])
        again = self.plan([self.FORMED, self.STARTED, red, self.line("retry", why="flaky")])
        self.assertEqual((shape(again), again[0]["argv"][2]), ([("restart", "run", "-")], "restart"))
        split = self.plan([self.FORMED, self.STARTED, red,
                           dict(self.line("unhitched", why="its test fails"), slot="09")])
        self.assertEqual(shape(split), [("breakup", "run", "-"), ("unhitched", "send", "09")])
        self.assertEqual(split[0]["argv"][2:5], ["breakup", "--why", "split after red"])
        self.assertIn("field 09 is unhitched from the red train: its test fails.", split[1]["text"])

    def test_a_train_never_started_and_a_leftover_mark_are_broken_up(self):
        never = self.plan([self.FORMED])
        self.assertEqual((shape(never), never[0]["argv"][4]), ([("breakup", "run", "-")], "its landing never started"))
        mark = {"carrier": "wagon-master-hal2", "cars": [{"field": "05"}], "at": AT}
        mine = {"slot": "wagon-master-hal2", "position": 0, "pid": 0, "state": "waiting", "train": mark}
        left = self.plan([], [mine])
        self.assertEqual((shape(left), left[0]["argv"][4], left[0]["key"]),
                         ([("breakup", "run", "-")], "a mark without a train of ours", f"leftover:{AT}"))
        stale = self.plan([self.FORMED, self.STARTED], [mine])
        self.assertEqual(stale[0]["argv"][4], "the queue's mark names other cars")
        ours = dict(mine, train=dict(mark, cars=[{"field": "07"}, {"field": "09"}]))
        self.assertEqual(shape(self.plan([self.FORMED, self.STARTED], [ours], result={"status": "landed"}))[0],
                         ("landed", "run", "-"))

    def test_every_action_carries_a_key_and_a_failed_change_wakes_the_session(self):
        rows = [self.FORMED, self.STARTED]
        planned = (self.plan(rows, result={"status": "landed"}) + self.plan(rows, result={"status": "gate_failed"})
                   + self.plan(rows) + self.plan([self.FORMED]))
        self.assertEqual([a for a in planned if not a.get("key")], [], "D22: tick.fresh drops keyless actions")
        for a in (a for a in planned if a["do"] == "run"):
            (stuck,) = a["on_fail"]
            self.assertEqual((stuck["kind"], stuck["do"], stuck["slot"], stuck["key"]),
                             ("train-stuck", "wake", "-", "stuck:" + a["key"]))
            self.assertIn(a["argv"][:2], ([trains.sys.executable, str(trains.ENGINE)],
                                          [trains.sys.executable, str(chain.CLI)]), "an engine verb, or the chain")
        log = [{"at": "2026-10-13T12:00:00", "key": a["key"]} for a in planned]
        now = tick.dt.datetime(2026, 10, 13, 12, 5)
        self.assertEqual(tick.fresh(planned, log, now, "wagon-master"), [], "a second round does nothing again")
        self.assertEqual(len(tick.fresh(planned, [], now, "wagon-master")), len(planned),
                         "and no action names the wagon master's own field: none is held back")


class Chain(unittest.TestCase):
    """Hal2 plan 0333 step 6 (cause C): one call goes on link after link until a wait, at most MAX_LINKS."""

    @staticmethod
    def ran(kind, code=0, do="run", slot="-"):
        return {"kind": kind, "do": do, "slot": slot, "exit": code}

    def test_a_link_goes_on_only_after_landed_or_breakup_that_started_no_landing(self):
        ran = self.ran
        self.assertIsNone(chain.stop([ran("landed"), ran("in-the-barn", None, "send", "07")]))
        self.assertIsNone(chain.stop([ran("breakup", tick.OFFLINE)]), "offline is no failure")
        self.assertEqual(chain.stop([]), "nothing to do")
        self.assertEqual(chain.stop([ran("breakup"), ran("unhitched", None, "send", "09"), ran("form")]),
                         "a landing started")
        self.assertEqual(chain.stop([ran("restart")]), "a landing started")
        self.assertEqual(chain.stop([ran("breakup", 1), ran("form")]), "failed: breakup")
        self.assertEqual(chain.stop([ran("unhitch"), ran("unhitched", None, "send", "31")]), "a wait")
        self.assertEqual(chain.stop([ran("red"), ran("train-failed", None, "wake")]), "a wait")

    def test_the_chain_is_bounded_and_every_link_is_logged(self):
        logged, links = [], iter([[self.ran("landed")], [self.ran("breakup")], [self.ran("landed")]])
        with mock.patch.object(chain, "link", lambda *a: next(links)), \
                mock.patch.object(chain.tick, "execute", lambda a, *rest: logged.append((a["kind"], a["do"], a["text"]))), \
                mock.patch.object(chain.mtm_scan, "main_checkout", return_value="/m"):
            r = chain.go("/f", None, None)
        self.assertEqual((len(r["links"]), r["why"], r["items"]), (3, "3 links: the next round goes on", 0))
        self.assertEqual(logged, [("chain", "record", "chain link 1: landed -"), ("chain", "record", "chain link 2: breakup -"),
                                  ("chain", "record", "chain link 3: landed -")])
        self.assertEqual(chain.report(r)[1].splitlines()[-1], "chain stops: 3 links: the next round goes on")


class State(unittest.TestCase):
    def test_the_fold(self):
        formed, started = Plan.FORMED, Plan.STARTED
        self.assertIsNone(train_state.standing([]))
        self.assertEqual(train_state.standing([formed])["state"], "formed")
        t = train_state.standing([formed, started, started])
        self.assertEqual((t["state"], t["starts"], t["pid"], t["base"]), ("landing", 2, 4711, "b" * 40))
        red = dict(started, kind="red", status="gate_failed", run="u")
        self.assertEqual(train_state.standing([formed, started, red])["state"], "red")
        other = dict(started, kind="landed", train="another@x")
        self.assertEqual(train_state.standing([formed, started, red, other])["state"], "red", "another train's line")
        plain = {"kind": "unhitched", "slot": "09", "why": "conflict"}  # no car of the train: a ready ticket's
        self.assertEqual(train_state.standing([formed, started, red, plain])["unhitched"], [])
        for end in ("landed", "cleared"):
            self.assertIsNone(train_state.standing([formed, started, dict(started, kind=end)]))

    def test_a_pid_another_process_got_is_not_the_landing(self):
        sleeper = [trains.sys.executable, "-c", "import time; time.sleep(60)"]
        ours = subprocess.Popen([*sleeper, "engine.py land"])  # as `ps` shows the train's detached process
        other = subprocess.Popen(sleeper)
        try:
            self.assertTrue(train_state.alive(ours.pid))
            self.assertFalse(train_state.alive(other.pid), "alive, but not a landing: a reused pid")
        finally:
            for p in (ours, other):
                p.kill()
                p.wait()
        self.assertFalse(train_state.alive(ours.pid) or train_state.alive(None))

    def test_utc_with_z_and_whole_seconds(self):
        naive = tick.dt.datetime(2026, 10, 13, 12, 0, 5, 999)
        self.assertRegex(train_state.utc(naive), r"^2026-10-1[234]T\d\d:\d\d:05Z$")
        aware = tick.dt.datetime(2026, 10, 13, 12, 0, 5, tzinfo=tick.dt.timezone(tick.dt.timedelta(hours=2)))
        self.assertEqual(train_state.utc(aware), "2026-10-13T10:00:05Z")
        self.assertEqual(json.loads(json.dumps(train_state.KINDS)),
                         ["formed", "yard", "regenerated", "pretest", "started", "red", "retry", "unhitched", "landed",
                          "cleared"])


if __name__ == "__main__":
    unittest.main()
