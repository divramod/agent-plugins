"""Hal2 plan 0383 step 6 (D6, L33, L34): on a green merge job the next train is formed and pretested at once, while
the run before still runs its jobs after the merge; its land run starts only after that run has finished. A red
after the merge is ordered to its car's foreman and rides the next train, never holding it; no wagon leaves a formed
train. Whole passes and rounds on engine_farm.py's farm (a bare origin, no landing), gh is gh_fake.py's."""
# enforces .adr/deterministic-first.md, .adr/merge-queue-policy.md and .adr/tollman.md

import os
import contextlib
import io
import types
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import acks
import engine
import mtm_scan
import next_train
import post_merge
import run_triage_wire
import stack_red
import tick
import train_state
import tollman
from engine_farm import Farm, out
from gh_fake import FakeGh, job, run
from test_farmer import git

os.environ.setdefault("HAL2_WORKQUEUE_FREEZE", "0")  # no test takes a real workqueue hold (plan 0466)

ROLE = """---
duties:
  trains: "*/15 * * * *"
  watch: "* * * * *"
notify: every-round
---

# the tollman
"""
RED = "d1-01-stack-test\ttest\t2026-10-19T04:10:00.1Z error: assertion failed at code/x/twenty.py:3"
MERGE = job("d2-01-git-merge", "success")


class Trains(Farm):
    """Train 20+02 lands in run 720; 03 hitches while it lands."""

    def setUp(self):
        super().setUp()
        self.commit(self.wm, tollman.WIRING.role_file, ROLE)  # the field's own role file: the watch too
        self.crop("20", {"code/x/twenty.py": "20"}, plan="0380-twenty")
        self.crop("02", {"two.txt": "2"}, plan="0381-two")
        self.panes, self.refs, fake = {"20": "%20", "02": "%2"}, [], engine.spawn

        def spawn(top, log, ref):  # the landing's process lives on: its pretest, then its wait (next_train.py)
            pid = fake(top, log, ref)
            self.alive.add(pid)
            self.refs.append(ref)
            return pid

        p = mock.patch.object(engine, "spawn", spawn)
        p.start()
        self.addCleanup(p.stop)
        self.round()
        self.a = self.train()
        self.assertEqual((self.a["state"], len(self.spawned)), ("landing", 1))
        self.run = run(720, "land/" + self.a["land_ref"], "2099-01-01T00:00:00Z", status="in_progress")
        self.url = self.run["url"]
        queue = mtm_scan.run_json  # the gate's queue (engine_farm.py), before the fake gh takes the reader
        self.gh = FakeGh([self.run], jobs={"720": [job("d1-01-rust-test", "success"), job("d2-01-git-merge", None)]},
                         logs={"720": RED}).start(self)
        gh = self.gh.run_json
        p = mock.patch.object(mtm_scan, "run_json", lambda args, cwd=None: gh(args, cwd) if args[:1] == ["gh"]
                              else queue(args, cwd))
        p.start()
        self.addCleanup(p.stop)

    def minute(self):
        """A tick on which only the watch is due: a pass."""
        with mock.patch.object(tick.due, "is_due", lambda cron, last, now: cron == "* * * * *"):
            code, text = self.call("tick")
        self.assertEqual(code, 0, text)
        return text

    def merged(self):
        """The merge job green while the run runs on; the landing's process ends soon after (hal2-git ends a
        landing at its merge's green): the barn has the candidate, the mark and the cars' tickets are gone."""
        self.gh.jobs["720"] = [job("d1-01-rust-test", "success"), MERGE]
        self.assertIn("merge job green: d2-01-git-merge", self.minute())
        head = out(self.cw, "rev-parse", "HEAD")
        self.ends({"status": "landed", "commit": head, "run": self.url})
        git(self.cw, "push", "-q", "origin", "HEAD:main")
        self.gate.tickets = [t for t in self.gate.tickets if t["slot"] not in ("20", "02", self.carrier())]  # mark, cars

    def fix(self):
        """20's foreman, as the order says: the side branch from the carrier's remote head, one commit, pushed."""
        path = self.fields["20"]
        git(path, "fetch", "-q", "origin", self.carrier())
        git(path, "switch", "-q", "-C", "20-train-fix", f"origin/{self.carrier()}")
        (path / "code/x/twenty.py").write_text("20, fixed")
        git(path, "commit", "-qam", "fix 20")
        git(path, "push", "-q", "origin", "20-train-fix")
        return out(path, "rev-parse", "HEAD")


