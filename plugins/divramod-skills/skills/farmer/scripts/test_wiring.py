"""Hal2 plan 0294, step 4: the round frame takes a role. The farmer's values are what they were, and the frame
run with another role's `roles.Wiring` (`tollman`) uses that role's label, slot, duties, commands and state
folder, never the farmer's. No real timer, session or tmux: launchctl, hal2-cli-agents and hal2-cli-git are fakes."""

import contextlib
import dataclasses
import datetime as dt
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import acks
import due
import farmer
import handoff
import logstate
import mtm_scan
import roles
import tick
import timer
import wake
from test_farmer import NOW, Repo, git

SCRIPTS = Path(__file__).resolve().parent
WM_ROLE = """---
duties:
  trains: "*/15 * * * *"
  yard: "0 * * * *"
notify: every-round
---

# the tollman
"""
# Without `mtm` and `trains` since step 5: the merge-to-main boss and the trains are the tollman's; without `prune`
# since plan 0360 step 7 (D30, D67): the prune duty is the tollman's after-the-barn duty.
FARMER_DUTIES = ("lead", "ci", "prs", "sync", "watch", "autoclear")
FARMER_SUBSKILLS = {"lead": "development-lead", "ci": "ci", "watch": "sanity-watch", "autoclear": "fix-autoclear"}
SNAP = {"now": NOW.timestamp(), "queue": [], "findings": [], "landings": [], "worktrees": [],
        "load": {"load1": 1.0, "cores": 8}}


def wagon(skill: Path = Path("/skills/tollman")) -> roles.Wiring:
    """The wiring a tollman's CLI would build (step 5 builds the real one)."""
    return roles.Wiring(role="tollman", cli=skill / "scripts/tollman.py", skill=skill,
                        act="/tollman act", handoff="/tollman handoff", duties=("trains", "yard"),
                        subskills={"trains": "wagon-train"})


WAGON = wagon()


class FarmerValues(unittest.TestCase):
    """What was hard-coded before the frame took a role: unchanged, and still under its old names."""

    def test_the_farmer_s_wiring(self):
        f = roles.FARMER
        self.assertEqual((f.role, f.cli, f.skill), ("farmer", SCRIPTS / "farmer.py", SCRIPTS.parent))
        self.assertEqual((f.act, f.handoff), ("/farmer act", "/farmer handoff"))
        self.assertEqual((f.duties, dict(f.subskills), f.delegates), (FARMER_DUTIES, FARMER_SUBSKILLS, True))
        self.assertEqual((f.role_file, f.role_files),
                         ("roles/farmer/ROLE.md", ("roles/farmer/ROLE.md", "roles/farmer/.gitignore")))
        self.assertIs(farmer.WIRING, roles.FARMER)
        self.assertNotIn("duty:prune", farmer.HANDLERS, "the tollman's since plan 0360 step 7")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            f.role = "lord"

    def test_the_old_names_still_hold_the_farmer_s_values(self):
        self.assertEqual(due.DUTIES, FARMER_DUTIES)
        self.assertEqual((wake.ACT, wake.HANDOFF, wake.SKILL), ("/farmer act", "/farmer handoff", SCRIPTS.parent))
        self.assertEqual(wake.SUBSKILLS, FARMER_SUBSKILLS)
        self.assertEqual(timer.FARMER, SCRIPTS / "farmer.py")
        self.assertEqual((tick.ROLE, tick.ROLE_FILES),
                         ("roles/farmer/ROLE.md", ("roles/farmer/ROLE.md", "roles/farmer/.gitignore")))

    def test_the_farmer_s_timer_label_command_and_unit(self):
        self.assertEqual(timer.label("hal2"), "local.farmer.hal2")
        self.assertEqual(timer.argv("/w/farmer-hal2"),
                         [sys.executable, str(SCRIPTS / "farmer.py"), "tick", "--repo", "/w/farmer-hal2"])
        service, unit = timer.systemd("hal2", "/w/farmer-hal2", Path("/s"), "7-59/15 * * * *")
        self.assertIn("Description=farmer tick for hal2\n", service)
        self.assertIn("Description=farmer tick for hal2\n", unit)
        self.assertIn("<key>Label</key><string>local.farmer.hal2</string>",
                      timer.plist("hal2", "/w/farmer-hal2", Path("/s"), "4 * * * *"))

    def test_the_farmer_s_stamp_and_reply(self):
        reply = "Reply `ack 07-1: started|done|refused <why>` by SendMessage to the farmer session."
        self.assertEqual(acks.REPLY.format(id="07-1"), reply)
        self.assertEqual(acks.stamp("go on", "07-1"), f"farmer [07-1]: go on\n{reply}")
        self.assertEqual(acks.stamp("farmer (lead): go on", "07-1"), f"farmer [07-1] (lead): go on\n{reply}")

    def test_the_farmer_s_summary_title_and_own_slot(self):
        self.assertTrue(mtm_scan.render_summary(SNAP, [], [], "quiet").startswith(f"# farmer {NOW:%Y-%m-%d %H:%M}\n"))
        told = [tick.act("lead", "x", "send", s, key=s) for s in ("farmer-hal2", "tollman-hal2")]
        self.assertEqual([a["slot"] for a in tick.fresh(told, [], NOW)], ["tollman-hal2"])


