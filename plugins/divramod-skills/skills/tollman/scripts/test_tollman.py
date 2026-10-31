"""Hal2 plan 0294, step 5: the tollman's CLI on the farmer skill's frame. Its rounds run in its own field
`tollman-<repo>` with the duties `mtm` and `trains`, write its own state folder and never the farmer's. No real
timer, session, tmux or merge queue: launchctl, hal2-cli-agents and hal2-cli-git are fakes, the queue is data. The
trains themselves (step 6) are test_engine.py's."""
# enforces .adr/tollman.md and .adr/tollman-decides-trains.md

import contextlib
import io
import json
import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame
import board
import due
import farmer
import handoff
import mtm_scan
import role_cli
import roles
import run_triage_wire
import tick
import timer
import tollman
import wake
from test_farmer import NOW, Repo, git

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import repo_root, sibling  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)
SCRIPTS = Path(__file__).resolve().parent
WIRING = tollman.WIRING
ROLE = """---
duties:
  mtm: "*/15 * * * *"
  trains: "*/15 * * * *"
notify: every-round
---

# the tollman
"""
READY = {"at": "2026-10-13T10:00:00Z", "head": "a" * 40, "by": "hal2/09"}


class Wiring(unittest.TestCase):
    def test_the_tollman_s_wiring(self):
        w = WIRING
        self.assertEqual((w.role, w.cli, w.skill), ("tollman", SCRIPTS / "tollman.py", SCRIPTS.parent))
        self.assertEqual((w.act, w.handoff, w.delegates), ("/tollman act", "/tollman handoff", False))
        self.assertEqual((w.duties, dict(w.subskills)),
                         (("mtm", "trains", "checks", "learn", "prune", "mainred", "watch"),
                          {"mtm": "merge-to-main-boss", "trains": "merge-train"}))
        self.assertEqual(w.role_files, ("roles/tollman/ROLE.md", "roles/tollman/.gitignore"))
        self.assertEqual(set(tollman.HANDLERS), {"duty:mtm", "duty:trains", "duty:checks", "duty:learn", "duty:prune",
                                                 "duty:mainred", "duty:watch"}, "no task:* (D22)")
        self.assertEqual(w.min_tick, 1, "the watch ticks every minute (plan 0383 step 4)")
        self.assertEqual(roles.FARMER.min_tick, 5)
        self.assertIs(w.carries, tollman.carries, "D22: the field carries the trains and the barn's own fix (own_fix.carries)")
        self.assertIsNone(roles.FARMER.carries)

    def test_the_duties_moved_with_their_texts_and_the_farmer_lost_them(self):
        for duty, sub in WIRING.subskills.items():
            self.assertEqual(wake.instructions(duty, "any", WIRING), str(SCRIPTS.parent / f"instructions/{duty}.md"))
            self.assertTrue((SCRIPTS.parent / "subskills" / sub / "SUBSKILL.md").is_file(), sub)
            self.assertNotIn(duty, roles.FARMER.duties)
            self.assertNotIn(duty, roles.FARMER.subskills)
            self.assertNotIn(f"duty:{duty}", farmer.HANDLERS)
            self.assertFalse((farmer_frame.SCRIPTS.parent / f"instructions/{duty}.md").exists())
        self.assertFalse(any((farmer_frame.SCRIPTS / f).exists() for f in ("boss.py", "trains.py", "trial.py")))

    def test_the_frame_is_the_farmer_skill_s(self):
        self.assertEqual(farmer_frame.SCRIPTS, sibling("farmer") / "scripts")
        self.assertEqual(Path(tick.__file__).parent, farmer_frame.SCRIPTS)
        self.assertEqual(Path(role_cli.__file__).parent, farmer_frame.SCRIPTS)


