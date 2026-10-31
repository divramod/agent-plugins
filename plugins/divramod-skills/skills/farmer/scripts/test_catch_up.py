"""The catch-up of 2026-10-31 replayed (hal2 plan 0530 step 5, D6): after 12 h of crashed rounds the first good round
re-sent 5 asks days old (one "URGENT, against the user's hold", long void) and woke 18 old `restore` items. Copied from
the live log (testdata/catch-up: the 5 `ask-ack` lines, texts cut, and the round's 18 `restore` lines): now each ask
is closed void once and never re-sent, each item older than a day is one `stale-skip` record and never woken; a fresh
ask still gets its one re-send and a fresh item still wakes. Also step 4's follow-up: the tick's board syncs outside
the round count in tick-health.json."""

import contextlib
import datetime as dt
import io
import json
import os
import time
import unittest
from pathlib import Path
from unittest import mock

import acks
import board
import duties
import farmer
import field_pause
import mtm_scan
import role_cli
import roles
import roletime
import tick
import tick_health
import test_tick_health
from test_farmer import ROLE, Repo

FIXTURE = Path(__file__).resolve().parent / "testdata" / "catch-up"
NOW_LOCAL = dt.datetime(2026, 10, 31, 10, 4, 27)  # the catch-up round, Berlin time (TZ pinned below)
NOW = dt.datetime(2026, 10, 31, 9, 4, 27, tzinfo=dt.timezone.utc)  # the same instant
VOIDED = ["wagon-master-hal2-4", "wagon-master-6", "tollman-25", "tollman-26", "tollman-32"]
WATCH_ROLE = ROLE.replace('  lead: "*/15 * * * *"', '  lead: "*/15 * * * *"\n  watch: "*/15 * * * *"')


def rows(name: str) -> list[dict]:
    return [json.loads(x) for x in (FIXTURE / name).read_text().splitlines()]


def incidents() -> list[dict]:
    """The 18 `restore` wakes of the round as sanity-watch's F8 incidents (its id and `at` are in the key)."""
    out = []
    for e in rows("restore.jsonl"):
        ident = e["key"].removeprefix("watch:")
        out.append({"id": ident, "class": "F8", "name": "process gone", "session": ident.split(":")[1],
                    "at": ident.split(":", 2)[2], "slot": e["slot"], "pane": None, "action": "restore",
                    "reason": "", "evidence": {}})
    return out


def logged(actions: list[dict], at: str) -> list[dict]:
    """The log lines `tick.execute` writes for the acts."""
    return [{"at": at, "kind": a["kind"], "slot": a["slot"], "what": a.get("text", ""), "note": "", "by": "tick",
             "duty": a["duty"], "do": a["do"], "key": a.get("key", "")} for a in actions]


def ask(ident: str, at: str, slot: str = "07", role: str = "farmer") -> dict:
    text = acks.stamp(f"{role}: do x", ident, role)
    return acks.ask_entry(slot, ident, text, None, "tick") | {"at": at}


@unittest.skipUnless(hasattr(time, "tzset"), "needs time.tzset to pin the farmer's local zone")
class Berlin(unittest.TestCase):
    def setUp(self):
        old = os.environ.get("TZ")
        os.environ["TZ"] = "Europe/Berlin"
        time.tzset()
        self.addCleanup(self.restore_tz, old)

    @staticmethod
    def restore_tz(old):
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()


