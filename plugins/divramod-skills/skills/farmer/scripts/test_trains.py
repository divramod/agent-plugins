import datetime as dt
import subprocess
import tempfile
import unittest
from pathlib import Path

import tick
import trains
import trial

NOW = dt.datetime(2026, 10, 4, 10, 0)


def ticket(slot, pos, state="waiting", **kw):
    return {"slot": slot, "position": pos, "state": state, "branch": slot, "worktree": f"/x/{slot}", "seq": pos, **kw}


def info(**slots):
    """slot=commits ahead → slot_info's shape."""
    return {s: {"ahead": n, "current": ""} for s, n in slots.items()}


def logged(key, kind="train", hours_ago=1):
    return {"key": key, "kind": kind, "at": (NOW - dt.timedelta(hours=hours_ago)).isoformat(timespec="seconds")}


def clean(carrier, waiters):
    return waiters, {}


RESERVED = {"reason": "reserved"}


class Group(unittest.TestCase):
    def test_the_queue_of_2026_10_06_is_one_train_carried_by_the_holder(self):
        # hal2 plan 0169 step 11: 05 held the queue reserved (the user's priority, no candidate pushed); behind it
        # 34, 36, 31 and 32, whose branch had nothing to land.
        q = [ticket("05", 0, "held", holding=True, hold=RESERVED), ticket("34", 1), ticket("36", 2),
             ticket("31", 3), ticket("32", 4)]
        i = info(**{"05": 27, "34": 3, "36": 2, "31": 5, "32": 0})
        self.assertEqual(trains.group(q, i, {}, clean), (["05", "34", "36", "31"], {}))

    def test_a_running_landing_is_never_the_carrier(self):
        # Rule 1: a pushed candidate or a running land run is never touched; neither is a red one or a kept lease.
        for head in (ticket("05", 0, "active", holding=True),
                     ticket("05", 0, "held", holding=True, hold={"reason": "failed"}),
                     ticket("05", 0, "held", holding=True, hold=RESERVED, kept_until="2026-10-04T10:10:00Z"),
                     ticket("05", 0, "held", holding=True, hold=RESERVED, landing="l1")):
            q = [head, ticket("34", 1), ticket("36", 2), ticket("31", 3)]
            got = trains.group(q, info(**{"05": 9, "34": 3, "36": 2, "31": 5}), {}, clean)
            self.assertEqual(got, (["34", "36", "31"], {}), head)

    def test_no_maximum(self):
        q = [ticket(f"0{n}", n) for n in range(1, 8)]
        i = info(**{f"0{n}": 1 for n in range(1, 8)})
        self.assertEqual(trains.group(q, i, {}, clean)[0], [f"0{n}" for n in range(1, 8)])

    def test_a_waiter_the_trial_merge_refuses_is_left_out_and_named(self):
        q = [ticket("01", 1), ticket("02", 2), ticket("03", 3)]
        trial = lambda c, w: (["03"], {"02": ["src/a.rs"]})  # noqa: E731
        self.assertEqual(trains.group(q, info(**{"01": 1, "02": 1, "03": 1}), {}, trial),
                         (["01", "03"], {"02": ["src/a.rs"]}))
        out = trains.plan(q, info(**{"01": 1, "02": 1, "03": 1}), [], {}, NOW, trial=trial)
        self.assertIn("Left out, it conflicts: 02 (src/a.rs).", out[0]["text"])
        self.assertIn("left out: 02 (src/a.rs)", out[-1]["text"])

    def test_one_waiter_alone_is_no_train(self):
        self.assertEqual(trains.group([ticket("01", 1)], info(**{"01": 1}), {}, clean), ([], {}))
        q = [ticket("01", 1), ticket("02", 2)]
        self.assertEqual(trains.group(q, info(**{"01": 1, "02": 0}), {}, clean), ([], {}))

    def test_a_subservants_slot_is_neither_carrier_nor_passenger(self):
        # Review 1 finding 11: a slot with plans/LEAD (even a broken one) never lands, so it never rides.
        with tempfile.TemporaryDirectory() as d:
            q = [dict(ticket(s, n), worktree=str(Path(d) / s)) for n, s in enumerate(("31", "01", "32", "02"))]
            for s in ("31", "32"):
                (Path(d) / s / "plans").mkdir(parents=True)
            (Path(d) / "31/plans/LEAD").write_text("05 0013-parallel-plans 4\n")
            (Path(d) / "32/plans/LEAD").write_text("broken\n")
            got = trains.slot_info(d, q)
        self.assertEqual({s for s, i in got.items() if i.get("marked")}, {"31", "32"})
        i = {**info(**{"01": 1, "02": 1}), **{s: dict(got[s], ahead=3) for s in ("31", "32")}}  # even with commits
        self.assertEqual(trains.group(q, i, {}, clean)[0], ["01", "02"])

    def test_a_passenger_is_not_taken_again_and_a_carrier_takes_on_who_came_since(self):
        q = [ticket("01", 1), ticket("02", 2), ticket("03", 3)]
        i = info(**{s: 1 for s in ("01", "02", "03")})
        self.assertEqual(trains.group(q, i, {"01": "carrier", "02": "passenger"}, clean)[0], ["01", "03"])
        self.assertEqual(trains.group(q, i, {"01": "passenger"}, clean)[0], ["02", "03"])