class Timer(unittest.TestCase):
    """The tollman's timer: its own label, its own CLI, its own files; launchctl is a fake."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home, self.state, self.cmds, self.system = self.tmp / "home", self.tmp / "state", [], "Darwin"
        self.state.mkdir()

        def run(cmd):
            self.cmds.append(cmd)
            return 0, ""

        for p in (mock.patch.object(timer.Path, "home", return_value=self.home), mock.patch.object(timer, "run", run),
                  mock.patch.object(timer.platform, "system", lambda: self.system)):
            p.start()
            self.addCleanup(p.stop)

    def test_label_command_and_units_name_the_role(self):
        self.assertEqual(timer.label("hal2", WAGON), "local.tollman.hal2")
        self.assertEqual(timer.argv("/w/wm", WAGON), [sys.executable, "/skills/tollman/scripts/tollman.py",
                                                      "tick", "--repo", "/w/wm"])
        text = timer.plist("hal2", "/w/wm", self.state, "2-59/5 * * * *", WAGON)
        self.assertIn("<key>Label</key><string>local.tollman.hal2</string>", text)
        self.assertIn("<string>/skills/tollman/scripts/tollman.py</string><string>tick</string>", text)
        self.assertNotIn("local.farmer.", text)
        self.assertNotIn(str(timer.FARMER), text)
        service, unit = timer.systemd("hal2", "/w/wm", self.state, "2-59/5 * * * *", WAGON)
        self.assertIn("Description=tollman tick for hal2\n", service)
        self.assertIn("/skills/tollman/scripts/tollman.py tick --repo /w/wm\n", service)
        self.assertIn("Description=tollman tick for hal2\n", unit)

    def test_install_status_and_remove_touch_only_the_role_s_timer(self):
        agents = self.home / "Library/LaunchAgents"
        self.assertEqual(timer.install("hal2", "/w/wm", self.state, "7-59/15 * * * *", True, WAGON)[0][-1][-18:],
                         "local.tollman.hal2")
        self.assertEqual((self.cmds, agents.exists()), ([], False))
        timer.install("hal2", "/w/wm", self.state, "7-59/15 * * * *", wiring=WAGON)
        self.assertEqual([p.name for p in agents.iterdir()], ["local.tollman.hal2.plist"])
        self.assertEqual([c[:2] for c in self.cmds], [["launchctl", "bootout"], ["launchctl", "bootstrap"]])
        self.assertTrue(all("local.tollman.hal2" in c[-1] for c in self.cmds))
        self.assertEqual(json.loads((self.state / "timer.json").read_text()),
                         {"cron": "7-59/15 * * * *", "label": "local.tollman.hal2"})
        status = timer.status("hal2", self.state, WAGON)
        self.assertEqual((status["label"], status["loaded"], [Path(f).name for f in status["files"]]),
                         ("local.tollman.hal2", True, ["local.tollman.hal2.plist"]))
        self.assertEqual(timer.status("hal2", self.state)["files"], [], "the farmer's timer is not this one")
        timer.remove("hal2", self.state, wiring=WAGON)
        self.assertEqual((list(agents.iterdir()), (self.state / "mode").read_text()), ([], "claude\n"))

    def test_the_systemd_files_are_named_by_the_role_too(self):
        self.system = "Linux"
        self.assertEqual([p.name for p in timer.files("hal2", WAGON)],
                         ["local.tollman.hal2.service", "local.tollman.hal2.timer"])
        self.assertEqual(timer.install("hal2", "/w/wm", self.state, "4 * * * *", True, WAGON)[-1][-1],
                         "local.tollman.hal2.timer")
        self.assertEqual(timer.remove("hal2", self.state, True, WAGON)[0][-1], "local.tollman.hal2.timer")


class WagonRepo(Repo):
    """test_farmer's repository with a second role: `roles/tollman/ROLE.md` on main and the tollman's
    slot (a worktree and branch `tollman-hal2`) beside the farmer's."""

    def setUp(self):
        super().setUp()
        self.wm = self.tmp / ".hal/git/worktree/hal2/tollman-hal2"
        self.wm_state = self.data / "hal2" / "tollman"

    def grow(self):
        super().grow()
        role = self.main / WAGON.role_file
        role.parent.mkdir(parents=True)
        role.write_text(WM_ROLE)
        git(self.main, "add", ".")
        git(self.main, "commit", "-qm", "the tollman's role")
        git(self.main, "push", "-q", "origin", "main")
        self.wm = self.tmp / ".hal/git/worktree/hal2/tollman-hal2"
        git(self.main, "worktree", "add", "-q", "-b", "tollman-hal2", str(self.wm))

    def wm_log(self):
        f = self.wm_state / "log.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


