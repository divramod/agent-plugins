"""The prune duty's scan and plan, the tollman's since plan 0360 step 7 (D30, D67): which fields are free, what a
round plans for them, the disk report. Its hands (`clean`, `remove`) are test_prune_act.py's and test_removal.py's;
the fields of the last landed train test_barn.py's. No real session, removal or hal2-cli-agents."""

import datetime as dt
import subprocess
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import prune
import prune_proof
import tick
import tollman
import worktree_farm
from test_farmer import NOW, git
from worktree_farm import NOW_MS

ROLE = """---
duties:
  prune: "*/15 * * * *"
notify: every-round
---

# x
"""
INFO = {"free_gb": 400.0, "biggest": [(12.0, "03"), (3.0, "13")]}


class Scanning:
    def why(self, ctx=None, agents=(), build=lambda path: False):
        found = prune_proof.scan(str(self.main), ctx or {}, list(agents), NOW_MS, build)
        return {w["slot"]: w["why"] for w in found}

    def plan(self, ctx=None, log=(), info=INFO, landed=None):
        found = prune_proof.scan(str(self.main), ctx or {}, [], NOW_MS, lambda path: False)
        c = {"main": str(self.main), "now": NOW, "log": list(log), **(ctx or {})}
        return tick.fresh(prune.plan({}, c, found, info, landed or {}), list(log), NOW)


class Slots(Scanning, worktree_farm.Slots):
    pass


class MarkedSlots(Scanning, worktree_farm.MarkedSlots):
    pass


class Scan(Slots):
    def test_only_numbered_slots_and_each_kind_of_unsaved_work(self):
        why = self.why()
        self.assertEqual(sorted(why), ["03", "04", "05", "06", "07", "13", "14"])
        self.assertEqual([s for s, w in why.items() if w is None], ["03", "13", "14"])
        self.assertIn("uncommitted", why["04"])
        self.assertIn("CURRENT_PLAN names 0001-x", why["05"])
        self.assertIn("1 commit(s) not on origin/main", why["06"])
        self.assertIn("side branch 07-ui", why["07"])

    def test_the_heads_are_the_worktree_list_s_and_the_base_is_asked_once_per_scan(self):
        git(self.main, "worktree", "add", "-q", "--orphan", "-b", "15", str(self.base / "15"))  # an unborn branch
        heads = {w["slot"]: w["head"] for w in prune_proof.slots(str(self.main))}
        for slot, head in heads.items():
            asked = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.base / slot, capture_output=True, text=True)
            self.assertEqual(head, asked.stdout.strip() if asked.returncode == 0 else "", slot)
        self.assertEqual(heads["15"], "")
        with mock.patch.object(tick, "default_ref", wraps=tick.default_ref) as ref:
            self.assertIn("1 commit(s) not on origin/main", self.why()["06"])
        self.assertEqual(ref.call_count, 1)

    def test_a_ticket_a_pause_an_open_ask_a_busy_agent_a_build(self):
        self.assertIn("ticket", self.why({"waiting": {"13"}})["13"])
        self.assertIn("ticket", self.why({"landing": {"13"}})["13"])
        ask = [{"at": NOW.isoformat(), "kind": "ask", "slot": "13"}]
        self.assertIn("answer", self.why({"log": ask})["13"])
        busy = {"pane_id": "%9", "checkout": str(self.base / "03"), "state": "blocked", "since": 0}
        self.assertIn("blocked", self.why(agents=[busy])["03"])
        self.assertIn("build", self.why(build=lambda path: path.endswith("13"))["13"])

    def test_a_recent_session_keeps_a_10_99_slot_not_a_00_09_one(self):
        recent = lambda slot: {"pane_id": "%9", "checkout": str(self.base / slot), "state": "idle",  # noqa: E731
                               "since": NOW_MS - 60_000}
        self.assertIn("active", self.why(agents=[recent("13")])["13"])
        self.assertIsNone(self.why(agents=[recent("03")])["03"])
        old = {**recent("13"), "since": NOW_MS - 2 * 3600_000}
        self.assertIsNone(self.why(agents=[old])["13"])


