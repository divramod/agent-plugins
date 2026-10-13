import contextlib
import datetime as dt
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_link as fl
import state
import state_sources as src


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

PLAN = """# Plan 0042: the answer

| # | Step | Done when | Status |
|---|---|---|---|
| 1 | one | x | done (`abc1234`) |
| 2 | two | x | next |
| 3 | three | x | |
"""
REAL = {name: getattr(src, name) for name in ("agents", "queue", "open_runs")}  # before setUp mocks them
KEYS = {"wt", "is_main", "path", "branch", "plan", "plan_number", "plan_name", "steps_done", "steps_total", "agent",
        "agent_state", "own", "foreman", "last_commit_age", "uncommitted", "ahead", "queue", "ci", "waits", "cells"}


def now_iso(minutes_ago: int = 0) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes_ago)).isoformat()


class Fixture(unittest.TestCase):
    """A main checkout `proj` with an origin, slots 02, 10, 1 and farmer-x beside it (not under ~/.hal), a dot
    checkout `.deliver` and a prunable `gone`; the outside tools are mocked."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        origin, self.main, self.wt = self.tmp / "proj.git", self.tmp / "proj", self.tmp / "wt"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(origin))
        git(self.tmp, "clone", "-q", str(origin), str(self.main))
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            git(self.main, "config", k, v)
        (self.main / "README").write_text("x")
        git(self.main, "add", ".")
        git(self.main, "commit", "-qm", "init")
        git(self.main, "push", "-q", "origin", "main")
        git(self.main, "remote", "set-head", "origin", "main")
        for name in ("10", "02", "1", "farmer-x", ".deliver", "gone"):
            git(self.main, "worktree", "add", "-q", "-b", name.lstrip("."), str(self.wt / name))
        shutil.rmtree(self.wt / "gone")  # prunable
        self.plan_dir = self.wt / "02/plans/0042-the-answer"
        self.plan_dir.mkdir(parents=True)
        (self.plan_dir / "plan.md").write_text(PLAN)
        (self.wt / "02/plans/CURRENT_PLAN").write_text("0042-the-answer\n")
        (self.wt / "10/plans").mkdir()
        (self.wt / "10/plans/CURRENT_PLAN").write_text("my-shots/3/fix-the-thing\n")
        (self.wt / "1/plans").mkdir()
        (self.wt / "1/plans/CURRENT_PLAN").write_text("")
        self.data = self.tmp / "state"
        self.mock(fl.roles, "OVERRIDE", self.data)
        self.set_tools()

    def mock(self, obj, name, value):
        p = mock.patch.object(obj, name, value)
        p.start()
        self.addCleanup(p.stop)

    def set_tools(self, agents=None, queue=None, runs=None):
        for name, value in (("agents", agents), ("queue", queue), ("open_runs", runs)):
            self.mock(src, name, lambda *a, _v=value: _v)

    def rows(self) -> dict:
        return {r["wt"]: r for r in state.collect(str(self.main))["rows"]}

    def write_log(self, *entries: dict) -> None:
        d = self.data / "proj"
        d.mkdir(parents=True, exist_ok=True)
        (d / "log.jsonl").write_text("".join(json.dumps(e) + "\n" for e in entries))


class Slots(Fixture):
    def test_rows_by_number_then_names_then_main_last(self):
        order = [r["wt"] for r in state.collect(str(self.main))["rows"]]
        self.assertEqual(order, ["1", "02", "10", "farmer-x", "main"])

    def test_works_from_a_slot_too(self):
        out = state.collect(str(self.wt / "02"))
        self.assertEqual(out["repo"], os.path.realpath(self.main))
        self.assertEqual(len(out["rows"]), 5)

    def test_json_keys(self):
        out = state.collect(str(self.main))
        self.assertEqual(set(out), {"repo", "default", "head", "head_age", "head_subject", "queue", "runs", "rows"})
        self.assertEqual(out["default"], "main")
        self.assertEqual(len(out["head"]), 8)
        for r in out["rows"]:
            self.assertEqual(set(r), KEYS)
        self.assertTrue(self.rows()["main"]["is_main"])

    def test_cli_prints_the_json(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(state.main(["--repo", str(self.main), "--json"]), 0)
        self.assertEqual([r["wt"] for r in json.loads(buf.getvalue())["rows"]][-1], "main")

    def test_cli_prints_the_table_without_json(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), mock.patch.object(os, "getcwd", return_value=str(self.main)):
            self.assertEqual(state.main(["--repo", str(self.main)]), 0)
        lines = buf.getvalue().rstrip("\n").split("\n")
        self.assertEqual(lines[0], "| WT | Plan | Steps | State | Waits for |")
        self.assertTrue(lines[-3].startswith("| **main** |") and lines[-2] == "")
        self.assertTrue(lines[-1].startswith("main: "))


class Plans(Fixture):
    def test_a_plan_gives_number_name_and_steps(self):
        r = self.rows()["02"]
        self.assertEqual((r["plan"], r["plan_number"], r["plan_name"]), ("0042-the-answer", "0042", "the-answer"))
        self.assertEqual((r["steps_done"], r["steps_total"]), (1, 3))

    def test_a_path_in_current_plan_names_its_plan(self):
        root = self.rows()["02"]["path"]
        for text in ("plans/0042-the-answer", "plans/0042-the-answer/", "plans/0042-the-answer/plan.md"):
            r = src.plan_of(root, text)
            self.assertEqual((r["plan_number"], r["plan_name"], r["steps_done"], r["steps_total"]), ("0042", "the-answer", 1, 3))

    def test_a_shot_name_stays_as_it_stands(self):
        r = self.rows()["10"]
        self.assertEqual(r["plan"], "my-shots/3/fix-the-thing")
        self.assertEqual((r["plan_number"], r["plan_name"], r["steps_done"], r["steps_total"]), (None,) * 4)

    def test_an_empty_or_missing_current_plan(self):
        for wt in ("1", "farmer-x"):
            r = self.rows()[wt]
            self.assertEqual((r["plan"], r["plan_number"], r["steps_total"]), ("", None, None))

    def test_a_plan_number_without_its_folder_has_no_steps(self):
        (self.wt / "1/plans/CURRENT_PLAN").write_text("0099-ghost")
        r = self.rows()["1"]
        self.assertEqual((r["plan"], r["plan_number"], r["steps_total"]), ("0099-ghost", None, None))

    def test_a_missing_plan_skill_leaves_the_steps_unknown(self):
        with mock.patch.object(src, "steps", return_value=(None, None)):
            r = self.rows()["02"]
        self.assertEqual((r["plan_number"], r["steps_done"], r["steps_total"]), ("0042", None, None))

    def test_a_failing_or_erroring_parser_leaves_the_steps_unknown(self):
        src.steps(self.wt / "02", self.plan_dir / "plan.md")  # loads the plan skill's module
        import plan
        for result in ({"slug": "x", "problems": ["no step table"], "steps": []}, RuntimeError("boom")):
            kw = {"side_effect": result} if isinstance(result, Exception) else {"return_value": result}
            with mock.patch.object(plan, "describe_safe", **kw):
                r = self.rows()["02"]
            self.assertEqual((r["plan_number"], r["steps_done"], r["steps_total"]), ("0042", None, None))


class GitFacts(Fixture):
    def test_age_uncommitted_and_commits_ahead(self):
        (self.wt / "02/new.txt").write_text("x")
        (self.wt / "02/new2.txt").write_text("x")
        (self.wt / "10/f").write_text("x")
        git(self.wt / "10", "add", "f")
        git(self.wt / "10", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "work")
        rows = self.rows()
        self.assertEqual(rows["10"]["ahead"], 1)
        self.assertEqual(rows["1"]["ahead"], 0)
        self.assertEqual(rows["1"]["uncommitted"], 1)  # its plans/CURRENT_PLAN
        self.assertGreaterEqual(rows["02"]["uncommitted"], 3)
        self.assertLess(rows["10"]["last_commit_age"], 60)

    def test_the_main_checkout_counts_what_is_not_pushed(self):
        (self.main / "g").write_text("x")
        git(self.main, "add", "g")
        git(self.main, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "local")
        r = self.rows()["main"]
        self.assertEqual((r["branch"], r["ahead"]), ("main", 1))


class Tools(Fixture):
    def test_agents_busy_idle_none_and_unknown(self):
        real = os.path.realpath
        by = {real(self.wt / "02"): {"state": "working"}, real(self.wt / "10"): {"state": "done"}}
        self.mock(src, "agents", lambda: by)
        rows = self.rows()
        self.assertEqual((rows["02"]["agent"], rows["02"]["agent_state"]), ("busy", "working"))
        self.assertEqual((rows["10"]["agent"], rows["10"]["agent_state"]), ("idle", "done"))
        self.assertEqual((rows["1"]["agent"], rows["1"]["agent_state"]), ("none", None))
        self.mock(src, "agents", lambda: None)
        self.assertEqual((self.rows()["02"]["agent"], self.rows()["02"]["agent_state"]), (None, None))

    def test_queue_places_and_ci_runs_by_branch(self):
        real = os.path.realpath
        queue = [{"slot": "02", "worktree": real(self.wt / "02"), "position": 0, "holding": True, "state": "held"},
                 {"slot": "10", "worktree": real(self.wt / "10"), "position": 1, "holding": False, "state": "waiting"}]
        runs = [{"workflow": "merge-to-main", "status": "in_progress", "branch": "land/02", "sha": "a", "url": "u1"},
                {"workflow": "check", "status": "queued", "branch": "10", "sha": "b", "url": "u2"},
                {"workflow": "main run", "status": "queued", "branch": "main", "sha": "c", "url": "u3"},
                {"workflow": "other", "status": "queued", "branch": "55", "sha": "d", "url": "u4"}]
        self.set_tools(queue=queue, runs=runs)
        rows = self.rows()
        self.assertEqual(rows["02"]["queue"], {"holds": True, "position": 0, "state": "held"})
        self.assertEqual(rows["10"]["queue"]["position"], 1)
        self.assertIsNone(rows["1"]["queue"])
        self.assertEqual([c["workflow"] for c in rows["02"]["ci"]], ["merge-to-main"])
        self.assertEqual([c["workflow"] for c in rows["10"]["ci"]], ["check"])
        self.assertEqual([c["workflow"] for c in rows["main"]["ci"]], ["main run"])
        self.assertEqual(rows["1"]["ci"], [])
        self.assertEqual([w["kind"] for w in rows["02"]["waits"]], ["queue", "ci"])
        self.assertEqual(rows["02"]["waits"][0], {"kind": "queue", "holds": True, "position": 0})

    def test_every_tool_missing_failing_or_slow_leaves_facts_unknown(self):
        self.assertIsNone(src.tool(["definitely-not-a-tool-xyz"]))
        self.assertIsNone(src.tool(["false"]))
        self.assertIsNone(src.tool(["sleep", "5"], timeout=0.2))
        self.assertIsNone(src.tool_json(["echo", "not json"]))
        real = src.tool
        self.mock(src, "tool", lambda args, cwd=None, timeout=None: real(args, cwd, timeout) if args[0] == "git" else None)
        self.assertIsNone(REAL["agents"]())  # the real sources, over the failing tool
        self.assertIsNone(REAL["queue"](str(self.main)))
        self.assertIsNone(REAL["open_runs"](str(self.main)))

    def test_collect_survives_failing_tools(self):
        real = src.tool
        self.mock(src, "tool", lambda args, cwd=None, timeout=None: real(args, cwd, timeout) if args[0] == "git" else None)
        out = state.collect(str(self.main))
        self.assertEqual((out["queue"], out["runs"]), (None, None))
        r = {x["wt"]: x for x in out["rows"]}["02"]
        self.assertEqual((r["agent"], r["queue"], r["ci"], r["waits"]), (None, None, [], []))
        self.assertEqual(r["steps_total"], 3)  # git and files still known


class Log(Fixture):
    def test_open_asks_unacked_instructions_and_open_questions(self):
        (self.plan_dir / "questions.md").write_text(
            "# Questions\n\n## Q1 · 2026-10-13 · agent · answered 2026-10-13\n\n**Q:** x\n\n"
            "## Q31 · 2026-10-13 · agent · open\n\n**Q:** y\n")
        self.write_log(
            {"at": now_iso(30), "kind": "ask", "slot": "10", "what": "?"},
            {"at": now_iso(30), "kind": "ask-ack", "slot": "02", "id": "02-1", "text": "go on"},
            {"at": now_iso(30), "kind": "ask-ack", "slot": "1", "id": "1-1", "text": "do"},
            {"at": now_iso(20), "kind": "ack", "slot": "1", "id": "1-1", "what": "started"},
            {"at": now_iso(24 * 60), "kind": "ask-ack", "slot": "farmer-x", "id": "fx-1", "text": "old"})
        rows = self.rows()
        self.assertEqual([w["kind"] for w in rows["10"]["waits"]], ["ask"])
        self.assertEqual(rows["02"]["waits"], [{"kind": "unacked", "ids": ["02-1"]},
                                               {"kind": "questions", "open": ["Q31"]}])
        self.assertEqual(rows["1"]["waits"], [])  # acked
        self.assertEqual(rows["farmer-x"]["waits"], [])  # a day old: stale

    def test_an_answered_ask_is_closed(self):
        self.write_log({"at": now_iso(30), "kind": "ask", "slot": "10"}, {"at": now_iso(5), "kind": "answered", "slot": "10"})
        self.assertEqual(self.rows()["10"]["waits"], [])

    def test_a_broken_log_line_is_skipped(self):
        d = self.data / "proj"
        d.mkdir(parents=True)
        (d / "log.jsonl").write_text('not json\n{"kind": "ask", "slot": "10"}\n')
        self.assertEqual(self.rows()["10"]["waits"], [])

    def test_the_call_writes_nothing(self):
        self.assertFalse(self.data.exists())
        self.rows()
        self.assertFalse(self.data.exists())  # roles.state_dir would have created it
        self.assertIsNone(src.farmer_log(str(self.main)))
        before = self.mtimes()
        self.rows()
        self.assertEqual(before, self.mtimes())

    def mtimes(self) -> dict:
        """The checkout's own entries: `.git` is git's, a read-only command may touch the folder (a Linux runner did)."""
        return {p: p.stat().st_mtime for p in self.main.glob("*") if p.name != ".git"}


if __name__ == "__main__":
    unittest.main()


class Marks(Fixture):
    def lead(self, slot: str, text: str) -> None:
        (self.wt / slot / "plans").mkdir(exist_ok=True)
        (self.wt / slot / "plans/LEAD").write_text(text)

    def test_the_own_row_is_bold_and_only_it(self):
        out = state.collect(str(self.main), str(self.wt / "02"))
        self.assertEqual({r["wt"]: r["own"] for r in out["rows"]},
                         {"1": False, "02": True, "10": False, "farmer-x": False, "main": False})
        self.assertEqual({r["wt"]: r["cells"][0] for r in out["rows"]}["02"], "**02**")
        self.assertEqual({r["wt"]: r["cells"][0] for r in out["rows"]}["10"], "10")

    def test_another_repository_marks_no_row(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        git(elsewhere, "init", "-q")
        self.assertFalse(any(r["own"] for r in state.collect(str(self.main), str(elsewhere))["rows"]))
        self.assertFalse(any(r["cells"][0].startswith("**") for r in state.collect(str(self.main), str(elsewhere))["rows"]))

    def test_servants_stand_under_their_foreman_by_number(self):
        self.lead("10", "02 0042-the-answer 3\n")
        self.lead("1", "02 0042-the-answer 2\n")
        out = state.collect(str(self.main), str(self.main))
        self.assertEqual([r["wt"] for r in out["rows"]], ["02", "1", "10", "farmer-x", "main"])
        self.assertEqual([r["cells"][0] for r in out["rows"]], ["02", "↳ 1", "↳ 10", "farmer-x", "**main**"])
        self.assertEqual({r["wt"]: r["foreman"] for r in out["rows"]}, {"02": None, "1": "02", "10": "02", "farmer-x": None, "main": None})

    def test_a_marker_naming_no_slot_of_the_table_keeps_the_row_in_place(self):
        self.lead("10", "77 0042-the-answer 3\n")
        out = state.collect(str(self.main))
        self.assertEqual([r["wt"] for r in out["rows"]], ["1", "02", "10", "farmer-x", "main"])
        self.assertEqual(out["rows"][2]["cells"][0], "10")

    def test_a_broken_marker_names_no_foreman(self):
        self.lead("10", "nonsense\n")
        self.assertIsNone(self.rows()["10"]["foreman"])


class WithoutTheSiblingSkills(Fixture):
    def test_no_farmer_skill_leaves_its_facts_out(self):
        self.write_log({"at": now_iso(), "kind": "ask", "slot": "02", "what": "x"})
        with mock.patch.object(fl, "FARMER", self.tmp / "nope"), mock.patch.object(fl, "mtm_scan", None), \
                mock.patch.object(fl, "acks", None), mock.patch.object(fl, "logstate", None), \
                mock.patch.object(fl, "roles", None), mock.patch.object(fl, "lead_marker", None):
            rows = {r["wt"]: r for r in state.collect(str(self.main))["rows"]}
        self.assertEqual(list(rows), ["1", "02", "10", "farmer-x", "main"])
        self.assertEqual(rows["02"]["waits"], [])
        self.assertEqual((rows["02"]["steps_done"], rows["02"]["steps_total"]), (1, 3))

    def test_no_plan_skill_leaves_the_steps_out(self):
        with mock.patch.object(src, "__file__", str(self.tmp / "a/b/state_sources.py")):
            r = src.plan_of(self.wt / "02", "0042-the-answer")
        self.assertEqual((r["plan_number"], r["steps_done"], r["steps_total"]), ("0042", None, None))
