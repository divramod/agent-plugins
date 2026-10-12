import contextlib
import datetime as dt
import io
import os
import subprocess
import unittest
from unittest import mock

import farmer
import prune
import tick
from test_farmer import NOW, Repo, git

ROLE = """---
duties:
  prune: "*/15 * * * *"
notify: every-round
---

# x
"""
NOW_MS = NOW.timestamp() * 1000
INFO = {"free_gb": 400.0, "biggest": [(12.0, "03"), (3.0, "13")]}


class Slots(Repo):
    """The main checkout with landed slots 03, 13, 14 and others holding work, plus names prune never touches."""

    def setUp(self):
        super().setUp()
        self.base = self.tmp / ".hal/git/worktree/hal2"
        for name in ("03", "04", "05", "06", "07", "13", "14", "00-train-wt", "owner"):
            git(self.main, "worktree", "add", "-q", "-b", name, str(self.base / name), "origin/main")
        (self.base / "04/new.txt").write_text("x")
        (self.base / "05/plans").mkdir()
        (self.base / "05/plans/CURRENT_PLAN").write_text("0001-x\n")
        git(self.base / "06", "commit", "-q", "--allow-empty", "-m", "work")
        git(self.base / "07", "branch", "07-ui")
        git(self.base / "07", "switch", "-q", "07-ui")
        git(self.base / "07", "commit", "-q", "--allow-empty", "-m", "side")
        git(self.base / "07", "switch", "-q", "07")

    def why(self, ctx=None, agents=(), build=lambda path: False):
        found = prune.scan(str(self.main), ctx or {}, list(agents), NOW_MS, build)
        return {w["slot"]: w["why"] for w in found}

    def plan(self, ctx=None, log=(), info=INFO):
        found = prune.scan(str(self.main), ctx or {}, [], NOW_MS, lambda path: False)
        c = {"main": str(self.main), "now": NOW, "log": list(log), **(ctx or {})}
        return tick.fresh(prune.plan({}, c, found, info), list(log), NOW)


class Scan(Slots):
    def test_only_numbered_slots_and_each_kind_of_unsaved_work(self):
        why = self.why()
        self.assertEqual(sorted(why), ["03", "04", "05", "06", "07", "13", "14"])
        self.assertEqual([s for s, w in why.items() if w is None], ["03", "13", "14"])
        self.assertIn("uncommitted", why["04"])
        self.assertIn("CURRENT_PLAN names 0001-x", why["05"])
        self.assertIn("1 commit(s) not on origin/main", why["06"])
        self.assertIn("side branch 07-ui", why["07"])

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

    def test_a_failed_run_wakes_the_farmer_a_skip_does_not(self):
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
        state = prune.mtm_scan.state_dir(str(self.main))
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

    def test_a_dry_round_of_the_farmer_plans_the_prune_actions(self):
        (self.slot / tick.ROLE).write_text(ROLE)
        git(self.slot, "commit", "-qam", "prune")
        with mock.patch.object(prune, "measured", return_value=INFO), mock.patch.object(prune, "build_running",
                                                                                    return_value=False):
            r = tick.run(str(self.slot), True, farmer.HANDLERS, NOW)
        self.assertEqual([(a["kind"], a["slot"]) for a in r["planned"] if a["duty"] == "prune"],
                         [("clean", "03"), ("remove", "13"), ("disk", "-"), ("ran", "-")])
        self.assertTrue((self.base / "13").exists())