class Plan(Slots):
    def test_00_09_cleaned_once_per_landing_10_99_one_removal_per_round(self):
        actions = self.plan()
        self.assertEqual([(a["kind"], a["slot"]) for a in actions],
                         [("clean", "03"), ("remove", "13"), ("disk", "-")])
        self.assertEqual(actions[0]["argv"][-4:], ["clean", "03", "--repo", str(self.main)])
        self.assertEqual(actions[1]["argv"][-4:], ["remove", "13", "--repo", str(self.main)])
        log = [{"at": NOW.isoformat(), "key": a["key"]} for a in actions]
        self.assertEqual(self.plan(log=log), [])
        git(self.base / "03", "commit", "-q", "--allow-empty", "-m", "landed")
        git(self.base / "03", "push", "-q", "origin", "HEAD:main")
        git(self.base / "03", "fetch", "-q")
        self.assertEqual([(a["kind"], a["slot"]) for a in self.plan(log=log)], [("clean", "03")])

    def test_a_failed_run_wakes_the_tollman_a_skip_does_not(self):
        remove = next(a for a in self.plan() if a["kind"] == "remove")
        for exit_code, wakes in ((0, []), (1, ["failed"])):
            out = {}
            with mock.patch.object(tick, "sh", return_value=(exit_code, "x")):
                tick.execute(dict(remove), str(self.slot), str(self.main), out)
            self.assertEqual([a["kind"] for a in out.get("wake", [])], wakes)

    def test_disk_is_reported_every_6_hours_a_notice_under_100_gb(self):
        disk = [a for a in self.plan() if a["duty"] == "prune" and a["kind"] in ("disk", "low-disk")]
        self.assertEqual([a["do"] for a in disk], ["record"])
        self.assertIn("free disk 400 GB; biggest worktrees: 03 12 GB, 13 3 GB", disk[0]["text"])
        low = [a["kind"] for a in self.plan(info={"free_gb": 80.0, "biggest": []})]
        self.assertIn("low-disk", low)
        later = [{"at": (NOW - dt.timedelta(hours=1)).isoformat(), "key": "prune:disk:2026-10-03T09"}]
        with mock.patch.object(prune, "disk") as du:
            ctx = {"main": str(self.main), "now": NOW, "log": later}
            self.assertEqual(prune.disk_actions(str(self.main), ctx, None), [])
            du.assert_not_called()

    def test_the_sizes_are_measured_in_the_background_and_reported_the_round_after(self):
        # plan 0011: du over every worktree takes minutes; a round never waits for it.
        ctx = {"main": str(self.main), "now": NOW, "log": [], "dry": False}
        with mock.patch.object(prune, "measured", return_value=None), \
                mock.patch.object(prune, "measure_later") as later:
            self.assertEqual(prune.disk_actions(str(self.main), ctx, None), [])
            later.assert_called_once_with(str(self.main))
            later.reset_mock()
            self.assertEqual(prune.disk_actions(str(self.main), {**ctx, "dry": True}, None), [])
            later.assert_not_called()
        state = prune.state(str(self.main))
        with mock.patch.object(prune, "disk", return_value=INFO):
            (state / prune.SIZES_LOCK).write_text("1")
            prune.measure(str(self.main))
        self.assertFalse((state / prune.SIZES_LOCK).exists())
        self.assertEqual(prune.measured(str(self.main), dt.datetime.now())["free_gb"], INFO["free_gb"])
        self.assertIsNone(prune.measured(str(self.main), dt.datetime.now() + dt.timedelta(hours=7)))
        with mock.patch.object(prune, "measured", return_value=INFO):
            self.assertEqual([a["kind"] for a in prune.disk_actions(str(self.main), ctx, None)], ["disk"])
        popen = mock.Mock()
        (state / prune.SIZES_LOCK).write_text("1")
        self.assertFalse(prune.measure_later(str(self.main), popen))  # one at a time
        (state / prune.SIZES_LOCK).unlink()
        self.assertTrue(prune.measure_later(str(self.main), popen))
        self.assertEqual(popen.call_args.args[0][-3:], ["sizes", "--repo", str(self.main)])

    def test_a_dry_round_of_the_tollman_plans_the_prune_actions(self):
        field = self.tmp / ".hal/git/worktree/hal2/tollman-hal2"
        git(self.main, "worktree", "add", "-q", "-b", "tollman-hal2", str(field))
        (field / tollman.WIRING.role_file).parent.mkdir(parents=True)
        (field / tollman.WIRING.role_file).write_text(ROLE)
        git(field, "add", ".")
        git(field, "commit", "-qm", "prune")
        with mock.patch.object(prune, "measured", return_value=INFO), \
                mock.patch.object(prune_proof, "build_running", return_value=False):
            r = tick.run(str(field), True, tollman.HANDLERS, NOW, wiring=tollman.WIRING)
        self.assertEqual([(a["kind"], a["slot"]) for a in r["planned"] if a["duty"] == "prune"],
                         [("clean", "03"), ("remove", "13"), ("disk", "-"), ("ran", "-")])
        self.assertTrue((self.base / "13").exists())


