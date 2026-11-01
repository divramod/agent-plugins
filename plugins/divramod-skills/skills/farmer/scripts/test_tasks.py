import datetime as dt
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import due
import mtm_scan
import task_detach
import tasks
import tick

PROPOSAL = (Path(__file__).resolve().parent / "testdata/owner-role-hal2-tasks.md").read_text()
TODAY = """
## Tasks

### n8n.hal9k.app stays up

- **Cron**: `*/15 * * * *`
- **Check**: `curl -fsS https://n8n.hal9k.app/healthz` and `hal2-cli-n8n instances check hal9k --json` (ready).
- **Act**: down or not ready: redeploy n8n's services from main (`code/python/scripts/hal9k` `deploy app`).
"""
CTX = {"top": "/x/farmer", "main": "/x/hal2"}


def item(name):
    return {"name": f"task:{name}"}


class Parse(unittest.TestCase):
    def test_the_proposal_is_machine_run_and_todays_prose_never_runs_a_command(self):
        specs = tasks.parse(PROPOSAL)
        self.assertEqual({n: s["machine"] for n, s in specs.items()},
                         {"n8n.hal9k.app stays up": True, "hal9k production healthy": True,
                          "Disabled tests come back": True, "Orphaned slots finished": True})
        self.assertEqual(specs["n8n.hal9k.app stays up"]["act"][1], ("notify", ""))
        self.assertEqual(specs["n8n.hal9k.app stays up"]["still"], [("delegate", ""), ("notify", "")])
        self.assertFalse(tasks.parse(TODAY)["n8n.hal9k.app stays up"]["machine"])
        self.assertEqual(tasks.argv("farmer check flaky", "/x/farmer")[-4:], ["check", "flaky", "--repo", "/x/farmer"])


class Plan(unittest.TestCase):
    def setUp(self):
        self.specs = tasks.parse(PROPOSAL)

    def plan(self, name, ok, specs=None, why="boom: exit 7", online=True):
        return tasks.plan_task(item(name), CTX, specs or self.specs, lambda cmds, top, main: (ok, why), lambda: online)

    def test_hal2s_tasks_run_without_a_wake_while_their_checks_pass(self):
        for name in self.specs:
            self.assertEqual([a["do"] for a in self.plan(name, True)], ["record"], name)

    def test_a_failing_check_runs_the_act_then_rechecks_with_its_still_failing_outcomes(self):
        plan = self.plan("n8n.hal9k.app stays up", False)
        self.assertEqual([a["do"] for a in plan], ["run", "notify", "run"])
        self.assertEqual(plan[0]["argv"][-1], "python3 code/python/scripts/hal9k/main.py deploy app --service n8n n8n-runners")
        self.assertEqual(plan[2]["argv"][-5:], ["check", "task", "n8n.hal9k.app stays up", "--repo", "/x/farmer"])
        self.assertEqual([f["do"] for f in plan[2]["on_fail"]], ["delegate", "notify"])
        self.assertEqual([a["do"] for a in self.plan("Disabled tests come back", False)], ["delegate"])

    def test_prose_wakes_the_model(self):
        self.assertEqual([a["do"] for a in self.plan("n8n.hal9k.app stays up", False, tasks.parse(TODAY))], ["wake"])

    def test_the_recheck_follow_ups_run_only_when_it_fails(self):
        recheck = self.plan("n8n.hal9k.app stays up", False)[2]
        for code, follows in ((0, 0), (1, 2), (tasks.OFFLINE, 0)):
            out = {"wake": [], "notify": []}
            with mock.patch.object(tick, "sh", return_value=(code, "")), mock.patch.object(mtm_scan, "log"):
                tick.execute(dict(recheck), "/x/farmer", "/x/hal2", out)
            self.assertEqual(len(out.get("delegate", [])) + len(out["notify"]), follows)

    def test_the_2026_10_04_dns_outage_of_this_mac_deploys_nothing(self):
        why = ("curl -fsS -m 20 https://n8n.hal9k.app/healthz: exit 6\n"
               "curl: (6) Could not resolve host: n8n.hal9k.app\n")
        plan = self.plan("n8n.hal9k.app stays up", False, why=why, online=False)
        self.assertEqual([(a["do"], a["text"]) for a in plan],
                         [("record", "task n8n.hal9k.app stays up: check skipped: this machine is offline")])
        self.assertEqual([a["do"] for a in self.plan("hal9k production healthy", False, online=False)], ["record"])

    def test_a_real_outage_still_acts_and_the_brief_carries_the_checks_output(self):
        why = "curl -fsS -m 20 https://n8n.hal9k.app/healthz: exit 22\ncurl: (22) The requested URL returned error: 502\n"
        plan = self.plan("n8n.hal9k.app stays up", False, why=why, online=True)
        self.assertEqual([a["do"] for a in plan], ["run", "notify", "run"])
        delegate = plan[2]["on_fail"][0]
        self.assertEqual(delegate["text"], "task n8n.hal9k.app stays up: still failing after the act")
        self.assertIn("returned error: 502", delegate["brief"]["check"])

    def test_farmer_check_task_exits_75_when_offline(self):
        role = PROPOSAL
        with mock.patch.object(Path, "read_text", return_value=role), \
                mock.patch.object(mtm_scan, "main_checkout", return_value="/x/hal2"), \
                mock.patch.object(tasks, "run_check", return_value=(False, "curl: (6) Could not resolve host")):
            self.assertEqual(tasks.builtin("n8n.hal9k.app stays up", "/x/farmer", lambda: False)[0], tasks.OFFLINE)
            self.assertEqual(tasks.builtin("n8n.hal9k.app stays up", "/x/farmer", lambda: True)[0], 1)