class Slot(WagonRepo):
    def test_the_field_check_takes_the_role_s_field_and_refuses_the_farmer_s(self):
        self.assertIsNone(tick.slot_problem(str(self.wm), WAGON))
        refused = tick.slot_problem(str(self.slot), WAGON)
        self.assertIn("not the tollman's worktree tollman-hal2", refused)
        self.assertIn("hal2-cli-git worktree run tollman-hal2 --agent claude", refused)
        self.assertIn("not the tollman's worktree", tick.slot_problem(str(self.main), WAGON))
        self.assertIn("not the farmer's worktree farmer-hal2", tick.slot_problem(str(self.wm)))

    def test_the_role_s_field_holds_only_its_own_role_files(self):
        (self.wm / WAGON.role_file).write_text(WM_ROLE + "\nedited\n")
        self.assertIsNone(tick.slot_problem(str(self.wm), WAGON))
        (self.wm / tick.ROLE).write_text("the farmer's role, edited here\n")
        problem = tick.slot_problem(str(self.wm), WAGON)
        self.assertEqual(problem, "the tollman's worktree holds more than roles/tollman/ROLE.md: "
                                  "roles/farmer/ROLE.md")

    def test_an_unmigrated_slot_names_the_role_s_migration(self):
        old = self.tmp / "old" / "tollman"
        git(self.main, "worktree", "add", "-q", "-b", "tollman", str(old))
        self.assertIn("farmer.py migrate --role tollman --repo", tick.slot_problem(str(old), WAGON))