class Field(Repo):
    """test_farmer's repository (main `hal2`, the farmer's field) with the tollman's: `roles/tollman/
    ROLE.md` on main and the field `tollman-hal2`. The home is tmp; launchctl is a fake that never runs."""

    def setUp(self):
        super().setUp()
        self.wm = self.tmp / ".hal/git/worktree/hal2/tollman-hal2"
        self.wm_state, self.cmds, self.loaded = self.data / "hal2" / "tollman", [], False

        def launchctl(cmd):
            self.cmds.append(cmd)
            return (0 if self.loaded or cmd[1] != "print" else 113), ""

        self.triages = []  # run_triage_wire's detached children: recorded, never started (no process leaves a test)
        for p in (mock.patch.object(Path, "home", return_value=self.tmp), mock.patch.object(timer, "run", launchctl),
                  mock.patch.object(run_triage_wire, "SPAWN", lambda argv, **kw: self.triages.append(argv)),
                  mock.patch.object(timer.platform, "system", return_value="Darwin"),
                  mock.patch.object(role_cli.shutil, "which", return_value="/bin/x")):
            p.start()
            self.addCleanup(p.stop)

    def grow(self):
        super().grow()
        self.commit(self.main, WIRING.role_file, ROLE, push=True)
        self.wm = self.field("tollman-hal2")

    def commit(self, cwd, name, text, push=False):
        (Path(cwd) / name).parent.mkdir(parents=True, exist_ok=True)
        (Path(cwd) / name).write_text(text)
        git(cwd, "add", ".")
        git(cwd, "commit", "-qm", name)
        if push:
            git(cwd, "push", "-q", "origin", "HEAD")

    def field(self, name):
        path = self.tmp / ".hal/git/worktree/hal2" / name
        git(self.main, "worktree", "add", "-q", "-b", name, str(path))
        return path

    def call(self, *argv, repo=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = tollman.main([*argv, "--repo", str(repo or self.wm)])
        return code, out.getvalue() or err.getvalue()

    def wm_log(self):
        f = self.wm_state / "log.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


class Start(Field):
    def test_start_check_takes_only_the_tollman_s_field(self):
        code, out = self.call("start-check", "--json")
        self.assertEqual((code, json.loads(out)["loop_cron"], json.loads(out)["items"]),
                         (0, "7-59/15 * * * *", ["duty:mtm", "duty:trains"]))
        for other in (self.slot, self.main):
            code, out = self.call("start-check", repo=other)
            self.assertEqual(code, 4, other)
            self.assertIn("not the tollman's worktree tollman-hal2", out)

    def test_a_duty_of_the_farmer_s_is_unknown_here_and_no_role_file_is_nothing_to_run(self):
        self.commit(self.wm, WIRING.role_file, ROLE.replace("trains:", "lead:"))
        code, out = self.call("start-check")
        self.assertEqual((code, out), (1, "- unknown duty 'lead' (known: mtm, trains, checks, learn, prune, mainred, watch)\n"))
        git(self.wm, "rm", "-q", WIRING.role_file)
        code, out = self.call("start-check")
        self.assertEqual(code, 3)
        self.assertIn("roles/tollman/ROLE.md: nothing is opted in", out)

    def test_a_tick_runs_only_in_timer_mode_and_the_mode_is_the_role_s_own(self):
        code, out = self.call("tick")
        self.assertEqual(code, 4)
        self.assertIn("tollman.py: mode is `claude`", out)
        self.assertEqual(self.call("mode", "timer"), (0, "timer\n"))
        self.assertEqual((self.wm_state / "mode").read_text(), "timer\n")
        self.assertEqual(farmer.mode(str(self.slot)), "claude", "the farmer's mode is another file")
        self.assertEqual(self.call("tick", "--all-due")[0], 4)


class Timer(Field):
    def test_the_timer_is_the_tollman_s_own(self):
        plist = self.tmp / "Library/LaunchAgents/local.tollman.hal2.plist"
        code, out = self.call("timer", "install", "--dry-run")
        self.assertEqual((code, self.cmds, plist.exists()), (0, [], False))
        self.assertIn("local.tollman.hal2", out)
        self.assertEqual(self.call("timer", "install"), (0, "install: mode timer\n"))
        self.loaded = True
        text = plist.read_text()
        for part in ("<string>local.tollman.hal2</string>", f"<string>{SCRIPTS / 'tollman.py'}</string>",
                     "<string>tick</string>", f"<string>{self.wm.resolve()}</string>", str(self.wm_state / "tick.log")):
            self.assertIn(part, text, part)
        self.assertEqual([c[:2] for c in self.cmds], [["launchctl", "bootout"], ["launchctl", "bootstrap"]])
        self.assertEqual(timer.installed(self.wm_state),
                         {"cron": "7-59/15 * * * *", "label": "local.tollman.hal2"})
        self.assertFalse((self.tmp / "Library/LaunchAgents/local.farmer.hal2.plist").exists())
        self.assertEqual(farmer.mode(str(self.slot)), "claude")
        status = json.loads(self.call("timer", "status", "--json")[1])
        self.assertEqual((status["label"], status["loaded"], status["mode"]),
                         ("local.tollman.hal2", True, "timer"))
        self.assertEqual(self.call("timer", "remove"), (0, "remove: mode claude\n"))
        self.assertFalse(plist.exists())


class Rounds(Field):
    """Whole rounds with the real handlers: two fields wait at the toll gate with a landing of their own (the queue
    is data), each with a commit the barn lacks. Neither is hitched, so no train forms (step 6: only ready tickets
    ride)."""

    def setUp(self):
        super().setUp()
        self.fields = {n: self.field(n) for n in ("07", "09")}
        for n, path in self.fields.items():
            self.commit(path, f"{n}.txt", n)
        self.queue = [{"slot": n, "position": i, "state": "waiting", "branch": n, "worktree": str(path), "seq": i + 1,
                       "pid": 0} for i, (n, path) in enumerate(self.fields.items())]
        self.typed, real = [], tick.sh

        def answers(args, cwd=None):
            return {"queue": self.queue} if args[:3] == ["hal2-cli-git", "worktree", "queue"] else None

        def sh(argv, cwd, timeout=900):
            return (0, json.dumps({"status": "ok"})) if argv[0] == "hal2-cli-git" else real(argv, cwd, timeout)

        for p in (mock.patch.object(mtm_scan, "run_json", answers), mock.patch.object(tick, "sh", sh),
                  mock.patch.object(tick.deliver, "send", lambda pane, text, s=None: self.typed.append((pane, text)))):
            p.start()
            self.addCleanup(p.stop)

    def planned(self, r, duty):
        return [(a["kind"], a["do"], a["slot"]) for a in r["planned"] if a["duty"] == duty]

    def test_a_dry_tick_plans_the_boss_s_and_the_train_s_work_and_touches_nothing(self):
        code, out = self.call("tick", "--dry-run", "--json")
        r = json.loads(out)
        self.assertEqual((code, [i["name"] for i in r["due"]]), (0, ["duty:mtm", "duty:trains"]))
        self.assertEqual(self.planned(r, "mtm"),
                         [("waiter-gone", "send", "07"), ("waiter-gone", "send", "09"), ("ran", "ran", "-")])
        self.assertEqual(self.planned(r, "trains"), [("ran", "ran", "-")], "a waiter with its own landing never rides")
        gone = next(a for a in r["planned"] if a["kind"] == "waiter-gone")
        self.assertTrue(gone["text"].startswith("tollman (merge-to-main boss): your merge-queue ticket has no "))
        self.assertEqual((self.typed, self.wm_log()), ([], []))
        self.assertEqual([p.name for p in self.wm_state.iterdir() if p.name != "cache"], ["tick.lock"])
        self.assertEqual(self.log(), [], "nothing of the farmer's")

    def test_a_hitched_field_is_no_gone_waiter(self):
        self.queue[1]["ready"] = READY
        r = json.loads(self.call("tick", "--dry-run", "--json")[1])
        self.assertEqual(self.planned(r, "mtm"), [("waiter-gone", "send", "07"), ("ran", "ran", "-")])
        self.assertEqual(self.planned(r, "trains"), [("ran", "ran", "-")], "its head is not known here: it waits")
        self.queue[0]["train"] = {"carrier": "07", "cars": [{"field": "09"}], "at": READY["at"]}
        r = json.loads(self.call("tick", "--dry-run", "--json")[1])
        self.assertEqual(self.planned(r, "mtm"), [("ran", "ran", "-")], "nor is a standing train's ticket")

    def test_a_round_writes_the_tollman_s_folder_and_never_the_farmer_s(self):
        self.call("mode", "timer")
        with mock.patch.object(role_cli.tick, "run", wraps=tick.run) as run:
            code, out = self.call("tick")
        self.assertEqual(code, 0, out)
        self.assertIs(run.call_args.kwargs["wiring"], WIRING)
        self.assertIn("tollman tick (round): 2 due: duty:mtm, duty:trains", out)
        self.assertEqual(self.typed, [], "no session: nothing is typed, the messages wait as relays")
        kinds = [e["kind"] for e in self.wm_log()]
        for kind in ("stay-current", "waiter-gone"):
            self.assertIn(kind, kinds)
        asked = [e["text"].splitlines()[0] for e in self.wm_log() if e["kind"] == "ask-ack"]
        self.assertTrue(all(t.startswith("tollman [0") for t in asked) and len(asked) == 2, asked)
        self.assertEqual({json.loads(x)["name"] for x in (self.wm_state / "runs.jsonl").read_text().splitlines()},
                         {"duty:mtm", "duty:trains"})
        for name in ("last-scan.json", "summaries/latest.md"):
            self.assertTrue((self.wm_state / name).is_file(), name)
        self.assertEqual(sorted(p.name for p in (self.data / "hal2").iterdir()), ["tollman"])
        self.assertEqual(self.log(), [], "the farmer's log is another file")
        self.assertEqual(self.cmds, [], "a round installs no timer")

        status = json.loads(self.call("status", "--json", repo=self.main)[1])
        self.assertEqual((status["role"], status["field"], status["field_exists"], status["mode"]),
                         ("tollman", str(self.wm), True, "timer"))
        self.assertEqual((status["timer"]["label"], status["timer"]["loaded"]), ("local.tollman.hal2", False))
        self.assertTrue(status["last_tick"] and 0 <= status["last_tick_age_s"] < 600, status)
        self.assertEqual(status["pending"], 2)

        code, out = self.call("act")
        self.assertIn("relay  mtm/waiter-gone 07: tollman [07-", out)
        self.assertIn(f"read {SCRIPTS.parent / 'instructions/mtm.md'}", out)
        self.assertTrue(out.endswith("2 items\n"), out)
        self.assertEqual(self.call("act", "--done", "2"), (0, "0 items left\n"))
        self.assertEqual(json.loads(self.call("status", "--json")[1])["pending"], 0)

    def test_the_second_round_tells_nobody_again(self):
        self.call("mode", "timer")
        self.call("tick")
        n = len(self.wm_log())
        with mock.patch.object(tick.due, "is_due", return_value=True):
            code, out = self.call("tick")
        self.assertEqual(code, 0, out)
        self.assertEqual([e["kind"] for e in self.wm_log()[n:]], [],
                         "every key is in the log, and origin did not move: no merge-from-main (plan 0480 02.02)")
        self.assertEqual({json.loads(x)["name"] for x in (self.wm_state / "runs.jsonl").read_text().splitlines()[2:]},
                         {"duty:mtm", "duty:trains"}, "and the runs are recorded: no keyless action was dropped")


class Status(Field):
    def test_a_farm_without_a_tollman_has_no_field_no_timer_and_no_tick(self):
        lonely = self.tmp / "lonely"
        lonely.mkdir()
        git(lonely, "init", "-q", "-b", "main")
        with mock.patch.object(due, "DATA", None):
            s = tollman.status(str(lonely))
            self.assertEqual((s["field_exists"], s["timer"]["loaded"], s["mode"], s["last_tick"], s["last_tick_age_s"],
                              s["pending"]), (False, False, "claude", None, None, 0))
            self.assertEqual(s["field"], str(self.tmp / ".hal/git/worktree/lonely/tollman-lonely"))
            self.assertFalse((self.tmp / ".hal/git/worktree/lonely").exists(), "asking creates nothing")
            here = tollman.status(str(self.main))
            self.assertEqual((here["field"], here["field_exists"], here["last_tick"]), (str(self.wm), True, None))
        code, out = self.call("status", repo=lonely)
        self.assertEqual(code, 0)
        self.assertIn("no field", out)
        self.assertIn("last tick: never; 0 wake items", out)

    def test_the_last_tick_is_the_newest_tick_entry_or_run(self):
        self.wm_state.mkdir(parents=True)
        def at(minutes):
            return (NOW - tollman.dt.timedelta(minutes=minutes)).isoformat(timespec="seconds")

        (self.wm_state / "log.jsonl").write_text(
            json.dumps({"at": at(50), "kind": "stay-current", "by": "tick"}) + "\n"
            + json.dumps({"at": at(5), "kind": "train", "by": "tollman"}) + "\n")
        self.assertEqual(tollman.status(str(self.wm), NOW)["last_tick_age_s"], 50 * 60)
        (self.wm_state / "runs.jsonl").write_text(json.dumps({"at": at(20), "name": "duty:trains"}) + "\n")
        s = tollman.status(str(self.wm), NOW)
        self.assertEqual((s["last_tick"], s["last_tick_age_s"]), (at(20), 20 * 60))

    def test_the_handoff_is_the_role_s_own_file(self):
        code, out = self.call("handoff")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith(f"handoff: {self.wm_state / 'handoff.md'} (missing"), out)
        self.assertIn("# tollman handoff", out)
        self.assertIs(sys.modules["handoff"].__file__.startswith(str(farmer_frame.SCRIPTS)), True)