class Marked(MarkedSlots):
    def test_a_marked_30_99_slot_is_free_once_its_work_is_in_the_leads_branch(self):
        why = self.why()
        self.assertIsNone(why["31"])
        self.assertIsNone(why["33"])
        self.assertIn("HEAD: 1 commit(s) not in origin/02", why["32"])

    def test_a_branch_or_side_branch_the_lead_lacks_or_a_change_keeps_it(self):
        git(self.base / "31", "branch", "31-x")
        git(self.base / "31", "switch", "-q", "31-x")
        git(self.base / "31", "commit", "-q", "--allow-empty", "-m", "side")
        git(self.base / "31", "switch", "-q", "31")
        self.assertIn("31-x: 1 commit(s) not in origin/02", self.why()["31"])
        (self.base / "33/new.txt").write_text("x")
        self.assertIn("uncommitted", self.why()["33"])
        git(self.base / "32", "reset", "-q", "--hard", "origin/02")  # HEAD in origin/02, origin/32 not
        self.assertIn("origin/32: 1 commit(s) not in origin/02", self.why()["32"])

    def test_a_session_active_or_a_lead_written_in_the_last_hour_keeps_it(self):
        self.assertIn("active in the last 60 min", self.why(agents=[self.agent("31", 40)])["31"])
        self.assertIsNone(self.why(agents=[self.agent("31", 61)])["31"])
        self.assertIsNone(self.why(agents=[self.agent("13", 40)])["13"], "unmarked 10-99: 30 min, unchanged")
        busy = {**self.agent("31", 120), "state": "working"}
        self.assertIn("working", self.why(agents=[busy])["31"])
        self.mark("31", age=10 * 60)  # the foreman's `assign` reused it
        self.assertIn("plans/LEAD was written in the last 60 min", self.why()["31"])
        self.assertIn("ticket", self.why({"waiting": {"33"}})["33"])
        self.assertIn("build", self.why(build=lambda path: path.endswith("33"))["33"])

    def test_a_marked_slot_below_30_or_a_bad_marker_or_a_missing_lead_branch_is_never_pruned(self):
        why = self.why()
        self.assertIn("below 30", why["12"])
        self.mark("33", lead="99")
        self.assertIn("origin/99 does not exist", self.why()["33"])
        (self.base / "33/plans/LEAD").write_text("nonsense\n")
        self.assertIn("plans/LEAD is not", self.why()["33"])
        with mock.patch.object(prune.prune_act, "live", return_value=({}, [])):
            self.assertIn("never pruned", prune.prune_act.act_on(str(self.main), "12", "remove", True)[1])

    def test_unmarked_slots_are_unchanged(self):
        why = self.why()
        self.assertEqual([s for s in ("03", "13", "14") if why[s] is None], ["03", "13", "14"])
        self.assertIn("1 commit(s) not on origin/main", why["06"])
        self.assertIn("7 commit(s) not on origin/main", why["02"], "the lead's own slot, unmarked")

    def test_the_round_plans_its_removal_with_the_subservant_text(self):
        found = [w for w in prune_proof.scan(str(self.main), {}, [], NOW_MS, lambda path: False) if w["slot"] == "31"]
        actions = prune.plan({}, {"main": str(self.main), "now": NOW, "log": []}, found, INFO, {})
        remove = next(a for a in actions if a["kind"] == "remove")
        self.assertEqual(remove["argv"][-4:], ["remove", "31", "--repo", str(self.main)])
        self.assertIn("servant worktree 31 (its work is in origin/02)", remove["text"])



if __name__ == "__main__":
    unittest.main()