class Duties(WagonRepo):
    def test_a_role_names_its_own_duties(self):
        items, _, problems = due.schedule(WM_ROLE, WAGON.duties)
        self.assertEqual((items, problems), ({"duty:trains": "*/15 * * * *", "duty:yard": "0 * * * *"}, []))
        self.assertIn("unknown duty 'yard' (known: lead, ci, ", "\n".join(due.schedule(WM_ROLE)[2]))
        self.assertIn("unknown duty 'trains' (known: lead, ci, ", "\n".join(due.schedule(WM_ROLE)[2]),
                      "the trains are the tollman's (step 5)")
        farmers = WM_ROLE.replace("trains:", "ci:").replace("yard:", "lead:")
        self.assertEqual(due.schedule(farmers)[2], [])
        self.assertEqual(due.schedule(farmers, WAGON.duties)[2], ["unknown duty 'ci' (known: trains, yard)",
                                                                  "unknown duty 'lead' (known: trains, yard)"])

    def test_the_due_items_come_from_the_role_s_own_role_file_and_runs(self):
        rows, settings, problems = tick.due_items(str(self.wm), NOW, wiring=WAGON)
        self.assertEqual(([r["name"] for r in rows], settings["notify"], problems),
                         (["duty:trains", "duty:yard"], "every-round", []))
        self.assertEqual([r["name"] for r in tick.due_items(str(self.wm), NOW)[0]], ["duty:lead", "task:probe"])
        due.record_run(str(self.wm), "duty:trains", NOW, WAGON.role)
        self.assertEqual(set(due.last_runs(str(self.wm), WAGON.role)), {"duty:trains"})
        self.assertEqual(due.last_runs(str(self.wm)), {}, "the farmer's runs.jsonl is another file")
        self.assertEqual([r["name"] for r in tick.due_items(str(self.wm), NOW, wiring=WAGON)[0]], ["duty:yard"])
        (self.wm / WAGON.role_file).unlink()
        self.assertEqual(tick.due_items(str(self.wm), NOW, wiring=WAGON)[2],
                         ["no roles/tollman/ROLE.md: nothing is opted in"])

    def test_an_edit_with_a_duty_of_another_role_is_not_committed(self):
        (self.wm / WAGON.role_file).write_text(WM_ROLE.replace("yard:", "lead:"))
        actions, go_on = tick.role_edit(str(self.wm), WAGON)
        self.assertEqual((go_on, actions[0]["kind"]), (False, "role-invalid"))
        self.assertIn("roles/tollman/ROLE.md edit not committed", actions[0]["text"])
        self.assertIn("unknown duty 'lead'", actions[0]["text"])


class State(WagonRepo):
    def test_each_role_has_its_own_state_folder(self):
        self.assertEqual(mtm_scan.state_dir(str(self.main)), self.data / "hal2")
        self.assertEqual(mtm_scan.state_dir(str(self.main), "tollman"), self.wm_state)
        self.assertEqual(roles.state_dir(self.main, self.data, "farmer"), self.data / "hal2")
        with mock.patch.object(mtm_scan, "DATA", None), mock.patch.object(roles.Path, "home", return_value=self.tmp):
            self.assertEqual(mtm_scan.state_dir(str(self.main), "tollman"), self.wm / "roles/tollman")
            self.assertEqual(mtm_scan.state_dir(str(self.main)), self.slot / "roles/farmer")

    def test_the_log_and_the_summaries_follow_the_role(self):
        main = str(self.main)
        mtm_scan.log(main, {"kind": "train", "slot": "07", "what": "formed"}, "tollman")
        self.assertEqual([e["kind"] for e in self.wm_log()], ["train"])
        self.assertEqual([e["kind"] for e in logstate.read_log(main, "tollman")], ["train"])
        self.assertEqual((self.log(), logstate.read_log(main)), ([], []))
        path = mtm_scan.write_summary(main, SNAP, "a train left", role="tollman")
        self.assertTrue(path.is_relative_to(self.wm_state / "summaries"))
        text = path.read_text()
        self.assertTrue(text.startswith(f"# tollman {NOW:%Y-%m-%d %H:%M}\n"))
        self.assertIn("train 07: formed", text)
        self.assertFalse((self.data / "hal2" / "summaries").exists())

    def test_the_snapshot_reads_the_role_s_own_pause(self):
        self.wm_state.mkdir(parents=True)
        (self.wm_state / "paused.json").write_text('{"note": "the tollman paused"}')
        with mock.patch.object(mtm_scan, "run", return_value=""), mock.patch.object(mtm_scan, "worktrees",
                                                                                   return_value=[]):
            self.assertIsNone(mtm_scan.snapshot(str(self.main), 1, fetch=False)["paused"])
            snap = mtm_scan.snapshot(str(self.main), 1, fetch=False, role="tollman")
        self.assertEqual(snap["paused"], {"note": "the tollman paused"})

    def test_the_farmer_s_context_counts_the_tollman_s_pauses(self):
        self.wm_state.mkdir(parents=True)
        at = NOW.isoformat()
        (self.wm_state / "log.jsonl").write_text(json.dumps({"at": at, "key": "pause:L1:07"}) + "\n")
        self.assertEqual(logstate.paused_by_any_boss(str(self.main), NOW), {"07"})
        self.assertEqual(logstate.paused(logstate.read_log(str(self.main)), NOW), set())
        shutil.rmtree(self.wm_state)
        self.assertEqual(logstate.paused_by_any_boss(str(self.main), NOW), set())
        self.assertFalse(self.wm_state.exists())

    def test_a_role_s_own_slot_label(self):
        self.assertTrue(roles.is_role_label("tollman-hal2", "tollman"))
        self.assertTrue(roles.is_role_label("tollman", "tollman"))
        self.assertFalse(roles.is_role_label("farmer-hal2", "tollman"))
        told = [tick.act("trains", "x", "send", s, key=s) for s in ("tollman-hal2", "farmer-hal2")]
        self.assertEqual([a["slot"] for a in tick.fresh(told, [], NOW, "tollman")], ["farmer-hal2"])