class BuiltinChecks(unittest.TestCase):
    def test_farmer_check_flaky_and_orphans_run_in_the_ticks_process(self):
        # plan 0011: a second python with its own snapshot cost 8 s a round; in-process they share the round.
        calls = []
        with mock.patch.object(tasks, "builtin", side_effect=lambda what, top: calls.append(what) or
                               ((1, "13: work without agent") if what == "orphans" else (0, ""))), \
                mock.patch.object(tasks.subprocess, "run") as run:
            self.assertEqual(tasks.run_check(["farmer check flaky"], "/x/farmer", "/x/hal2"), (True, ""))
            ok, why = tasks.run_check(["farmer check orphans"], "/x/farmer", "/x/hal2")
            run.assert_not_called()
        self.assertEqual((calls, ok), (["flaky", "orphans"], False))
        self.assertIn("farmer check orphans: exit 1\n13: work without agent", why)
        with mock.patch.object(tasks.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            tasks.run_check(["farmer check task n8n"], "/x/farmer", "/x/hal2")  # a task's check: its own process
            run.assert_called_once()


class Online(unittest.TestCase):
    def test_online_needs_a_name_and_a_connection(self):
        conn = mock.Mock()
        with mock.patch("socket.getaddrinfo", side_effect=OSError("nodename nor servname provided")), \
                mock.patch("socket.create_connection", return_value=conn):
            self.assertFalse(tasks.online())
        with mock.patch("socket.getaddrinfo", return_value=[1]), mock.patch("socket.create_connection", return_value=conn):
            self.assertTrue(tasks.online())
        with mock.patch("socket.getaddrinfo", return_value=[1]), \
                mock.patch("socket.create_connection", side_effect=OSError("no route")):
            self.assertFalse(tasks.online())


class Flaky(unittest.TestCase):
    def test_entries_back_or_with_a_running_plan_are_fine(self):
        ledger = ("- d · a · x · wt 12 · f · plan 1 · shot · running (16, plan 0120)\n"
                  "- d · b · x · wt 12 · f · plan 1 · shot · landed 2026-10-04\n"
                  "- d · c · x · wt 12 · f · plan 1 · shot · running (17, plan 0121)\n")
        with mock.patch.object(Path, "exists", return_value=True), mock.patch.object(Path, "read_text", return_value=ledger):
            self.assertEqual(tasks.flaky_open("/x/hal2", {"16": {"plan": "0120-x"}, "17": {"plan": ""}}),
                             ["d · c · x · wt 12 · f · plan 1 · shot · running (17, plan 0121)"])


LONG = """
## Tasks

### prune round

- **Cron**: `*/15 * * * *`
- **Limit**: 2700 s
- **Check**: `farmer prune-round`
- **Act**: notify
"""
T0 = dt.datetime(2026, 10, 31, 12, 0)


class Limit(unittest.TestCase):
    def test_a_task_declares_its_limit_and_defaults_to_120_s(self):
        self.assertEqual(tasks.parse(LONG)["prune round"]["limit"], 2700)
        self.assertEqual(tasks.parse(LONG.replace("- **Limit**: 2700 s\n", ""))["prune round"]["limit"], due.DEFAULT_LIMIT)
        self.assertTrue(all(s["limit"] == due.DEFAULT_LIMIT for s in tasks.parse(PROPOSAL).values()))

    def test_a_malformed_limit_is_a_problem_of_the_role_check(self):
        front = "---\nnotify: every-round\n---\n"
        for bad in ("soon", "0 s", "-5 s", "1.5 s", "10 min"):
            problems = due.schedule(front + LONG.replace("2700 s", bad))[2]
            self.assertTrue(any("**Limit**" in p and "prune round" in p for p in problems), bad)
        self.assertEqual(due.schedule(front + LONG)[2], [])
        self.assertEqual(due.schedule(front + LONG.replace("2700 s", "`90 s`"))[2], [])

    def test_a_short_limit_is_the_inline_timeout_and_names_itself_in_the_failure(self):
        short = LONG.replace("2700 s", "60 s")
        spec = tasks.parse(short)["prune round"]
        seen = []
        out = tasks.plan_task(item("prune round"), CTX, {"prune round": spec},
                              lambda cmds, top, main, limit: seen.append(limit) or (True, ""), lambda: True)
        self.assertEqual((seen, [a["do"] for a in out]), ([60], ["record"]))
        with mock.patch.object(tasks.subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 60)) as run:
            self.assertEqual(tasks.run_check(["sleep 99"], "/x/farmer", "/x/hal2", 60), (False, "sleep 99: timed out after 60 s"))
            self.assertEqual(run.call_args.kwargs["timeout"], 60)


