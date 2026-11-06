"""Hal2 plan 0522 step 7 (D17): a land run that finished red ends the train's landing at once, in the next minute
pass, and the fixed carrier is pushed in the minute every fix is in and the landing's process is gone, never at the
round's or the landing's poll. The regression replays train 32's run 41167356202 of 2026-10-31 (its three red jobs,
fixtures/run-41167356202.json): finished red at 05:00:27Z, the red line written by the round at 05:05:16Z, the fixed
carrier pushed at 05:07Z. Whole minute passes (`minute.run`) on engine_farm's farm: the engine's verbs run, the
landing is never started (its pid is data), gh is gh_fake's. Every train line of a test is stamped in the second
its setUp began: a restart within its start's second (the replay's flake) must still be a new start."""
# enforces .adr/deterministic-first.md, .adr/tollman.md and .adr/landings-survive-their-process.md

import contextlib
import datetime as dt
import io
import json
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import engine
import landing_end
import leavers
import minute
import mtm_scan
import tollman
import train_state
import watch_events
from engine_farm import Farm
from gh_fake import FakeGh, job, run
from logstate import read_log

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "run-41167356202.json").read_text())
RID = FIXTURE["run"]
REDS = [j["name"] for j in FIXTURE["jobs"]]  # c4-01-bash-test, c2-10-ts-test, c2-13-bash-test-linux
URL = f"https://github.com/divramod/hal2/actions/runs/{RID}"
UTC = train_state.utc