class MergeGreen(Trains):
    def test_merge_job_green_while_the_run_runs_forms_and_pretests_the_next_train_once(self):
        self.crop("03", {"three.txt": "3"}, plan="0382-three")
        self.panes["03"] = "%3"
        self.gh.jobs["720"] = [job("d1-01-rust-test", "success"), MERGE]
        self.assertEqual(self.minute(), f"merge job green: d2-01-git-merge ({self.url})\n",
                         "the landing's process still runs: never stopped, the next minute looks again")
        self.assertEqual((self.train()["train"], len(self.spawned)), (self.a["train"], 1))
        self.ends({"status": "landed", "commit": out(self.cw, "rev-parse", "HEAD"), "run": self.url})
        git(self.cw, "push", "-q", "origin", "HEAD:main")
        self.gate.tickets = [t for t in self.gate.tickets if t["slot"] not in ("20", "02", self.carrier())]  # mark, cars
        self.assertEqual(self.minute(), f"train {self.a['train']}: merge job green: the next train forms on the new "
                                        "main\n")
        self.assertEqual(self.gh.runs[0]["status"], "in_progress", "the run before still runs its post-merge jobs")
        b = self.train()
        self.assertEqual(([c["field"] for c in b["cars"]], b["state"], len(self.spawned)), (["03"], "landing", 2),
                         "formed on the new main, its landing's process started: the pretest first")
        self.assertEqual((self.refs[-1], b["land_ref"]), (None, "train-2-1"), "numbered: no --land-ref (plan 0398)")
        kinds = [k for k, _ in self.state()]
        self.assertEqual(kinds[kinds.index("landed"):], ["landed", "formed", "started"])
        self.assertEqual(out(self.cw, "rev-parse", "HEAD~1"), out(self.main, "rev-parse", "origin/main"))
        self.assertEqual(self.minute(), "", "once: the next minute is quiet")
        self.assertEqual(len(self.spawned), 2)

    def test_the_next_train_s_land_run_starts_only_after_the_run_before_has_finished(self):
        self.crop("03", {"three.txt": "3"}, plan="0382-three")
        self.merged()
        self.minute()
        naps = []

        def sleep(seconds):
            naps.append(seconds)
            self.gh.runs[0] = dict(self.run, status="completed", conclusion="success")

        with contextlib.redirect_stdout(io.StringIO()):
            lines = next_train.before_push(str(self.cw), sleep=sleep)
        self.assertEqual((naps, lines), ([next_train.POLL], [
            "next train: its land run waits for run 720 to finish (one land run at a time)"]))
        self.assertEqual(next_train.before_push(str(self.cw), sleep=sleep), [], "nothing runs: no wait")

    def test_the_landing_s_process_pretests_then_waits_then_lands(self):
        calls = []
        with (mock.patch.object(engine.pretest_train, "before_landing", lambda top: calls.append("pretest") or False),
              mock.patch.object(engine.next_train, "before_push", lambda top: calls.append("wait")),
              mock.patch.object(engine.hold, "stops", return_value=0),  # no hold (L88: test_orders_ended)
              mock.patch.object(engine.subprocess, "run",
                                lambda argv, cwd: calls.append(argv) or types.SimpleNamespace(returncode=0))):
            self.assertEqual(engine.land("/x", "train-0382"), 0)
        self.assertEqual(calls, ["pretest", "wait", engine.LAND + ["--land-ref", "train-0382"]])
        calls.clear()
        with (mock.patch.object(engine.pretest_train, "before_landing", lambda top: calls.append("pretest") or True),
              mock.patch.object(engine.next_train, "before_push", lambda top: calls.append("wait"))):
            self.assertEqual(engine.land("/x", "train-0382"), 1)
        self.assertEqual(calls, ["pretest"], "a red pretest: no wait, no land run")


