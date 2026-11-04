"""The sources wired into stop and done (plan 0585 step 3): sources 1-5 in order, each pass measured in the record,
the log and stats, the rescan's holders and busy runners, done's undo order and a timed-out `thaw all`. One fake
machine (AllSys) answers the workqueue and CI CLIs, the sessions and quiet.py are test_interrupt's fakes; nothing
real is signalled, frozen or stopped."""
import json
import os
import stat
from pathlib import Path

import interrupt  # first: it puts stop-all-agent-work's scripts on sys.path
import stopall
from test_freeze import ME
from test_interrupt import Base
from test_runners import FOLDERS, CiSys
from test_sources import WqSys


class AllSys(WqSys):
    """WqSys (machine, workqueue holders) plus CiSys's hal2-cli-ci; `events` is the run/kill timeline."""

    def __init__(self, wq_cli, ci_cli):
        super().__init__(wq_cli)
        self.idle, self.vms = [30.0, 85.0], [{"Name": "hal2-ci-runner-macos", "Running": True}]
        self.ci, self.events, self.thaw_code, self.free_after = CiSys(ci_cli), [], 0, None

    def run(self, cmd, timeout=60):
        if cmd[0] == self.ci.cli:
            self.events.append(" ".join(c for c in cmd[1:3] if c != "--json"))
            if "status" in cmd and self.free_after is not None:
                self.free_after -= 1
                if self.free_after < 0:
                    self.ci.busy_letters.clear()
                    for r in self.ci.runners:
                        r["busy"] = False
            return self.ci.run(cmd, timeout)
        if cmd[0] == self.cli:
            self.events.append(" ".join(cmd[1:3]))
            if cmd[1:3] == ["thaw", "all"] and self.thaw_code:
                self.wq.append((cmd[1:], timeout))
                return self.thaw_code, "", f"timed out after {timeout}s"
        return super().run(cmd, timeout)

    def kill(self, pid, sig):
        self.events.append(f"{sig} {pid}")
        return super().kill(pid, sig)


class PassesBase(Base):
    def setUp(self):
        super().setUp()
        base = Path(self.tmp.name)
        for f in FOLDERS:
            (base / "runners" / f).mkdir(parents=True)
        clis = {}
        for name in ("hal2-cli-workqueue", "hal2-cli-ci"):
            clis[name] = base / name
            clis[name].write_text("#!/bin/sh\nexit 99\n")  # never run: AllSys answers it
            clis[name].chmod(clis[name].stat().st_mode | stat.S_IXUSR)
        os.environ.update({"HAL2_CLI_WORKQUEUE": str(clis["hal2-cli-workqueue"]),
                           "HAL2_CLI_CI": str(clis["hal2-cli-ci"]), "HAL2_HOST_RUNNER_ROOT": str(base / "runners")})
        self.sys = AllSys(str(clis["hal2-cli-workqueue"]), str(clis["hal2-cli-ci"]))

    def actions(self):
        return json.loads(stopall.record().read_text())["actions"]

    def out(self):
        return "\n".join(self.lines)


STEPS = ["sessions", "daemon", "vms", "workqueue holders", "host runners", "quiet", "builds", "wq-quiet", "rescan", "leftovers"]