class Act(Slots):
    def setUp(self):
        super().setUp()
        live = mock.patch.object(prune, "live", return_value=({}, []))
        live.start()
        self.addCleanup(live.stop)

    def test_refused_when_the_slot_holds_work_or_the_range_is_wrong(self):
        self.assertIn("uncommitted", prune.act_on(str(self.main), "04", "clean", True)[1])
        self.assertIn("10-99", prune.act_on(str(self.main), "03", "remove", True)[1])
        self.assertIn("00-09", prune.act_on(str(self.main), "13", "clean", True)[1])
        self.assertIn("no numbered slot", prune.act_on(str(self.main), "42", "remove", True)[1])

    def test_clean_runs_the_cleanup_skill(self):
        (self.main / ".gitignore").write_text("target/\n")
        (self.base / "03/.gitignore").write_text("target/\n")
        git(self.base / "03", "add", ".gitignore")
        git(self.base / "03", "commit", "-qm", "ignore")
        git(self.base / "03", "push", "-q", "origin", "HEAD:main")
        git(self.base / "03", "fetch", "-q")
        (self.base / "03/target").mkdir()
        (self.base / "03/target/x.o").write_text("x")
        code, text = prune.act_on(str(self.main), "03", "clean", False)
        self.assertEqual(code, 0, text)
        self.assertFalse((self.base / "03/target").exists())

    def test_remove_stops_the_idle_session_by_signal_then_removes_with_the_remote_branch(self):
        agent = {"pane_id": "%7", "checkout": str(self.base / "13"), "state": "idle", "since": 0}
        calls = []
        with mock.patch.object(prune, "live", return_value=({}, [agent])), \
                mock.patch.object(prune, "stop", return_value=None) as stop, \
                mock.patch.object(tick, "sh", side_effect=lambda argv, cwd, timeout=900: calls.append((argv, cwd))
                                  or (0, "removed")):
            code, text = prune.act_on(str(self.main), "13", "remove", False)
        self.assertEqual((code, text), (0, "removed"))
        stop.assert_called_once_with(str(self.main), "%7")
        self.assertEqual(calls, [(["hal2-cli-git", "worktree", "remove", "13", "--remote"], str(self.main))])

    def test_a_draft_in_the_prompt_refuses_the_removal(self):
        agent = {"pane_id": "%7", "checkout": str(self.base / "13"), "state": "idle", "since": 0}
        with mock.patch.object(prune, "live", return_value=({}, [agent])), \
                mock.patch.object(prune, "stop", return_value="draft: the input box holds \"x\""), \
                mock.patch.object(tick, "sh") as sh:
            code, text = prune.act_on(str(self.main), "13", "remove", False)
        self.assertEqual(code, 0)
        self.assertIn("skipped remove 13", text)
        self.assertIn("draft", text)
        sh.assert_not_called()

    def test_the_cli_prints_the_dry_run(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(prune.shutil, "which", return_value="/bin/x"):
            self.assertEqual(prune.main(["remove", "13", "--repo", str(self.main), "--dry-run"]), 0)
        self.assertIn("would run hal2-cli-git worktree remove 13 --remote", out.getvalue())
        self.assertEqual(subprocess.run(["git", "worktree", "list"], cwd=self.main, capture_output=True,
                                        text=True).stdout.count("/13 "), 1)


class MarkedSlots(Slots):
    """Skills plan 0013: a lead in slot 02 and its subservants' slots marked plans/LEAD, beside the unmarked ones.
    31 and 33: their step merged into origin/02; 32: a commit origin/02 lacks; 12: a subservant below 30."""

    def setUp(self):
        super().setUp()
        self.lead = self.base / "02"
        git(self.main, "worktree", "add", "-q", "-b", "02", str(self.lead), "origin/main")
        git(self.lead, "commit", "-q", "--allow-empty", "-m", "the lead's plan")
        git(self.lead, "push", "-q", "origin", "02")
        for name in ("31", "32", "33", "12"):
            path = self.base / name
            git(self.main, "worktree", "add", "-q", "-b", name, str(path), "origin/02")
            git(path, "commit", "-q", "--allow-empty", "-m", f"step of {name}")
            git(path, "push", "-q", "-u", "origin", name)
            self.mark(name)
        for name in ("31", "33", "12"):
            git(self.lead, "merge", "-q", "--no-ff", "-m", f"merge {name}", f"origin/{name}")
        git(self.lead, "push", "-q", "origin", "02")

    def mark(self, name, lead="02", age=2 * 3600):
        """plans/LEAD and CURRENT_PLAN as create.py writes them (here not ignored), written `age` seconds before NOW."""
        plans = self.base / name / "plans"
        plans.mkdir(exist_ok=True)
        (plans / "LEAD").write_text(f"{lead} 0013-parallel-plans 4\n")
        (plans / "CURRENT_PLAN").write_text("0013-parallel-plans\n")
        os.utime(plans / "LEAD", (NOW.timestamp() - age,) * 2)

    def agent(self, name, minutes_ago):
        return {"pane_id": f"%{name}", "checkout": str(self.base / name), "state": "idle",
                "since": NOW_MS - minutes_ago * 60_000}


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
        self.mark("31", age=10 * 60)  # the lead's `assign` reused it
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
        with mock.patch.object(prune, "live", return_value=({}, [])):
            self.assertIn("never pruned", prune.act_on(str(self.main), "12", "remove", True)[1])

    def test_unmarked_slots_are_unchanged(self):
        why = self.why()
        self.assertEqual([s for s in ("03", "13", "14") if why[s] is None], ["03", "13", "14"])
        self.assertIn("1 commit(s) not on origin/main", why["06"])
        self.assertIn("7 commit(s) not on origin/main", why["02"], "the lead's own slot, unmarked")

    def test_the_round_plans_its_removal_with_the_subservant_text(self):
        found = [w for w in prune.scan(str(self.main), {}, [], NOW_MS, lambda path: False) if w["slot"] == "31"]
        actions = prune.plan({}, {"main": str(self.main), "now": NOW, "log": []}, found, INFO)
        remove = next(a for a in actions if a["kind"] == "remove")
        self.assertEqual(remove["argv"][-4:], ["remove", "31", "--repo", str(self.main)])
        self.assertIn("subservant slot 31 (its work is in origin/02)", remove["text"])


class ActMarked(MarkedSlots):
    def setUp(self):
        super().setUp()
        live = mock.patch.object(prune, "live", return_value=({}, []))
        live.start()
        self.addCleanup(live.stop)
        self.calls = []

    def sh(self, argv, cwd, timeout=900):
        self.calls.append(argv)
        if argv[0] == "hal2-cli-git":
            return 0, "removed"
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
        return p.returncode, (p.stdout + p.stderr).strip()

    def remote(self, name):
        return subprocess.run(["git", "ls-remote", "origin", f"refs/heads/{name}"], cwd=self.main,
                              capture_output=True, text=True, check=True).stdout.strip()

    def test_remove_forces_the_worktree_then_deletes_origin_nn(self):
        self.assertTrue(self.remote("31"))
        with mock.patch.object(tick, "sh", side_effect=self.sh):
            code, text = prune.act_on(str(self.main), "31", "remove", False)
        self.assertEqual(code, 0, text)
        self.assertEqual(self.calls[0], ["hal2-cli-git", "worktree", "remove", "31", "--force"])
        self.assertEqual(self.calls[1], ["git", "push", "--quiet", "origin", "--delete", "31"])
        self.assertFalse(self.remote("31"))
        self.assertTrue(self.remote("02"))

    def test_remove_fetches_and_checks_again(self):
        other = self.tmp / "other"
        git(self.tmp, "clone", "-q", "-b", "31", str(self.tmp / "hal2.git"), str(other))
        git(other, "-c", "user.name=x", "-c", "user.email=x@x", "commit", "-q", "--allow-empty", "-m", "late")
        git(other, "push", "-q", "origin", "31")
        with mock.patch.object(tick, "sh", side_effect=self.sh):
            code, text = prune.act_on(str(self.main), "31", "remove", False)
        self.assertEqual(code, 0)
        self.assertIn("skipped remove 31: origin/31: 1 commit(s) not in origin/02", text)
        self.assertEqual(self.calls, [])
        self.assertTrue(self.remote("31"))

    def test_kept_when_a_commit_is_not_in_the_leads_branch(self):
        with mock.patch.object(tick, "sh", side_effect=self.sh):
            code, text = prune.act_on(str(self.main), "32", "remove", False)
        self.assertIn("skipped remove 32", text)
        self.assertEqual(self.calls, [])

    def test_the_dry_run_names_both_commands(self):
        code, text = prune.act_on(str(self.main), "31", "remove", True)
        self.assertEqual(code, 0)
        self.assertEqual(text, "would run hal2-cli-git worktree remove 31 --force; then "
                               "git push --quiet origin --delete 31")


if __name__ == "__main__":
    unittest.main()