class Trial(unittest.TestCase):
    def test_a_real_trial_merge(self):
        with tempfile.TemporaryDirectory() as d:
            def g(*a):
                return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=d, check=True,
                                      capture_output=True, text=True).stdout.strip()

            def branch(name, files):
                g("checkout", "-q", "-b", name, "main")
                for f, text in files.items():
                    (Path(d) / f).write_text(text)
                g("add", "-A")
                g("commit", "-q", "-m", name)

            g("init", "-q", "-b", "main")
            (Path(d) / "a.rs").write_text("a\n")
            (Path(d) / "INTENT.md").write_text("log\n")
            g("add", "-A")
            g("commit", "-q", "-m", "base")
            branch("05", {"a.rs": "carrier\n", "INTENT.md": "log\n05\n"})
            branch("34", {"b.rs": "b\n"})
            branch("36", {"a.rs": "other\n"})  # conflicts with the carrier in code
            branch("31", {"INTENT.md": "log\n31\n"})  # conflicts only in an append-only doc
            before = g("for-each-ref")
            got = trial.ride(d, "main", "05", [("34", "34"), ("36", "36"), ("31", "31")])
            self.assertEqual(got, (["34", "31"], {"36": ["a.rs"]}))
            self.assertEqual(g("for-each-ref"), before, "no ref moves")
            self.assertEqual(g("status", "--porcelain"), "")

    def test_soft_files(self):
        self.assertTrue(all(trial.soft(f) for f in ("INTENT.md", "code/rust/Cargo.lock",
                                                    "code/rust/libs/hal2-workspace-hack/Cargo.toml")))
        self.assertFalse(trial.soft("code/rust/libs/hal2-git/src/queue.rs"))


class Plan(unittest.TestCase):
    Q = [ticket("17", 1), ticket("21", 2), ticket("12", 3)]
    I = info(**{"17": 1, "21": 1, "12": 1})

    def test_carrier_and_passenger_texts(self):
        out = trains.plan(self.Q, self.I, [], {"17": "%1", "21": "%2"}, NOW)
        self.assertEqual([(a["kind"], a["do"], a["slot"]) for a in out],
                         [("carrier", "send", "17"), ("passenger", "send", "21"), ("passenger", "send", "12"),
                          ("train", "record", "17")])
        self.assertIn("Merge 21, 12 into your branch", out[0]["text"])
        self.assertEqual(out[0]["pane"], "%1")
        self.assertIn("rides in slot 17's landing; keep your ticket", out[1]["text"])
        self.assertEqual({a.get("after") for a in out[1:]}, {"train:17+21+12:17"})
        self.assertNotIn("CURRENT_PLAN", out[0]["text"], "no car names a plan")

    def test_the_carrier_writes_every_cars_current_plan_as_the_trains_name(self):
        i = {s: dict(v, current=c) for (s, v), c in zip(self.I.items(), ("0131-landings", "", "owner/3/a-shot"))}
        out = trains.plan(self.Q, i, [], {}, NOW)
        self.assertIn("write `0131-landings + owner/3/a-shot` as the first line of your plans/CURRENT_PLAN",
                      out[0]["text"])

    def test_a_train_under_way_is_not_planned_again(self):
        log = [logged("train:17+21+12")]
        self.assertEqual(trains.plan(self.Q, self.I, log, {}, NOW), [])

    def test_an_old_train_no_longer_counts(self):
        log = [logged("train:17+21+12", hours_ago=13)]
        self.assertEqual(len(trains.plan(self.Q, self.I, log, {}, NOW)), 4)

    def test_failed_carrier_wakes_the_farmer(self):
        q = [ticket("17", 0, "held", holding=True, hold={"reason": "failed", "message": "test-unit hal2-git"}),
             ticket("21", 2), ticket("12", 3)]
        out = trains.plan(q, self.I, [logged("train:17+21+12")], {}, NOW)
        self.assertEqual([(a["kind"], a["do"], a["slot"]) for a in out], [("train-failed", "wake", "17")])
        self.assertIn("test-unit hal2-git", out[0]["text"])
        self.assertEqual(out[0]["train"]["passengers"], ["21", "12"])

    def test_a_held_carrier_message_holds_the_whole_train(self):
        """The carrier waits for the user: tick.fresh drops its passengers' messages and the record too."""
        log = [{"kind": "ask", "slot": "17", "at": NOW.isoformat()}]
        planned = trains.plan(self.Q, self.I, log, {}, NOW)
        self.assertEqual(tick.fresh(planned, log, NOW), [])


class CurrentPlan(unittest.TestCase):
    def test_the_first_line(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(trains.current_plan(d), "")
            (Path(d) / "plans").mkdir()
            (Path(d) / "plans/CURRENT_PLAN").write_text("owner/3/some-shot\n")
            self.assertEqual(trains.current_plan(d), "owner/3/some-shot")


if __name__ == "__main__":
    unittest.main()
