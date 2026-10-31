"""The 2026-10-30 night replayed (hal2 plan 0530): the farmer's tick died 12 h on "can't compare offset-naive and
offset-aware datetimes" because log.jsonl and delegations.jsonl mixed naive local `at` values with `+02:00`,
`+00:00` and `Z` ones. A slice of the live files (testdata/mixed-times, copied, texts shortened) plus hand-made lines
of every shape go through the round's readers; nothing raises, and a naive line is read as LOCAL time (the farmer,
2026-10-31: every naive `at` in the live files is Europe/Berlin, never UTC)."""

import datetime as dt
import json
import os
import time
import unittest
from pathlib import Path
from unittest import mock

import acks
import delegation
import due
import logstate
import mtm_scan
import roletime
import tick
import wake
from test_farmer import Repo

FIXTURE = Path(__file__).resolve().parent / "testdata" / "mixed-times"
UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 31, 9, 30, tzinfo=UTC)  # the morning after: 10:30 in Berlin (CET)
NOW_LOCAL = dt.datetime(2026, 10, 31, 10, 30)  # the same instant as a naive local `now` (TZ Europe/Berlin)

# The shapes of the incident: naive local, `+02:00`, `+00:00`, `Z`; one key in several shapes.
LOG = [
    {"at": "2026-10-31T09:52:24", "kind": "relay", "slot": "07", "what": "naive local", "key": "mixed:one",
     "by": "tick", "do": "relay"},
    {"at": "2026-10-18T17:03:48+02:00", "kind": "relay", "slot": "07", "what": "summer offset", "key": "mixed:one",
     "by": "tick", "do": "relay"},
    {"at": "2026-10-30T17:54:08+00:00", "kind": "relay", "slot": "08", "what": "utc offset", "key": "mixed:old",
     "by": "tick", "do": "relay"},
    {"at": "2026-10-30T17:54:08+00:00", "kind": "ask-ack", "slot": "07", "what": "farmer [07-901]: x",
     "id": "07-901", "text": "farmer [07-901]: x", "pane": "", "by": "tick"},
    {"at": "2026-10-31T08:52:24Z", "kind": "ack", "slot": "07", "what": "started", "id": "07-901", "by": "farmer"},
    {"at": "2026-10-31T08:00:00Z", "kind": "pause", "slot": "12", "what": "paused", "key": "pause:land-9:12"},
    {"at": "2026-10-31T09:10:00", "kind": "pause", "slot": "13", "what": "paused", "key": "pause:land-9:13"},
    {"at": "2026-10-31T08:20:00+00:00", "kind": "go", "slot": "13", "what": "go", "key": "go:land-9:13"},
    {"at": "not a time", "kind": "relay", "slot": "07", "what": "garbage stamp", "key": "mixed:one"},
]
LEDGER = [
    {"at": "2026-10-18T17:03:48+02:00", "key": "mixed:a", "state": "running", "slot": "12", "title": "plus two",
     "brief": "/x/a.md"},
    {"at": "2026-10-30T17:54:08+00:00", "key": "mixed:b", "state": "running", "slot": "13", "title": "plus zero",
     "brief": "/x/b.md"},
    {"at": "2026-10-31T09:52:24", "key": "mixed:c", "state": "running", "slot": "14", "title": "naive",
     "brief": "/x/c.md"},
    {"at": "2026-10-31T08:52:24Z", "key": "mixed:d", "state": "running", "slot": "15", "title": "zulu",
     "brief": "/x/d.md"},
]
RUNS = [{"at": "2026-10-31T10:15:00", "name": "duty:lead"}, {"at": "2026-10-31T08:50:00Z", "name": "task:probe"},
        {"at": "2026-10-30T23:00:00+00:00", "name": "duty:lead"}]


def lines(rows):
    return "".join(json.dumps(r) + "\n" for r in rows)