class Wake(WagonRepo):
    """The tollman's session is woken with its own commands, from its own wake.json, for its own skill's files."""

    def setUp(self):
        super().setUp()
        self.skill = self.tmp / "skills/tollman"
        for f in ("instructions/trains.md", "instructions/trains.red.md", "subskills/wagon-train/SUBSKILL.md",
                  "SKILL.md"):
            (self.skill / f).parent.mkdir(parents=True, exist_ok=True)
            (self.skill / f).write_text("x")
        self.wiring = wagon(self.skill)
        self.sent, self.agent = [], {"context_percent": 5, "session_id": "a", "state": "idle"}

        def send(pane, text, states=None):
            self.sent.append((pane, text))
            if text == "/clear":
                self.agent = {"context_percent": 0, "session_id": "c", "state": "idle"}

        for p in (mock.patch.object(wake.deliver, "send", send),
                  mock.patch.object(wake.deliver, "agent", lambda pane: dict(self.agent)),
                  mock.patch.object(wake, "farmer_pane", return_value="%8")):
            p.start()
            self.addCleanup(p.stop)
        self.main = str(self.main)

    def over(self, out, minutes=0):
        return wake.hand_over(str(self.wm), self.main, out, NOW + dt.timedelta(minutes=minutes), self.wiring)

    def red(self):
        return tick.act("trains", "red", "wake", "07", text="the train is red")

    def test_the_instructions_are_the_role_s_skill_s(self):
        w = self.wiring
        self.assertEqual(wake.instructions("trains", "red", w), str(self.skill / "instructions/trains.red.md"))
        self.assertEqual(wake.instructions("trains", "formed", w), str(self.skill / "instructions/trains.md"))
        (self.skill / "instructions/trains.md").unlink()
        self.assertEqual(wake.instructions("trains", "formed", w),
                         str(self.skill / "subskills/wagon-train/SUBSKILL.md"))
        self.assertEqual(wake.instructions("mtm", "front", w), str(self.skill / "SKILL.md"),
                         "the farmer's subskill map is not the tollman's")
        self.assertTrue(wake.instructions("lead", "asks").endswith("farmer/instructions/lead.md"))

    def test_the_wake_types_the_role_s_act_command_and_keeps_its_own_file(self):
        r = self.over({"wake": [self.red()]})
        self.assertEqual((r["woken"], self.sent), (True, [("%8", "/tollman act")]))
        self.assertEqual(wake.wake_file(self.main, self.wiring), self.wm_state / "wake.json")
        items = wake.read(self.main, self.wiring)["items"]
        self.assertEqual([(i["kind"], i["instructions"]) for i in items],
                         [("red", str(self.skill / "instructions/trains.red.md"))])
        self.assertEqual((wake.read(self.main)["items"], wake.wake_file(self.main).exists()), ([], False))
        self.assertEqual([(e["kind"], e["slot"], e["what"]) for e in self.wm_log()],
                         [("wake", "tollman", "/tollman act: 1 items")])
        self.assertEqual(self.log(), [])
        self.assertEqual(wake.done(self.main, 1, self.wiring), 0)
        self.assertFalse(wake.wake_file(self.main, self.wiring).exists())

    def test_a_large_context_gets_the_role_s_handoff_command_then_its_act(self):
        self.agent["context_percent"] = wake.CLEAR_AT
        r = self.over({"wake": [self.red()]})
        self.assertEqual((r["woken"], r["why"], self.sent), (False, "handoff asked", [("%8", "/tollman handoff")]))
        self.over({}, 16)
        self.assertEqual([t for _, t in self.sent], ["/tollman handoff", "/clear", "/tollman act"])
        self.assertEqual([e["kind"] for e in self.wm_log()], ["handoff", "handoff-timeout", "wake"])

    def test_without_a_session_the_refusal_names_the_role(self):
        with mock.patch.object(wake, "farmer_pane", return_value=None):
            self.assertEqual(self.over({"wake": [self.red()]})["why"], "no tollman session")
            self.assertEqual(wake.hand_over(str(self.slot), self.main, {"wake": [self.red()]}, NOW)["why"],
                             "no farmer session")

    def test_a_failed_delegation_s_item_carries_the_role(self):
        failed = {"delegations": [{"key": "k", "state": "error", "title": "t"}]}
        self.assertEqual(wake.items(failed, self.wiring)[0]["duty"], "tollman")
        self.assertEqual(wake.items(failed)[0]["duty"], "farmer")