class Asks(Berlin):
    def test_the_five_stale_asks_are_closed_void_never_re_sent(self):
        log = rows("asks.jsonl")
        for now in (NOW, NOW_LOCAL):
            planned = tick.fresh(acks.plan(log, now, {"tollman": "%9"}, capture=lambda p: ""), log, now)
            self.assertEqual([(a["do"], a["kind"], a["key"]) for a in planned],
                             [("record", "ack-void", f"ack-void:{i}") for i in VOIDED])
        texts = {a["key"][9:]: a["text"] for a in planned}
        self.assertEqual(texts["tollman-32"], "tollman-32 closed void: no ack 25 h after it was sent "
                                              "(2026-10-30T07:30:26Z), never re-sent")  # 08:30 local, CET
        self.assertIn("no ack 349 h", texts["wagon-master-6"])  # 14 days

    def test_a_void_ask_is_logged_once_and_counts_as_closed(self):
        log = rows("asks.jsonl")
        log += logged(acks.plan(log, NOW, {}), roletime.stamp(NOW))
        self.assertEqual(acks.plan(log, NOW + dt.timedelta(minutes=5), {}), [])
        self.assertEqual({i: x["void"] is not None for i, x in acks.instructions(log).items()},
                         dict.fromkeys(VOIDED, True))

    def test_a_fresh_ask_gets_its_one_re_send_then_its_wake(self):
        log = [ask("07-1", "2026-10-31T08:04:27")]  # 2 h old
        planned = acks.plan(log, NOW, {"07": "%7"})
        self.assertEqual([(a["do"], a["kind"], a.get("pane")) for a in tick.fresh(planned, log, NOW)],
                         [("send", "resend", "%7")])
        log += logged(planned, "2026-10-31T09:50:00")  # re-sent 14 min before
        woke = tick.fresh(acks.plan(log, NOW, {}, capture=lambda p: ""), log, NOW)
        self.assertEqual([(a["do"], a["kind"]) for a in woke], [("wake", "no-ack")])
        log += logged(woke, roletime.stamp(NOW))
        self.assertEqual(tick.fresh(acks.plan(log, NOW, {}, capture=lambda p: ""), log, NOW), [])

    def test_an_ask_re_sent_long_ago_is_void_never_woken(self):
        log = [ask("07-2", "2026-10-29T08:00:00"), {"at": "2026-10-29T08:15:00", "kind": "resend", "slot": "07",
                                                    "key": "ack-resend:07-2"}]
        self.assertEqual([a["kind"] for a in acks.plan(log, NOW, {})], ["ack-void"])

    def test_a_started_or_done_ask_is_never_void(self):
        for status in ("started", "done"):
            log = [ask("07-3", "2026-10-28T08:00:00"),
                   {"at": "2026-10-28T09:00:00", "kind": "ack", "id": "07-3", "what": status, "slot": "07"}]
            self.assertEqual(acks.plan(log, NOW, {}), [])

    def test_a_day_old_refusal_is_history_a_fresh_one_wakes(self):
        # L74 of the tollman (acks.stale, from main): nothing about it newer than 24 h, so no wake and no record.
        old = [ask("07-4", "2026-10-28T08:00:00"),
               {"at": "2026-10-29T08:00:00", "kind": "ack", "id": "07-4", "what": "refused", "slot": "07"}]
        self.assertEqual(tick.fresh(acks.plan(old, NOW, {}), old, NOW), [])
        later = NOW + dt.timedelta(days=30)
        self.assertEqual(tick.fresh(acks.plan(old, later, {}), old, later), [])
        fresh = [ask("07-5", "2026-10-31T08:00:00"),
                 {"at": "2026-10-31T09:30:00", "kind": "ack", "id": "07-5", "what": "refused", "slot": "07"}]
        self.assertEqual([a["do"] for a in tick.fresh(acks.plan(fresh, NOW, {}), fresh, NOW)], ["wake"])

    def test_the_tollman_s_asks_take_the_same_path(self):
        # The tollman sends through the frame (tick.execute stamps, acks.plan follows up, tick.fresh gates): no re-send
        # of its own (orders, leavers, prune_ask send through `send` acts).
        log = [ask("12-7", "2026-10-29T13:00:00", "12", "tollman"), ask("12-8", "2026-10-31T08:30:00", "12", "tollman")]
        self.assertTrue(log[0]["text"].startswith("tollman [12-7]: "))
        planned = tick.fresh(acks.plan(log, NOW, {"12": "%12"}), log, NOW, "tollman")
        self.assertEqual([(a["do"], a["kind"]) for a in planned], [("record", "ack-void"), ("send", "resend")])