@unittest.skipUnless(hasattr(time, "tzset"), "needs time.tzset to pin the farmer's local zone")
class MixedTimes(Repo):
    """The farmer's state folder holds the live slice plus the incident's lines; TZ is Europe/Berlin."""

    def setUp(self):
        super().setUp()
        old = os.environ.get("TZ")
        os.environ["TZ"] = "Europe/Berlin"
        time.tzset()
        self.addCleanup(self.restore_tz, old)
        self.state = self.data / "hal2"
        self.state.mkdir(parents=True)
        (self.state / "log.jsonl").write_text((FIXTURE / "log.jsonl").read_text() + lines(LOG))
        (self.state / "delegations.jsonl").write_text((FIXTURE / "delegations.jsonl").read_text() + lines(LEDGER))
        (self.state / "runs.jsonl").write_text(lines(RUNS))
        call = mock.patch.object(delegation, "call", return_value=(1, ""))  # no CLI: no transplants, no free field
        self.call = call.start()
        self.addCleanup(call.stop)

    @staticmethod
    def restore_tz(old):
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()

    def log_entries(self):
        return mtm_scan.entries(self.state / "log.jsonl")

    def test_a_naive_local_line_and_a_z_line_of_the_same_instant_are_equal(self):
        self.assertEqual(roletime.parse("2026-10-31T09:52:24"), roletime.parse("2026-10-31T08:52:24Z"))
        self.assertEqual(roletime.parse("2026-10-18T17:03:48"), roletime.parse("2026-10-18T17:03:48+02:00"))
        self.assertEqual(roletime.aware(NOW_LOCAL), NOW)

    def test_the_log_keeps_every_readable_line_whatever_its_shape(self):
        read = self.log_entries()
        written = (self.state / "log.jsonl").read_text().splitlines()
        self.assertEqual(len(read), len(written) - 1)  # only the garbage stamp is skipped
        order = [e["what"] for e in sorted(read, key=lambda e: roletime.parse(e["at"])) if e.get("key") == "mixed:one"]
        self.assertEqual(order, ["summer offset", "naive local"])  # parsed, never compared as strings

    def test_fresh_drops_a_key_logged_in_any_shape_within_its_window(self):
        log = self.log_entries()
        for now in (NOW, NOW_LOCAL):
            kept = tick.fresh([tick.act("lead", "x", "record", "07", key="mixed:one", window=3600),
                               tick.act("lead", "y", "record", "08", key="mixed:old", window=3600)], log, now)
            self.assertEqual([a["key"] for a in kept], ["mixed:old"], now)

    def test_a_dry_round_runs_through_the_mixed_files(self):
        handlers = {"duty:lead": lambda item, ctx: [tick.act("lead", "x", "record", "07", key="mixed:one",
                                                             window=3600, text="x")]}
        for now in (NOW, NOW_LOCAL, None):
            with mock.patch.object(tick, "sh", wraps=tick.sh):
                r = tick.run(str(self.slot), True, handlers, now)
            self.assertFalse(r.get("problem"), r.get("problem"))
            self.assertIn("delegations", r)
            if now is not None:
                self.assertNotIn("mixed:one", [a.get("key") for a in r["planned"]])

    def test_the_follow_up_reads_the_mixed_ledger_dry(self):
        mine = {"mixed:a", "mixed:b", "mixed:c", "mixed:d"}
        for now in (NOW, NOW_LOCAL):
            done = delegation.follow_up(str(self.main), {}, 2, True, now)
            # older than SETTLE (30 min) and nothing in the field: landed; c (09:52 local) and d (08:52Z) 38 min old
            self.assertEqual({d["key"] for d in done if d.get("state") == "landed"} & mine, mine)
        early = delegation.follow_up(str(self.main), {}, 2, True, NOW - dt.timedelta(minutes=20))
        # 18 min old, not settled: had the naive 09:52 been read as UTC it would lie in the future either way
        self.assertEqual({d["key"] for d in early if d.get("state") == "landed"} & mine, {"mixed:a", "mixed:b"})
        self.assertFalse(any(c.args[0][:len(delegation.STOP)] == delegation.STOP for c in self.call.call_args_list))

    def test_acks_pauses_and_runs_read_every_shape(self):
        log = self.log_entries()
        for now in (NOW, NOW_LOCAL):
            planned = acks.plan(log, now, {}, capture=lambda pane: "")
            self.assertNotIn("07-901", [a.get("ack_id") for a in planned])  # acked `started`: no re-send
            self.assertEqual(logstate.paused(log, now) & {"12", "13"}, {"12"})  # 13: its go came after
        last = due.last_runs(str(self.slot))
        self.assertEqual(last["duty:lead"], roletime.parse("2026-10-30T23:00:00Z"))
        self.assertEqual(last["task:probe"], roletime.parse("2026-10-31T08:50:00Z"))
        self.assertTrue(due.is_due("*/15 * * * *", last["task:probe"], NOW))
        self.assertFalse(due.is_due("0 * * * *", roletime.parse("2026-10-31T09:00:00Z"), NOW_LOCAL))

    def test_the_wake_file_with_mixed_stamps(self):
        wake.wake_file(str(self.main)).write_text(json.dumps({
            "woken_at": "2026-10-31T10:10:00", "handoff": {"at": "2026-10-31T09:20:00+00:00", "session": "s"},
            "items": [{"seq": 1, "at": "2026-10-31T09:00:00", "duty": "lead", "kind": "x", "slot": "07"},
                      {"seq": 2, "at": "2026-10-31T08:30:00Z", "duty": "lead", "kind": "x", "slot": "07"},
                      {"seq": 3, "at": "bad", "duty": "lead", "kind": "x", "slot": "07"}]}))
        closed = wake.close_older(str(self.main), roletime.parse("2026-10-31T08:15:00Z").timestamp())
        self.assertEqual([i["seq"] for i in closed], [1])  # 09:00 local = 08:00Z; a bad stamp stays
        result = wake.hand_over(str(self.slot), str(self.main), {"wake": [tick.act("lead", "y", "wake", "08")]},
                                NOW_LOCAL, agents=[])
        self.assertEqual(result["pending"], 3)
        self.assertTrue(wake.read(str(self.main))["items"][-1]["at"].endswith("Z"))


if __name__ == "__main__":
    unittest.main()