class StopTest(PassesBase):
    def test_dry_run_lists_sources_1_to_5_and_changes_nothing(self):
        self.assertEqual(self.run_stop("--dry-run"), 0)
        out = self.out()
        for n in range(1, 6):
            self.assertIn(f"-- source {n} ", out)
        self.assertIn("would stop host runner mac-host-hal2-a", out)
        self.assertIn("would freeze workqueue holder 700", out)
        self.assertEqual(self.sys.kills, [])
        self.assertEqual(self.sys.ci.stops(), [])
        self.assertEqual([c[:2] for c, _ in self.sys.wq], [["frozen", "--json"]])
        self.assertFalse(stopall.record().exists())

    def test_stop_runs_every_source_in_order_and_measures_each(self):
        self.assertEqual(self.run_stop(), 0)
        kinds = [a["kind"] for a in self.actions() if a.get("kind")]
        first = {k: kinds.index(k) for k in ("daemon", "vm", "wq-freeze", "holder", "host-runner", "build")}
        self.assertEqual(sorted(first, key=first.get), ["daemon", "vm", "wq-freeze", "holder", "host-runner", "build"])
        self.assertEqual(kinds.count("host-runner"), 4)
        self.assertEqual(self.quiet.applied[0][1], False)  # hal2-cli-ci stops the runners, not quiet.py's bootout
        ii = json.loads(stopall.record().read_text())["important_interrupt"]
        self.assertEqual([s["step"] for s in ii["steps"]], STEPS)
        self.assertTrue(all(s["idle"] == 50.0 for s in ii["steps"] if s["step"] != "rescan"))
        self.assertEqual(ii["steps"][-2]["idle"], 85.0)
        self.assertEqual(len(ii["sources"]["host runners"]["stopped"]), 4)
        self.assertEqual(ii["sources"]["workqueue holders"]["holders"], 2)
        row = json.loads((interrupt.root() / "log.jsonl").read_text().splitlines()[-1])
        self.assertEqual(row["steps"], ii["steps"])
        self.assertIn("-- source 4 host runners: 4 done in 0.0s, CPU idle 50% after", self.lines)
        self.lines.clear()
        interrupt.main(["stats"], self.deps())
        self.assertTrue(any(x.startswith("    sessions 0.0s 50% · daemon 0.0s 50%") for x in self.lines))

    def test_a_holder_started_later_is_frozen_by_the_rescan(self):
        late = {710: [1, ME, "S", 20.0, "/u/hal2-cli-workqueue", "hal2-cli-workqueue freeze serve --manual {}"]}
        self.sys.idle = [30.0, 30.0, 85.0]
        self.assertEqual(self.run_stop(tables=[late]), 0)
        self.assertIn((710, "STOP"), self.sys.kills)
        self.assertTrue(any(a["undo"] == ["CONT", 710] for a in self.actions()))

    def test_a_busy_runner_is_retried_and_stops_once_free(self):
        self.sys.ci.runners[0]["busy"] = True  # mac-host-hal2-a runs a job; its second status shows it free
        self.sys.free_after = 1
        self.assertEqual(self.run_stop(), 0)
        names = [a["text"] for a in self.actions() if a.get("kind") == "host-runner"]
        self.assertEqual(names[-1], "stop host runner mac-host-hal2-a")  # by the rescan's retry
        self.assertNotIn("still busy", self.out())

    def test_a_runner_still_busy_does_not_keep_the_machine_loud(self):
        self.sys.ci.runners[0]["busy"] = True
        self.assertEqual(self.run_stop(), 0)
        self.assertIn("host runners still busy with a job (not stopped, their builds frozen): mac-host-hal2-a",
                      self.out())

    def test_a_farmer_of_another_farm_is_told(self):
        self.msg.rows.append({"pid": 16, "name": "farmer-diktier", "checkout": "/a/diktier", "socket": "/s/16.sock",
                              "pane": None})
        self.run_stop("--dry-run")
        self.assertIn("farmer-diktier", [s[0] for s in self.msg.sent])
        self.assertIn("  farmers among them: farmer-diktier", self.lines)

    def test_missing_tart_is_reported(self):
        self.sys.vms = None
        self.assertEqual(self.run_stop("--dry-run"), 0)
        self.assertIn("tart not found: no CI VMs to stop", self.lines)


class DoneTest(PassesBase):
    def stopped(self):
        self.assertEqual(self.run_stop(), 0)
        self.sys.events.clear()
        self.lines.clear()

    def test_done_undoes_the_sources_in_reverse(self):
        self.stopped()
        self.assertEqual(interrupt.main(["done"], self.deps()), 0)
        ev = self.sys.events
        starts = [i for i, e in enumerate(ev) if e == "runner start"]
        self.assertEqual(len(starts), 4)
        conts = [ev.index("CONT 701"), ev.index("CONT 700")]
        self.assertLess(max(starts), min(conts))
        self.assertLess(max(conts), ev.index("thaw all"))
        self.assertLess(ev.index("thaw all"), ev.index("CONT 600"))  # hal2-daemon last
        self.assertNotIn("CONT 702", ev)  # stopped before the interrupt
        row = json.loads((interrupt.root() / "log.jsonl").read_text().splitlines()[-1])
        self.assertEqual((row["counts"]["holder"], row["counts"]["host-runner"]), (2, 4))

    def test_done_dry_run_lists_every_undo(self):
        self.stopped()
        self.assertEqual(interrupt.main(["done", "--dry-run"], self.deps()), 0)
        out = self.out()
        for want in ("would undo stop host runner mac-host-hal2-a", "would undo freeze workqueue holder 700",
                     "would undo freeze every session's work (workqueue)", "would undo freeze hal2-daemon 600"):
            self.assertIn(want, out)
        self.assertEqual(self.sys.events, [])

    def test_a_timed_out_thaw_all_is_reported_and_done_goes_on(self):
        self.stopped()
        self.sys.thaw_code = 124
        self.assertEqual(interrupt.main(["done"], self.deps()), 0)
        self.assertIn((["thaw", "all"], 30), self.sys.wq)
        self.assertIn("(timed out after 30s)", self.out())
        self.assertIn("holds thaw all: 702;", self.out())
        self.assertEqual(self.sys.events[-1], "CONT 600")