class Wakes(Berlin):
    def ctx(self, **kw):
        return {"top": "/x/farmer", "main": "/x/hal2", "now": NOW, "log": [], "duties": {"watch"}, "panes": {},
                "agents_by_pane": {}, "landing": set(), **kw}

    def test_the_eighteen_restore_items_wake_only_the_one_of_this_morning(self):
        found = incidents()
        self.assertEqual(len(found), 18)
        planned = tick.fresh(duties.plan_watch({}, self.ctx(), found), [], NOW)
        self.assertEqual(sum(a["kind"] == "stale-skip" for a in planned), 17)
        woken = [a for a in planned if a["do"] in tick.TALKS]
        # 2026-10-31T06:03:15Z: 3 h before the round, inside its day: a real restore item
        self.assertEqual([(a["kind"], a["key"]) for a in woken],
                         [("restore", "watch:F8:tmvvzvz30xtam:2026-10-31T06:03:15Z")])
        self.assertTrue(all(a["key"].startswith("watch:F8:") and a["do"] == "record" for a in planned
                            if a["kind"] == "stale-skip"))

    def test_a_stale_item_is_logged_once_never_re_planned(self):
        planned = tick.fresh(duties.plan_watch({}, self.ctx(), incidents()), [], NOW)
        log = logged(planned, roletime.stamp(NOW))
        for later in (NOW + dt.timedelta(minutes=15), NOW + dt.timedelta(days=60)):
            again = tick.fresh(duties.plan_watch({}, self.ctx(), incidents()), log, later)
            self.assertEqual(again, [], later)

    def test_a_wake_already_logged_is_no_stale_skip_line(self):
        # The 18 keys the bad round logged at 10:04: the next rounds add nothing for them.
        log = rows("restore.jsonl")
        self.assertEqual(tick.fresh(duties.plan_watch({}, self.ctx(), incidents()), log, NOW + dt.timedelta(hours=1)),
                         [])

    def test_a_stale_resume_drops_its_handled_record_too(self):
        epoch_ms = int((NOW - dt.timedelta(days=2)).timestamp() * 1000)  # sanity-watch's chronicle time
        i = {"id": "F1:s1:1", "class": "F1", "name": "n", "session": "s1", "slot": "04", "pane": "%4", "at": epoch_ms,
             "action": "resume", "reason": "", "evidence": {"api_error": {"text": "Connection lost"}}}
        planned = tick.fresh(duties.plan_watch({}, self.ctx(), [i]), [], NOW)
        self.assertEqual([(a["do"], a["kind"]) for a in planned], [("record", "stale-skip")])
        fresh = {**i, "at": int((NOW - dt.timedelta(minutes=5)).timestamp() * 1000)}
        planned = tick.fresh(duties.plan_watch({}, self.ctx(), [fresh]), [], NOW)
        self.assertEqual([(a["do"], a["kind"]) for a in planned], [("send", "resume"), ("run", "handled")])

    def test_the_window_of_the_act_bounds_its_item_and_an_act_without_born_is_never_stale(self):
        acts = [tick.act("x", "a", "wake", "07", key="k1", born="2026-10-31T08:00:00Z", window=1800),
                tick.act("x", "b", "wake", "07", key="k2", born="2026-10-31T08:50:00Z", window=1800),
                tick.act("x", "c", "wake", "07", key="k3"),
                tick.act("x", "d", "run", "07", key="k4", born="2026-10-01T08:00:00Z", argv=["true"])]
        self.assertEqual([(a["kind"], a["do"]) for a in tick.stale(acts, NOW)],
                         [("stale-skip", "record"), ("b", "wake"), ("c", "wake"), ("d", "run")])
        self.assertEqual([tick.item_time(v) for v in (None, True, "junk", 1793437467000, 1793437467)],
                         [None, None, None] + [dt.datetime(2026, 10, 31, 9, 4, 27, tzinfo=dt.timezone.utc)] * 2)

    def test_a_paused_field_s_stale_item_is_one_stale_skip_never_a_daily_paused_skip(self):
        pause = {"by": "farmer", "why": "the user's hold"}
        acts = duties.plan_watch({}, self.ctx(), [i for i in incidents() if i["slot"] == "20"])
        out = field_pause.skip(tick.stale(acts, NOW), {"20": pause})
        self.assertEqual({a["kind"] for a in out}, {"stale-skip"})


