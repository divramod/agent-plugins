import datetime as dt
import unittest
from pathlib import Path
from unittest import mock

import mtm_scan
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


if __name__ == "__main__":
    unittest.main()