class Detached(unittest.TestCase):
    """A Check over 120 s runs detached; the clock is fake (ctx now), the process starter, kill and alive too."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.spec = tasks.parse(LONG)["prune round"]
        self.spawned, self.killed, self.up = [], [], True
        self.d = types.SimpleNamespace(
            TIMED_OUT=task_detach.TIMED_OUT, read=task_detach.read, finish=task_detach.finish, consume=task_detach.consume,
            status=lambda rec, now: task_detach.status(rec, now, lambda pid: self.up),
            start=lambda *a: task_detach.start(*a, spawn=lambda argv, **kw: self.spawned.append(argv)),
            terminate=self.killed.append)
        patch = mock.patch.object(tasks, "task_dir", return_value=self.folder)
        patch.start()
        self.addCleanup(patch.stop)

    def tick(self, seconds, dry=False, net=True):
        ctx = {**CTX, "now": T0 + dt.timedelta(seconds=seconds), "dry": dry}
        return tasks.plan_task(item("prune round"), ctx, {"prune round": self.spec},
                               lambda *a, **k: self.fail("a detached task never runs inline"), lambda: net, self.d)

    def runner(self, ok, why="", at=0):
        """The runner process, as the spawned one does: it marks itself running (pid 4242), then writes the result."""
        rec = task_detach.read(self.folder, "prune round")
        task_detach.write(self.folder, "prune round", {**rec, "state": "running", "pid": 4242})
        cur = task_detach.read(self.folder, "prune round")
        task_detach.finish(self.folder, "prune round", cur, ok, why, (T0 + dt.timedelta(seconds=at)).timestamp())

    def test_a_check_of_600_s_finishes_and_the_next_tick_reports_a_pass(self):
        first = self.tick(0)
        self.assertEqual([(a["do"], "started detached" in a["text"]) for a in first], [("record", True)])
        self.assertEqual(len(self.spawned), 1)
        self.runner(True, at=600)  # the check "ran" 600 s by the fake clock, five times the old inline limit
        out = self.tick(900)
        self.assertEqual([(a["do"], a["text"]) for a in out], [("record", "task prune round: check passed")])
        self.assertEqual(len(self.spawned), 2)  # the next run starts in the same round
        self.assertEqual(task_detach.read(self.folder, "prune round")["state"], "starting")

    def test_a_check_that_failed_after_600_s_notifies_on_the_next_tick_once(self):
        self.tick(0)
        self.runner(False, "farmer prune-round: exit 1\nprune failed: field 17 busy", at=600)
        out = self.tick(900)
        self.assertEqual([a["do"] for a in out], ["notify"])
        self.assertIn("prune failed: field 17 busy", out[0]["text"])
        self.assertEqual(len(self.spawned), 2)
        self.assertEqual([a["do"] for a in self.tick(960)], ["record"])  # the new run is running: nothing re-evaluated

    def test_a_result_is_evaluated_once(self):
        self.tick(0)
        self.runner(False, "x: exit 1", at=10)
        self.tick(900)
        rec = task_detach.read(self.folder, "prune round")
        self.assertEqual(task_detach.status(rec, (T0 + dt.timedelta(seconds=901)).timestamp(), lambda p: True), "running")

    def test_a_run_under_its_limit_is_not_started_twice(self):
        self.tick(0)
        self.runner(True, at=1000)  # finished long ago; consume it, a new run starts
        self.tick(1100)
        rec = {**task_detach.read(self.folder, "prune round"), "state": "running", "pid": 4242}
        task_detach.write(self.folder, "prune round", rec)
        n = len(self.spawned)
        for later in (1200, 2000, 3700):  # 3700 - 1100 = 2600 s, still under 2700
            out = self.tick(later)
            self.assertEqual([a["do"] for a in out], ["record"])
            self.assertIn("running since", out[0]["text"])
        self.assertEqual((len(self.spawned), self.killed), (n, []))

    def test_a_run_past_its_limit_is_killed_and_notifies(self):
        self.tick(0)
        task_detach.write(self.folder, "prune round", {**task_detach.read(self.folder, "prune round"),
                                                       "state": "running", "pid": 4242})
        out = self.tick(2701)
        self.assertEqual(self.killed, [4242])
        self.assertEqual([a["do"] for a in out], ["notify"])
        self.assertIn("timed out after 2700 s", out[0]["text"])
        self.assertEqual(len(self.spawned), 2)

    def test_a_run_at_exactly_its_limit_still_runs(self):
        self.tick(0)
        task_detach.write(self.folder, "prune round", {**task_detach.read(self.folder, "prune round"),
                                                       "state": "running", "pid": 4242})
        self.assertEqual(self.tick(2700)[0]["do"], "record")
        self.assertEqual(self.killed, [])

    def test_a_runner_that_died_without_a_result_is_a_failed_check(self):
        self.tick(0)
        task_detach.write(self.folder, "prune round", {**task_detach.read(self.folder, "prune round"),
                                                       "state": "running", "pid": 4242})
        self.up = False
        out = self.tick(300)
        self.assertEqual(([a["do"] for a in out], self.killed), (["notify"], []))
        self.assertIn("runner died", out[0]["text"])

    def test_a_failure_while_the_machine_is_offline_is_only_recorded(self):
        self.tick(0)
        self.runner(False, "curl: (6) Could not resolve host", at=5)
        out = self.tick(900, net=False)
        self.assertEqual([(a["do"], "offline" in a["text"]) for a in out], [("record", True)])

    def test_a_dry_round_starts_kills_and_consumes_nothing(self):
        self.assertEqual(self.tick(0, dry=True)[0]["do"], "record")
        self.assertEqual((self.spawned, list(self.folder.iterdir())), ([], []))
        self.tick(0)
        self.runner(False, "boom", at=5)
        before = task_detach.read(self.folder, "prune round")
        self.assertEqual([a["do"] for a in self.tick(900, dry=True)], ["notify"])
        self.assertEqual((task_detach.read(self.folder, "prune round"), len(self.spawned)), (before, 1))

    def test_farmer_check_task_never_blocks_and_never_starts_a_second_run(self):
        spec = {**self.spec, "check": ["farmer prune-round"]}
        run = lambda t: tasks.detached_check("prune round", spec, "/x/farmer", "/x/hal2", self.d, t)  # noqa: E731
        t0 = T0.timestamp()
        self.assertEqual(run(t0)[0], 0)
        self.assertEqual(len(self.spawned), 1)
        self.assertEqual(run(t0 + 30), (0, f"task prune round: check already running since {task_detach.stamp(t0)}"))
        self.assertEqual(len(self.spawned), 1)
        self.assertEqual(run(t0 + 2701)[0], 1)  # past its limit: the tick kills it, no new run meanwhile
        self.runner(False, "boom: exit 3", at=40)
        self.assertEqual(run(t0 + 60), (1, "boom: exit 3"))
        self.assertEqual(len(self.spawned), 1)


if __name__ == "__main__":
    unittest.main()