class Round(WagonRepo):
    """A whole round for the tollman: its role file, log, runs and session, and nothing of the farmer's."""

    def setUp(self):
        super().setUp()
        self.sent, self.seen = [], {}
        agents = json.dumps([{"pane_id": "%8", "checkout": str(self.wm), "slot": "tollman-hal2",
                              "state": "idle"}])
        real = tick.sh

        def sh(argv, cwd, timeout=900):
            return (0, json.dumps({"status": "ok"})) if argv[0] == "hal2-cli-git" else real(argv, cwd, timeout)

        for p in (mock.patch.object(tick, "sh", sh), mock.patch.object(mtm_scan, "snapshot", return_value=SNAP),
                  mock.patch.object(tick.deliver, "cli", lambda *a, timeout=30: (0, agents)),
                  mock.patch.object(tick.deliver, "send", lambda pane, text, s=None: self.sent.append((pane, text))),
                  mock.patch.object(tick.delegation, "follow_up", side_effect=AssertionError("the farmer's ledger"))):
            p.start()
            self.addCleanup(p.stop)

    def handlers(self):
        def trains(item, ctx):
            self.seen = ctx
            return [tick.act("trains", "in-the-barn", "send", "07", pane="%7", text="tollman: in the barn"),
                    tick.act("trains", "red", "wake", "09", text="the train is red"),
                    tick.act("trains", "fix", "delegate", "09", text="fix the red train")]
        return {"duty:trains": trains, "duty:yard": lambda item, ctx: []}

    def test_a_round_runs_for_the_role(self):
        (self.wm / WAGON.role_file).write_text(WM_ROLE + "\nthe user's note\n")
        r = tick.run(str(self.wm), False, self.handlers(), NOW, wiring=WAGON)
        self.assertIsNone(r.get("problem"))
        self.assertIs(self.seen["wiring"], WAGON)
        self.assertEqual(self.seen["duties"], {"trains", "yard"})
        self.assertEqual([i["name"] for i in r["due"]], ["duty:trains", "duty:yard"])
        self.assertEqual(r["planned"][0]["text"], "merge-from-main in the tollman's worktree")
        last = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=self.wm, capture_output=True, text=True)
        self.assertEqual(last.stdout.strip(), "chore(roles): apply the user's change to the tollman's role file")
        self.assertEqual(set(due.last_runs(str(self.wm), "tollman")), {"duty:trains", "duty:yard"})
        reply = "Reply `ack 07-1: started|done|refused <why>` by SendMessage to the tollman session."
        self.assertEqual(self.sent, [("%7", f"tollman [07-1]: in the barn\n{reply}"), ("%8", "/tollman act")])
        self.assertEqual([e["kind"] for e in self.wm_log()],
                         ["stay-current", "role-add", "role-commit", "ask-ack", "in-the-barn", "red", "fix", "wake"])
        self.assertTrue(Path(r["summary"]).is_relative_to(self.wm_state / "summaries"))
        self.assertTrue(Path(r["summary"]).read_text().startswith("# tollman "))
        self.assertEqual((self.log(), due.last_runs(str(self.wm))), ([], {}), "nothing of the farmer's is written")
        self.assertEqual(sorted(p.name for p in (self.data / "hal2").iterdir()), ["tollman"])

    def test_a_field_that_carries_is_taken_as_it_is(self):
        # Hal2 plan 0294, D22: while the tollman's train stands its field holds the cars' commits.
        (self.wm / "car.txt").write_text("another field's crop\n")
        (self.wm / WAGON.role_file).write_text(WM_ROLE + "\nthe user's note\n")
        self.assertIn("holds more than", tick.slot_problem(str(self.wm), WAGON))
        asked = []
        carrying = dataclasses.replace(WAGON, carries=lambda top: asked.append(top) or True)
        self.assertIsNone(tick.slot_problem(str(self.wm), carrying))
        self.assertIn("not the tollman's worktree", tick.slot_problem(str(self.slot), carrying), "only its own field")
        r = tick.run(str(self.wm), False, self.handlers(), NOW, wiring=carrying)
        self.assertIsNone(r.get("problem"))
        self.assertEqual([i["name"] for i in r["due"]], ["duty:trains", "duty:yard"], "the duties run")
        kinds = [e["kind"] for e in self.wm_log()]
        self.assertFalse({"stay-current", "role-add", "role-commit"} & set(kinds), kinds)
        self.assertNotEqual(r["planned"][0]["kind"], "stay-current")
        status = subprocess.run(["git", "status", "--porcelain"], cwd=self.wm, capture_output=True, text=True).stdout
        self.assertIn(" M roles/tollman/ROLE.md", status, "the role file edit waits for the train's end")
        self.assertEqual(set(asked), {str(self.wm.resolve())})
        between = dataclasses.replace(WAGON, carries=lambda top: False)
        self.assertIn("holds more than", tick.slot_problem(str(self.wm), between))
        self.assertIsNone(roles.FARMER.carries)

    def test_a_role_that_does_not_delegate_gets_the_delegation_as_a_wake(self):
        r = tick.run(str(self.wm), False, self.handlers(), NOW, wiring=WAGON)
        self.assertNotIn("delegations", r)
        self.assertNotIn("delegate", r)
        self.assertNotIn("delegations", r["timing"])
        self.assertEqual([(a["kind"], a.get("why")) for a in r["wake"]],
                         [("red", None), ("fix", "the tollman places no delegations")])
        self.assertEqual(r["woke"], {"items": 2, "pending": 2, "woken": True})

    def test_a_dry_run_plans_the_role_s_round_and_writes_nothing(self):
        r = tick.run(str(self.wm), True, self.handlers(), NOW, wiring=WAGON)
        self.assertEqual([a["kind"] for a in r["planned"]],
                         ["stay-current", "in-the-barn", "red", "fix", "ran", "ran"])
        self.assertEqual((r["done"], self.sent), ([], []))
        self.assertEqual([i["kind"] for i in r["wake_items"]], ["red"])
        self.assertFalse(self.data.exists() and any(self.data.rglob("*.jsonl")))

    def test_the_farmer_s_round_in_the_same_repository_still_delegates_and_keeps_its_own_state(self):
        with mock.patch.object(tick.delegation, "follow_up", return_value=[]) as follow_up:
            r = tick.run(str(self.slot), False, {}, NOW)
        follow_up.assert_called_once()
        self.assertEqual((r["delegations"], r["planned"][0]["text"]), ([], "merge-from-main in the farmer's worktree"))
        self.assertIn("delegations", r["timing"])
        self.assertTrue(self.log() and not self.wm_state.exists())

    def test_without_the_override_the_role_s_state_is_ignored_in_its_own_field(self):
        patches = [mock.patch.object(m, "DATA", None) for m in (due, mtm_scan)]
        patches.append(mock.patch.object(Path, "home", return_value=self.tmp))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        r = tick.run(str(self.wm), False, self.handlers(), NOW, wiring=WAGON)
        state = self.wm / "roles/tollman"
        self.assertTrue((state / "log.jsonl").exists() and (state / "runs.jsonl").exists())
        self.assertTrue(Path(r["summary"]).is_relative_to(state / "summaries"))
        status = subprocess.run(["git", "status", "--porcelain", "-uall", "--ignored=no"], cwd=self.wm,
                                capture_output=True, text=True).stdout
        self.assertEqual(status, "")
        tracked = subprocess.run(["git", "ls-files", "roles/tollman"], cwd=self.wm, capture_output=True, text=True)
        self.assertEqual(tracked.stdout.split(), ["roles/tollman/.gitignore", "roles/tollman/ROLE.md"])
        self.assertFalse((self.slot / "roles/farmer/log.jsonl").exists())