class Round(Berlin, Repo):
    """tick.run (dry) over a farmer worktree whose log holds the 5 asks and whose watch finds the 18 items."""

    def setUp(self):
        Berlin.setUp(self)
        Repo.setUp(self)
        (self.slot / tick.ROLE).write_text(WATCH_ROLE)
        state = self.data / "hal2"
        state.mkdir(parents=True)
        (state / "log.jsonl").write_text((FIXTURE / "asks.jsonl").read_text())
        self.handlers = {"duty:watch": lambda item, ctx: duties.plan_watch(item, ctx, incidents()),
                         "duty:lead": lambda item, ctx: [], "task:probe": lambda item, ctx: []}
        call = mock.patch.object(tick.delegation, "call", return_value=(1, ""))
        call.start()
        self.addCleanup(call.stop)

    def test_the_dry_catch_up_round_sends_nothing_old_and_wakes_one(self):
        for now in (NOW, NOW_LOCAL):
            r = tick.run(str(self.slot), True, self.handlers, now, all_due=True)
            self.assertFalse(r.get("problem"), r.get("problem"))
            planned = r["planned"]
            self.assertEqual(sorted(a["key"] for a in planned if a["kind"] == "ack-void"),
                             sorted(f"ack-void:{i}" for i in VOIDED))
            self.assertEqual(sum(a["kind"] == "stale-skip" for a in planned), 17)
            self.assertFalse([a for a in planned if a["do"] in ("send", "relay")])
            self.assertEqual([(i["kind"], i.get("key")) for i in r["wake_items"]],
                             [("restore", "watch:F8:tmvvzvz30xtam:2026-10-31T06:03:15Z")])
            self.assertNotIn("URGENT", json.dumps(r["planned"] + r["wake_items"]))

    def test_acks_open_lists_no_void_ask(self):
        log = self.data / "hal2" / "log.jsonl"
        with log.open("a") as f:
            for line in logged(acks.plan(mtm_scan.entries(log), NOW, {}), roletime.stamp(NOW)):
                f.write(json.dumps(line) + "\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            acks.main(["open", "--repo", str(self.main), "--json"])
        self.assertEqual(json.loads(out.getvalue()), [])

    def test_the_board_shows_a_void_ask_closed(self):
        log = self.data / "hal2" / "log.jsonl"
        with log.open("a") as f:
            for line in logged(acks.plan(mtm_scan.entries(log), NOW, {}), roletime.stamp(NOW)):
                f.write(json.dumps(line) + "\n")
        board.sync(str(self.main), roles.ROLE)
        lines = board.lines(str(self.main), role=roles.ROLE)
        self.assertEqual(sorted(x["id"] for x in lines if x["kind"] == "message"), sorted(VOIDED))
        done = [x for x in lines if x["kind"] == "ack"]
        self.assertEqual(sorted((x["id"], x["status"]) for x in done), sorted((i, "done") for i in VOIDED))
        self.assertTrue(all(x["text"].startswith("void: ") and x["from"] == "farmer-hal2" for x in done))
        board.sync(str(self.main), roles.ROLE)
        self.assertEqual(len(board.lines(str(self.main), role=roles.ROLE)), len(lines), "each once")


class SyncHealth(unittest.TestCase):
    """Step 4's follow-up: the tick's board sync before and after its round runs outside role_cli.run_tick's catch; a
    failure there counts in tick-health.json like a failed round, once per tick."""
    wiring = roles.FARMER
    state = test_tick_health.Rounds.state
    health = test_tick_health.Rounds.health
    latest = test_tick_health.Rounds.latest

    def setUp(self):
        test_tick_health.Rounds.setUp(self)
        quiet = mock.patch.object(role_cli, "quiet", return_value=False)
        quiet.start()
        self.addCleanup(quiet.stop)

    def tick_(self, sync_fails: bool, round_fails: bool = False) -> int:
        effect = TypeError("round") if round_fails else None
        with mock.patch.object(board, "sync", side_effect=OSError("board.jsonl: read-only") if sync_fails else None,
                               return_value=[]), \
                mock.patch.object(tick, "run", side_effect=effect, return_value=test_tick_health.GOOD), \
                contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            return farmer.run_tick(str(self.repo), False, True)

    def test_a_failing_sync_counts_once_per_tick_and_notifies_at_the_second(self):
        self.assertEqual(self.tick_(sync_fails=True), 0)
        self.assertEqual((self.health()["failures"], self.sent), (1, []))
        self.assertEqual(self.health()["error"], "BoardFailed: board messages and acks: board.jsonl: read-only")
        self.tick_(sync_fails=True)
        self.assertEqual((self.health()["failures"], len(self.sent)), (2, 1))
        self.assertIn("farmer tick failing: BoardFailed: board messages and acks", self.sent[0][1])
        self.tick_(sync_fails=False)
        self.assertEqual(self.health()["failures"], 0)
        self.assertIn("farmer tick recovered after 2 failed rounds", self.latest())

    def test_a_failed_round_and_a_failed_sync_are_one_failure(self):
        self.assertEqual(self.tick_(sync_fails=True, round_fails=True), 5)
        self.assertEqual(self.health()["failures"], 1)
        self.assertEqual(self.health()["error"], "TypeError: round")

    def test_a_sync_failing_only_after_the_round_counts(self):
        state = {"n": 0}

        def sync(main, role="tollman"):
            state["n"] += 1
            if state["n"] % 2 == 0:
                raise OSError("after")
            return []
        with mock.patch.object(board, "sync", side_effect=sync), \
                mock.patch.object(tick, "run", return_value=test_tick_health.GOOD), \
                contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            farmer.run_tick(str(self.repo), False, True)
        self.assertEqual((self.health()["failures"], self.health()["error"]),
                         (1, "BoardFailed: board messages and acks: after"))

    def test_a_dry_tick_never_syncs_or_counts(self):
        with mock.patch.object(board, "sync", side_effect=AssertionError("synced")), \
                mock.patch.object(tick, "run", return_value=test_tick_health.GOOD | {"dry": True}), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(farmer.run_tick(str(self.repo), True, True), 0)
        self.assertFalse((self.state / tick_health.FILE).exists())

    def test_a_failed_pass_outside_the_round_is_counted(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            for _ in range(2):
                try:
                    raise KeyError("minute")
                except KeyError as exc:
                    self.assertEqual(role_cli.failed_pass(str(self.repo), self.wiring, exc), 5)
        self.assertIn("Traceback", err.getvalue())
        self.assertEqual((self.health()["failures"], len(self.sent)), (2, 1))


if __name__ == "__main__":
    unittest.main()