class OpenWait(unittest.TestCase):
    def test_the_open_train_joins_each_poll_while_the_run_before_runs_and_never_after(self):
        runs, calls = [[{"databaseId": 720}], [{"databaseId": 720}], []], []  # plan 0490 step 20 (D21, D23, D9)
        with mock.patch.object(next_train, "others", lambda main, own: runs.pop(0)), \
                contextlib.redirect_stdout(io.StringIO()):
            lines = next_train.wait("/m", "land/x", sleep=lambda s: calls.append("sleep"),
                                    join=lambda: calls.append("join") or ["04 joined"])
        self.assertEqual((calls, lines[1:]), (["join", "sleep", "join", "sleep"], ["04 joined", "04 joined"]))


class PostMergeRed(Trains):
    def test_a_post_merge_red_orders_its_car_and_the_next_train_still_goes_with_the_fix(self):
        self.crop("03", {"three.txt": "3"}, plan="0382-three")
        self.panes["03"] = "%3"
        self.merged()
        self.minute()
        b, told = self.train(), len(self.typed)  # the cars were told "in the barn"
        self.gh.jobs["720"].append(job("d1-01-stack-test", "failure"))  # after the merge, while 03's train is formed
        lines = self.minute().splitlines()
        self.assertEqual(lines[0], "job failed: d1-01-stack-test: error: assertion failed at code/x/twenty.py:3")
        self.assertTrue(lines[1].startswith(f"train {self.a['train']}: fix order to 20 for its red after the merge"))
        order = train_state.lines(str(self.main))[-1]
        self.assertEqual((order["kind"], order["field"], order["post"], order["train"], order["branch"]),
                         ("order", "20", self.a["train"], b["train"], "20-train-fix"))
        now = self.train()
        self.assertEqual((now["train"], now["state"], now["orders"], [c["field"] for c in now["cars"]]),
                         (b["train"], "landing", [], ["03"]), "never holds it, no wagon leaves it")
        ((pane, msg),) = self.typed[told:]
        self.assertEqual(pane, "%20")
        for part in (f"git switch -C 20-train-fix origin/{self.carrier()}", f"the next train {b['train']}", "done fixed <sha>"):
            self.assertIn(part, msg)
        self.assertEqual(self.minute(), "", "ordered once")

        self.crop("04", {"four.txt": "4"}, plan="0384-four")
        self.panes["04"] = "%4"
        self.round()
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["03"], "a later hitch waits for the next train")
        sha = self.fix()
        ack = msg.split("]")[0].removeprefix("tollman [")
        self.assertEqual(acks.main(["ack", ack, "done", "fixed", sha, "--repo", str(self.wm), "--role", "tollman"]), 0)
        code, text = self.call("fixed", "20", sha)
        self.assertEqual(code, 1)
        self.assertIn("the landing merges it before its run starts", text)
        self.round()
        self.assertNotIn(("fixed", "run", "20"), self.last, "the round leaves it to the landing's process")

        self.gh.runs[0] = dict(self.run, status="completed", conclusion="failure")  # the run before has finished
        red = {"key": "triage:720:d1-01-stack-test", "kind": "file", "job": "d1-01-stack-test", "owner": "20",
               "unit": "d1-01-stack-test", "run": self.url, "at": self.run["createdAt"], "files": ["code/x/twenty.py"],
               "prefixes": []}  # its triage (plan 0490 step 21): the push waits for 20's fix car (D22)
        run_triage_wire.update(str(self.main), "720", lambda e: e.update(at="2099-01-01T01:00:00+00:00", reds=[red]))
        with contextlib.redirect_stdout(io.StringIO()):
            line, goes = next_train.before_push(str(self.cw), sleep=self.fail)
        self.assertTrue(line.startswith(f"fix order 20-fix-1: 20's fix {sha[:12]} merged into train {b['train']}"))
        self.assertEqual(goes, "next train: every red of run 720 has its fix car or a named reason: the push goes")
        self.assertEqual(out(self.cw, "rev-parse", "HEAD^2"), sha, "it rides this train's run")
        now = self.train()
        self.assertEqual((now["post"], now["state"], [c["field"] for c in now["cars"]]), ([], "landing", ["03"]))

    def test_with_no_train_standing_the_car_fixes_it_in_its_next_harvest(self):
        self.merged()
        self.minute()
        self.assertIsNone(self.train(), "nothing hitched: no next train")
        told = len(self.typed)
        self.gh.jobs["720"].append(job("d1-01-stack-test", "failure"))
        self.minute()
        ((pane, msg),) = self.typed[told:]
        self.assertEqual(pane, "%20")
        self.assertIn("in your next harvest", msg)
        self.assertNotIn("order", [k for k, _ in self.state()])
        self.round()
        self.assertEqual(len(self.typed), told + 1, "stack_red tells nobody twice: the watch settled the run")