class Acks(WagonRepo):
    def test_a_role_stamps_with_its_own_name(self):
        reply = "Reply `ack 07-2: started|done|refused <why>` by SendMessage to the tollman session."
        self.assertEqual(acks.stamp("tollman (trains): hitch up", "07-2", "tollman"),
                         f"tollman [07-2] (trains): hitch up\n{reply}")
        self.assertEqual(acks.stamp("farmer: go on", "07-2", "tollman"),
                         f"tollman [07-2]: farmer: go on\n{reply}")
        stamped = acks.stamp("in the barn", "07-2", "tollman")
        self.assertEqual((acks.stamped_id(stamped, "tollman"), acks.stamped_id(stamped)), ("07-2", None))

    def test_a_tick_s_send_is_logged_in_the_role_s_log(self):
        a = tick.act("trains", "in-the-barn", "send", "07", pane="%7", text="in the barn")
        acks.stamp_send(a, str(self.main), "tollman")
        self.assertEqual([(e["kind"], e["id"]) for e in self.wm_log()], [("ask-ack", "07-1")])
        self.assertTrue(a["text"].startswith("tollman [07-1]: in the barn\n"))
        self.assertEqual(self.log(), [])

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = acks.main([*argv, "--repo", str(self.main)])
        return code, out.getvalue()

    def test_the_command_line_takes_the_role(self):
        code, out = self.cli("instruct", "07", "hitch up", "--role", "tollman", "--json")
        self.assertEqual((code, json.loads(out)["id"]), (0, "07-1"))
        self.assertTrue(json.loads(out)["text"].startswith("tollman [07-1]: hitch up\n"))
        self.assertEqual(self.cli("ack", "07-1", "done", "--role", "tollman")[0], 0)
        self.assertEqual([(e["kind"], e["by"]) for e in self.wm_log()],
                         [("ask-ack", "tollman"), ("ack", "tollman")])
        self.assertEqual(json.loads(self.cli("open", "--role", "tollman", "--json")[1]), [])
        self.assertEqual(self.log(), [])
        code, out = self.cli("instruct", "07", "go on")
        self.assertTrue(out.startswith("farmer [07-1]: go on\n"))
        self.assertEqual([(e["kind"], e["by"]) for e in self.log()], [("ask-ack", "farmer")])