class Ends(Farm):
    def setUp(self):
        second = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)  # every train line in this second
        p = mock.patch.object(train_state, "utc", lambda now=None: UTC(second))
        p.start()
        self.addCleanup(p.stop)
        super().setUp()
        self.crop("07", {"seven.txt": "7"})
        self.crop("09", {"nine.txt": "9"})
        self.round()  # the train forms and its landing starts (pid 40001)
        self.alive.add(40001)
        self.name = self.train()["train"]
        self.gh = FakeGh([run(RID, "land/train-1-1", "2099-01-01T00:00:00Z", status="in_progress")],
                         jobs={RID: [job(n) for n in REDS] + [job("d2-01-git-merge", None)]}).start(self)
        gate = self.gate
        p = mock.patch.object(mtm_scan, "run_json", lambda args, cwd=None: gate.queue()
                              if args[:3] == ["hal2-cli-git", "worktree", "queue"] else self.gh.run_json(args, cwd))
        p.start()
        self.addCleanup(p.stop)
        t = self.train()  # the watch told the three reds while the run ran (step 6 ordered two of them)
        leavers.write(str(self.main), watch_events.FILE, {
            "schema": 1, "run": RID, "url": URL, "train": t["train"], "started": t["started"], "start": t["starts"],
            "closed": False,
            "seen": [f"job:{RID}:{n}" for n in REDS]})
        for field, red in (("09", REDS[1]), ("07", REDS[2])):
            train_state.append(str(self.main), "order", self.carrier(), train=self.name, field=field,
                               branch=f"{field}-train-fix", base=t["base"], why=red, run=URL, id=f"{field}-fix-1",
                               jobs=[red.split("-", 2)[2]])

    def minute(self) -> list[str]:
        """One minute pass, as the timer runs it: its printed lines."""
        text = io.StringIO()
        with contextlib.redirect_stdout(text):
            self.assertEqual(minute.run(str(self.wm), tollman.WIRING), 0)
        return text.getvalue().splitlines()

    def finish(self, conclusion="failure", merged=False):
        self.gh.runs[0] = run(RID, "land/train-1-1", "2099-01-01T00:00:00Z", conclusion=conclusion)
        self.gh.jobs[RID][-1] = job("d2-01-git-merge", "success" if merged else "skipped")

    def fix(self, field):
        train_state.append(str(self.main), "fixed", self.carrier(), train=self.name, field=field, id=f"{field}-fix-1",
                           sha="f" * 40, commit=engine.git(str(self.cw), "rev-parse", "HEAD")[1])

    def keys(self, kind):
        return [e["key"] for e in read_log(str(self.main), "tollman") if e.get("kind") == kind]

    def test_run_41167356202_ends_red_in_its_first_pass_and_lands_again_once_every_fix_is_in(self):
        self.assertEqual(self.minute(), [f"land run started: {RID} ({URL})"], "05:00Z: the run runs, its reds told before")
        self.finish()  # 05:00:27Z
        self.assertEqual(self.minute(), [f"workflow finished: failure ({URL})",
                                         f"train {self.name} is red (gate_failed): {', '.join(REDS)}"],
                         "05:01Z: the red is taken at once, never the round's 05:05:16Z")
        t = self.train()
        self.assertEqual((t["state"], t["why"], t["run"]), ("fixing", ", ".join(REDS), URL),
                         "its early orders answer the red: fixing, no wake")
        self.assertEqual(self.alive, {40001}, "the landing's process is never touched: it ends on its own")
        self.assertEqual(self.minute(), [], "no second red")
        self.fix("09")
        self.assertEqual((self.minute(), self.train()["state"]), ([], "fixing"), "07's fix is still out")
        self.fix("07")
        self.assertEqual(self.train()["state"], "retry")
        self.assertEqual((self.minute(), self.spawned), ([], [self.carrier()]),
                         "every fix is in, the last start's process still ends: no second landing beside it")
        planned = json.loads(self.call("tick", "--dry-run", "--json")[1])["planned"]
        round_key = [a["key"] for a in planned if a["kind"] == "restart"]
        self.alive.clear()  # its process is gone
        self.assertEqual(self.minute(), [f"train {self.name} lands again"])
        self.assertEqual((self.spawned, self.train()["state"], self.train()["starts"]), ([self.carrier()] * 2, "landing", 2))
        self.assertEqual(self.keys("restart"), round_key, "the round's own key: the round never pushes it twice")
        self.assertEqual(self.minute(), [])
        self.round()
        self.assertEqual((self.last, len(self.spawned)), ([("restart", "run", "-")], 3),
                         "the new start's process gone without a word: the round adopts (interrupted), never the pass")
        self.assertEqual(self.keys("red"), [f"red:{self.name}:1"], "one red line")

    def test_the_push_keys_by_the_attempt(self):
        """Plan 0620 D5: the pass pushes a retry train with the round's key, `retry:<train>:<attempt>`; a restart
        that started nothing (proof_red) raised it, so the fixed train's push is never the used key."""
        self.fix("09")
        self.fix("07")
        self.alive.clear()
        self.assertEqual([a["key"] for a in landing_end.push(str(self.wm), str(self.main), self.train())],
                         [f"retry:{self.name}:1"])
        train_state.append(str(self.main), "attempt", self.carrier(), train=self.name, attempt=2)
        self.assertEqual([a["key"] for a in landing_end.push(str(self.wm), str(self.main), self.train())],
                         [f"retry:{self.name}:2"])

    def test_a_restart_while_the_last_start_s_process_lives_waits_offline(self):
        self.finish()
        self.minute()
        self.fix("09")
        self.fix("07")
        code, text = engine.restart(str(self.wm))
        self.assertEqual((code, self.spawned), (75, [self.carrier()]), text)
        self.assertIn("still ends", text)

    def test_a_red_after_the_merge_job_and_a_cancelled_run_end_nothing(self):
        self.finish(merged=True)
        self.assertIn(f"workflow finished: failure ({URL})", self.minute(), "post-merge: post_merge.py's")
        self.assertEqual(self.train()["state"], "landing")
        state = {**watch_events.state(str(self.main)), "conclusion": "cancelled"}
        state["seen"] = [k for k in state["seen"] if not k.startswith("merge:")]
        self.assertFalse(landing_end.ended(self.train(), state), "a pause's or a newer push's cancel")

    def test_a_green_run_forms_the_next_train_after_the_landing_s_end(self):
        self.finish("success", merged=True)
        self.assertEqual(self.minute(), [f"merge job green: d2-01-git-merge ({URL})",
                                         f"workflow finished: success ({URL})", f"land run started: {RID} ({URL})"], "its process still runs")
        self.ends({"status": "landed", "run": URL, "commit": "c" * 40}, land=True)
        self.assertIn(f"train {self.name}: merge job green: the next train forms on the new main", self.minute())
        self.assertEqual([e["kind"] for e in train_state.lines(str(self.main))][-1], "landed")
        self.assertEqual(self.keys("red"), [], "no red")