class SessionEffort(Field):
    """Hal2 plan 0333, D4/D7: the tollman's session runs at effort high (ROLE.md's `session_effort`, default
    high) and every clear-and-continue passes it; the user's rule is in the skill, the template and the record."""

    def setUp(self):
        super().setUp()
        self.calls = []

        def cli(*args, timeout=30):
            if args[0] == "list":
                return 0, json.dumps([{"pane_id": "%9", "checkout": str(self.wm), "session_id": "s1"}])
            self.calls.append(args)
            return 0, '{"status": "started", "pane": "%9"}'

        p = mock.patch.object(wake.deliver, "cli", cli)
        p.start()
        self.addCleanup(p.stop)

    def clear(self, role_text=None):
        if role_text is not None:
            (self.wm / WIRING.role_file).write_text(role_text)
        f = handoff.path(str(self.main), WIRING)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("# tollman handoff\n")
        os.utime(f, None)
        self.calls.clear()
        code, out = self.call("handoff", "--clear")
        self.assertEqual(code, 0, out)
        return self.calls[-1]

    def test_the_default_is_high_and_the_template_names_it(self):
        self.assertEqual(due.SESSION_EFFORT, "high")
        self.assertEqual(due.schedule(ROLE, WIRING.duties)[1]["session_effort"], "high")
        template = (SCRIPTS.parent / "templates" / "ROLE.md").read_text()
        _, settings, problems = due.schedule(template, WIRING.duties)
        self.assertEqual((settings["session_effort"], problems), ("high", []))
        self.assertIn("session_effort: high", template)

    def test_a_named_effort_is_validated(self):
        self.assertEqual(due.schedule(ROLE.replace("notify:", "session_effort: xhigh\nnotify:"))[1]["session_effort"],
                         "xhigh")
        problems = due.schedule(ROLE.replace("notify:", "session_effort: huge\nnotify:"))[2]
        self.assertIn("`session_effort:` is one of low, medium, high, xhigh, max", problems)

    def test_the_restart_passes_the_effort_to_the_clear_and_continue(self):
        self.assertTrue(WIRING.session_effort)
        self.assertFalse(roles.FARMER.session_effort, "the farmer's clear is unchanged")
        self.assertEqual(self.clear(), ("clear-and-continue", "--pane", "%9", "--prompt", "/tollman act",
                                        "--without-plan", "--detach", "--json", "--effort", "high", "--session", "s1"))

    def test_a_role_file_with_another_effort_or_a_bad_one_decides_the_restart(self):
        self.assertIn("xhigh", self.clear(ROLE.replace("notify:", "session_effort: xhigh\nnotify:")))
        bad = self.clear(ROLE.replace("notify:", "session_effort: huge\nnotify:"))
        self.assertEqual(bad[bad.index("--effort") + 1], "high", "an invalid setting never blocks the clear")
        (self.wm / WIRING.role_file).unlink()
        self.assertEqual(handoff.session_effort(str(self.wm), WIRING), "high")

    def test_the_start_command_carries_model_and_effort_in_the_skill(self):
        skill = (SCRIPTS.parent / "SKILL.md").read_text()
        starts = re.findall(r"hal2-cli-git worktree run tollman-<repo> --agent claude[^`]*", skill)
        self.assertTrue(starts)
        self.assertTrue(all(s.endswith("--model opus --effort high") for s in starts), starts)

    def test_the_users_rule_is_in_the_skill_the_instructions_the_template_and_the_record(self):
        # the repository's record (absent in a published copy); it was found at the wrong depth before plan 0360 D20
        record = (repo_root(__file__) or Path("/nonexistent")) / ".adr" / "tollman-decides-trains.md"
        if record.is_file():
            self.assertIn("never asked", record.read_text().lower())
        for name in ("SKILL.md", "instructions/trains.md", "templates/ROLE.md"):
            text = (SCRIPTS.parent / name).read_text()
            self.assertIn("-decides-trains", text, name)
            self.assertIn("never ask", text.lower().replace("never asked", "never ask"), name)


class QuietSkipsTheTick(unittest.TestCase):
    """hal2 plan 0442 D11: while the machine is quiet a tick does nothing, not even the minute's watch."""

    def test_a_tick_while_quiet_is_skipped(self):
        import argparse
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "quiet.json").write_text(json.dumps({"schema": 1, "active": True, "holds": {}}))
            args = argparse.Namespace(repo=tmp, dry_run=False, json=False, all_due=False)
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"HAL2_STATE_DIR": tmp}), \
                    mock.patch.object(tollman.minute, "light", side_effect=AssertionError("minute")), \
                    mock.patch.object(board, "safely", side_effect=AssertionError("board")), \
                    mock.patch.object(role_cli, "run_tick", side_effect=AssertionError("round")), \
                    contextlib.redirect_stdout(out):
                self.assertEqual(tollman.tick(args), 0)
            self.assertIn("the machine is quiet", out.getvalue())


if __name__ == "__main__":
    unittest.main()
