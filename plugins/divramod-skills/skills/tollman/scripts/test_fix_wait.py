"""Hal2 plan 0490 step 21 (D22, D9): the next train's push waits until each red of the run before has its fix car or a
named reason; a timeout wakes the tollman and never pushes. fix_wait.fixes over data: the train's lines, the run's
row and its triage entry are fakes, the rounds' merges and joins are callables."""
# enforces .adr/deterministic-first.md and .adr/tollman.md

import contextlib
import datetime as dt
import io
import unittest
from unittest import mock

import fix_wait
import run_triage_wire

URL = "https://github.com/x/actions/runs/720"
NOW = dt.datetime(2026, 10, 30, 12, 0, tzinfo=dt.timezone.utc)


def red(key, kind="file", owner="20", files=("code/x/twenty.py",), job="d1-01-stack-test"):
    return {"key": key, "kind": kind, "job": job, "unit": f"{job}/{key}", "owner": owner, "run": URL,
            "at": "2026-10-30T11:00:00Z", "files": list(files), "prefixes": []}


class Wait(unittest.TestCase):
    def setUp(self):
        self.rows = [{"kind": "formed", "train": "A", "cars": [{"field": "20", "head": "a20"}]},
                     {"kind": "landed", "train": "A", "run": URL},
                     {"kind": "formed", "train": "B", "cars": [{"field": "03", "head": "h03"}]},
                     {"kind": "started", "train": "B", "pid": 1}]
        self.row = {"databaseId": 720, "status": "completed", "conclusion": "failure",
                    "createdAt": "2026-10-30T11:30:00Z"}
        self.entry = {"run": "720", "at": "2026-10-30T11:50:00Z", "reds": []}
        self.touched = {"h03": ["three.txt"]}
        self.naps, self.joins, self.reads, self.clock = [], 0, [], [0.0]
        for p in (mock.patch.object(fix_wait.train_state, "lines", lambda main: list(self.rows)),
                  mock.patch.object(fix_wait, "concluded", lambda main, rid: self.row),
                  mock.patch.object(fix_wait, "entry_of", self.entry_of),
                  mock.patch.object(fix_wait.wire, "update", lambda main, rid, change: change(self.entry))):
            p.start()
            self.addCleanup(p.stop)

    def entry_of(self, main, rid):
        self.reads.append(rid)
        return self.entry

    def read(self, main, wagon, since):
        return self.touched.get(wagon["head"], [])

    def sleep(self, seconds):
        self.naps.append(seconds)
        self.clock[0] += seconds
        self.on_sleep()

    def on_sleep(self):
        raise AssertionError("no round should sleep")

    def join(self):
        self.joins += 1
        return []

    def fixes(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return fix_wait.fixes("/m", "B", lambda: [], self.join, self.sleep, lambda: self.clock[0],
                                  lambda: NOW, self.read)

    def test_a_green_run_before_adds_no_wait_and_reads_no_triage(self):
        self.row["conclusion"] = "success"
        self.assertEqual((self.fixes(), self.reads, self.joins), ([], [], 0))

    def test_a_red_with_a_fix_car_rides_and_the_push_goes(self):
        self.entry["reds"] = [red("t1")]
        self.rows[2]["cars"].append({"field": "20", "head": "h20"})  # 20's fix, hitched and in the train
        self.touched["h20"] = ["code/x/twenty.py"]
        lines = self.fixes()
        self.assertEqual((self.naps, self.joins), ([], 0), "one pass, no join, no sleep")
        self.assertIn("every red of run 720 has its fix car or a named reason: the push goes", lines[-1])

    def test_a_fix_order_merged_into_the_train_covers_its_red(self):
        self.entry["reds"] = [red("t1", kind="car", files=())]
        self.rows += [{"kind": "order", "train": "B", "id": "20-fix-1", "field": "20", "run": URL, "post": "A"},
                      {"kind": "fixed", "train": "B", "id": "20-fix-1", "field": "20", "sha": "f"}]
        self.assertIn("the push goes", self.fixes()[-1])

    def test_a_red_with_a_runner_reason_does_not_hold(self):
        self.entry["reds"] = [red("t1", kind="runner", owner=None), red("t2", kind="needs-red", owner=None),
                              red("t3", kind="flake", owner=None)]
        self.assertIn("the push goes", self.fixes()[-1])
        self.assertEqual(self.naps, [])

    def test_a_red_without_a_fix_holds_the_push_until_its_car_joins(self):
        self.entry["reds"] = [red("t1"), red("t2", kind="runner")]

        def joined():
            if len(self.naps) == 2:  # 20's fix hitched: the open train's join round takes it
                self.rows.append({"kind": "joined", "train": "B", "cars": [{"field": "20", "head": "h20"}]})
                self.touched["h20"] = ["code/x/twenty.py", "other.txt"]

        self.on_sleep = joined
        lines = self.fixes()
        self.assertEqual((self.naps, self.joins), ([fix_wait.POLL] * 2, 2))
        self.assertIn("the push waits for the fix cars of run 720's reds: d1-01-stack-test/t1 (file, 20)", lines[0])
        self.assertIn("the push goes", lines[-1])
        self.assertEqual(len(lines), 2, "a line when the waiting reds change, not each poll")

    def test_an_unrelated_car_does_not_cover_a_red(self):
        self.entry["reds"] = [red("t1")]
        self.on_sleep = lambda: self.entry.setdefault("reasons", {}).update({"t1": "the user's word"}) \
            if len(self.naps) == 3 else None
        self.assertIn("the push goes", self.fixes()[-1])
        self.assertEqual(len(self.naps), 3, "03's three.txt fixes nothing: held until the reason")

    def test_an_unwritten_triage_holds_until_it_writes(self):
        self.entry = {"run": "720"}

        def writes():
            self.entry.update(at="2026-10-30T11:52:00Z", reds=[red("t1", kind="flake")])

        self.on_sleep = writes
        lines = self.fixes()
        self.assertIn("the push waits for the triage of run 720", lines[0])
        self.assertEqual((len(self.naps), lines[-1].endswith("the push goes")), (1, True))

    def test_the_timeout_wakes_the_tollman_and_never_pushes(self):
        self.entry["reds"] = [red("t1")]
        self.rows.insert(1, {"kind": "order", "train": "A", "id": "20-fix-1", "field": "20", "run": URL, "post": "A"})
        limit = (NOW - dt.datetime(2026, 10, 30, 11, 30, tzinfo=dt.timezone.utc)).total_seconds()  # its wall time
        rounds = int(limit // fix_wait.POLL) + 3
        pushed = []

        def later():
            pushed.append(self.entry.get("push"))
            if len(self.naps) == rounds:  # long after the wake: the session names the reason
                self.entry["reasons"] = {"*": "not ours: the pipeline field's"}

        self.on_sleep = later
        lines = self.fixes()
        woke = [i for i, p in enumerate(pushed) if p]
        self.assertEqual(woke[0], int(limit // fix_wait.POLL), "woken at the run before's wall time")
        self.assertTrue(lines[-1].endswith("the push goes"), "only after the reason, never at the timeout")
        self.assertEqual(sum("the tollman is woken" in x for x in lines), 1, "one wake")
        action = self.entry["push"]["action"]
        self.assertEqual((action["do"], action["key"]), ("wake", "push-waits:720:B"))
        self.assertIn("fix order 20-fix-1", action["text"])
        self.assertIn("fix_wait.py reason --repo <field> --run 720", action["text"])
        with mock.patch.object(run_triage_wire, "state", lambda main: {"runs": [self.entry]}):
            offered = run_triage_wire.pending("/m", NOW)
        self.assertIn(action, offered, "the next pass wakes the session (tick.fresh: once)")

    def test_a_set_timeout_overrides_the_wall_time(self):
        self.entry["reds"] = [red("t1")]
        self.on_sleep = lambda: self.entry.setdefault("reasons", {}).update({"*": "x"}) if self.entry.get("push") \
            else None
        with mock.patch.object(fix_wait, "TIMEOUT", fix_wait.POLL * 2):
            self.fixes()
        self.assertEqual(len(self.naps), 3)


class Compact(unittest.TestCase):
    def test_the_triage_keeps_each_red_as_the_wait_reads_it(self):
        v = {"key": "triage:720:d1-01-stack-test/hub-e2e:ocr.spec.ts", "kind": "file", "owner": "05", "cause": "file",
             "evidence": {"job": "d1-01-stack-test", "unit": "d1-01-stack-test/hub-e2e", "run": URL,
                          "file": "code/typescript/e2e/ocr.spec.ts", "lines": ["at code/a/b.ts:3"]}}
        pipe = {"key": "k2", "kind": "pipeline", "owner": "27", "cause": "pipeline",
                "evidence": {"job": "d1-02-build", "unit": "d1-02-build", "run": URL, "lines": []}}
        a, b = fix_wait.compact([v, pipe], "2026-10-30T11:00:00Z")
        self.assertEqual((a["files"], a["owner"], a["at"], a["prefixes"]),
                         (["code/a/b.ts", "code/typescript/e2e/ocr.spec.ts"], "05", "2026-10-30T11:00:00Z", []))
        self.assertEqual(b["prefixes"], [".github/workflows/", "code/bash/scripts/gate/"])

    def test_the_run_before_is_the_train_landed_before_this_one_formed(self):
        rows = [{"kind": "landed", "train": "Z", "run": "u1"}, {"kind": "formed", "train": "A"},
                {"kind": "landed", "train": "A", "run": "u2"}, {"kind": "formed", "train": "B"}]
        self.assertEqual((fix_wait.run_before(rows, "A"), fix_wait.run_before(rows, "B"),
                          fix_wait.run_before(rows, "C")), ("u1", "u2", None))


if __name__ == "__main__":
    unittest.main()