class Handoff(WagonRepo):
    def setUp(self):
        super().setUp()
        self.main, self.calls = str(self.main), []

        def cli(*args, timeout=30):
            if args[0] == "list":
                return 0, json.dumps([{"pane_id": "%8", "checkout": str(self.wm), "session_id": "s8"}])
            self.calls.append(args)
            return 0, '{"status": "started", "pane": "%8"}'

        p = mock.patch.object(wake.deliver, "cli", cli)
        p.start()
        self.addCleanup(p.stop)

    def test_the_role_s_handoff_is_in_its_own_folder_and_continues_with_its_own_command(self):
        f = handoff.path(self.main, WAGON)
        self.assertEqual(f, self.wm_state / "handoff.md")
        self.assertIn("# tollman handoff (<repo>", handoff.show(self.main, WAGON))
        self.assertIn("# farmer handoff (<repo>", handoff.show(self.main))
        self.assertEqual(handoff.clear(str(self.wm), self.main, dt.datetime.now(), WAGON)[0], 1, "not written yet")
        f.write_text("# tollman handoff\n")
        now = dt.datetime.now()
        os.utime(f, (now.timestamp(), now.timestamp()))
        code, what = handoff.clear(str(self.wm), self.main, now, WAGON)
        self.assertEqual((code, what), (0, "clear-and-continue started: /clear, then /tollman act"))
        self.assertEqual(self.calls, [("clear-and-continue", "--pane", "%8", "--prompt", "/tollman act",
                                       "--without-plan", "--detach", "--json", "--session", "s8")])
        self.assertEqual([(e["kind"], e["slot"], e["by"]) for e in self.wm_log()],
                         [("handoff-clear", "tollman", "tollman")])
        self.assertEqual(self.log(), [])


if __name__ == "__main__":
    unittest.main()