class Fold(unittest.TestCase):
    """train_state.standing carries the post-merge orders, never changing a train's state."""

    def test_a_post_order_rides_the_next_train_and_a_landed_train_s_early_order_becomes_one(self):
        def line(kind, train, **kw):
            return {"kind": kind, "train": train, **kw}

        rows = [line("formed", "A", cars=[{"field": "20"}]), line("started", "A", pid=1),
                line("order", "A", id="20-fix-1", field="20"),
                line("order", "A", id="02-fix-1", field="02", post="Z"), line("landed", "A"),
                line("formed", "B", cars=[{"field": "03"}])]
        b = train_state.standing(rows)
        self.assertEqual((b["state"], [(o["id"], o["post"]) for o in b["post"]]),
                         ("formed", [("02-fix-1", "Z"), ("20-fix-1", "A")]))
        b = train_state.standing(rows + [line("started", "B", pid=2), line("fixed", "B", id="20-fix-1")])
        self.assertEqual((b["state"], [o["id"] for o in b["post"]], b["orders"]), ("landing", ["02-fix-1"], []))
        cleared = train_state.standing(rows[:3] + [line("cleared", "A"), line("formed", "B")])
        self.assertEqual(cleared["post"], [], "a broken-up train's own orders do not ride on")

    def test_past_is_the_train_as_it_stood_before_it_landed(self):
        rows = [{"kind": "formed", "train": "A", "cars": []}, {"kind": "started", "train": "A", "pid": 1},
                {"kind": "landed", "train": "A"}, {"kind": "formed", "train": "B", "cars": []}]
        self.assertEqual((post_merge.past(rows, "A")["state"], post_merge.past(rows, "B")["train"]), ("landing", "B"))
        self.assertIsNone(post_merge.past(rows, "C"))
        self.assertIsNone(post_merge.past(rows, None))

    def test_stack_red_leaves_a_run_the_watch_owns(self):
        rows = [{"kind": "landed", "train": "A", "run": "https://github.com/x/actions/runs/720",
                 "at": "2099-01-01T00:00:00Z", "cars": ["20"]}]
        fetch = mock.Mock(return_value=[job("d1-01-stack-test", "failure")])
        with mock.patch.object(stack_red.gh_runs, "_round", None):
            self.assertEqual(stack_red.watch("/t", "/m", rows, {}, [{"key": "post-order:720"}], fetch), [])
            self.assertEqual(stack_red.watch("/t", "/m", rows, {}, [], fetch, watched="720"), [])
            self.assertTrue(stack_red.watch("/t", "/m", rows, {}, [], fetch, now=None), "else as before")


if __name__ == "__main__":
    unittest.main()
