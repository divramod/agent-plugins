"""Hal2 plan 0595 step 11: the farmer's lead round and plan dependencies. A foreman whose open dependency holds its next
step is not nudged as idle; when a dependency reaches its `until` the dependent field is told once, with an ack id. The
replay: plan 0514 pushed in field 38, plan 0543 in field 57 waited for its steps 22-27 and 36. The graph is data (a
stub of `depends_view.read`), the state folder a scratch one: never the real farm, sessions or CLI."""

import datetime as dt
import json
import os
import re
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

import acks
import duties
import depends_view
import lead_depends
import lead_scan
import mtm_scan
import queue_mode
import tick

SKILL = Path(__file__).resolve().parent.parent
NOW = dt.datetime(2026, 11, 3, 14, 0, tzinfo=dt.timezone.utc)
CHECKER = next((str(Path(d) / "hal2-cli-roles") for d in os.environ.get("PATH", "").split(os.pathsep)
                if (Path(d) / "hal2-cli-roles").is_file()), None)

def setUpModule():
    """No test of the scan asks the real `hal2-cli-git worktree paused` (plan 0695 D46: the scan reads the marks)."""
    patch = mock.patch.object(lead_scan.field_pause, "load", return_value={})
    patch.start()
    unittest.addModuleCleanup(patch.stop)



def link(state="pushed", reached=True, **over):
    return {"plan": 514, "slug": "0514-x", "field": "38", "steps": ["22-27", "36"], "needs": ["3"], "until": "pushed",
            "state": state, "reached": reached, **over}


def graph(*links):
    return {543: {"plan": 543, "slug": "0543-agents", "field": "57", "depends_on": list(links), "dependents": []}}


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name)
        for target in (mock.patch.object(mtm_scan, "DATA", self.data),
                       mock.patch.object(lead_depends, "commit_of", lambda main, link: "ab12cd3")):
            target.start()
            self.addCleanup(target.stop)

    def ctx(self, nodes, panes=None, log=()):
        return {"top": "/x/hal2", "main": "/x/hal2", "now": NOW, "log": list(log), "depends": nodes,
                "panes": {"57": "t:57"} if panes is None else panes, "duties": {"lead"}}

    def told(self):
        f = mtm_scan.state_dir("/x/hal2") / lead_depends.FILE
        return [json.loads(line) for line in f.read_text().splitlines()] if f.exists() else []

    def run_record(self, actions):
        run = next(a for a in actions if a["do"] == "run")
        self.assertEqual(run["argv"][2], "record")
        self.assertEqual(lead_depends.main(run["argv"][2:]), 0)


class Told(Base):
    def test_the_replay_38_pushed_tells_57_once(self):
        ctx = self.ctx(graph(link()))
        out = tick.fresh(lead_depends.plan({}, ctx), [], NOW)
        send, run = out
        self.assertEqual((send["do"], send["slot"], send["pane"], send["duty"], send["kind"]),
                         ("send", "57", "t:57", "lead", "depends-reached"))
        self.assertEqual(send["text"].split(": ", 1)[1].split(". ")[0],
                         "plan 0514 is pushed (ab12cd3): merge origin/38 and go on with step 22")
        self.assertTrue(send["text"].startswith(lead_depends.LEAD + ": "))
        self.assertEqual((run["do"], run["after"]), ("run", send["key"]))
        self.run_record(out)
        entry = self.told()[0]
        self.assertEqual({k: entry[k] for k in ("schema", "key", "plan", "dependent", "slot", "state", "until")},
                         {"schema": 1, "key": "depends:0514:0543:57", "plan": 514, "dependent": 543, "slot": "57",
                          "state": "pushed", "until": "pushed"})
        self.assertEqual(lead_depends.plan({}, self.ctx(graph(link()))), [], "told once, whatever the next ticks see")
        self.assertEqual(lead_depends.plan({}, self.ctx(graph(link("main")))), [], "also when it reaches main later")

    def test_at_the_foreman_limit_the_wake_waits_for_a_free_slot(self):
        busy = [{"slot": s, "state": "working"} for s in ("16", "01", "02")]
        panes = {"57": "t:57", "16": "t:16", "01": "t:01", "02": "t:02"}
        full = {**self.ctx(graph(link()), panes=panes), "settings": {"servant_limit": "3"}, "agent_rows": busy}
        self.assertEqual(lead_depends.plan({}, full), [], "3 of 3 busy: nobody is told")
        self.assertEqual(self.told(), [], "not recorded: told on a later tick")
        free = {**full, "agent_rows": busy[:2]}
        self.assertEqual([a["do"] for a in lead_depends.plan({}, free)], ["send", "run"])
        auto = {**full, "settings": {}}
        self.assertEqual([a["do"] for a in lead_depends.plan({}, auto)], ["send", "run"], "auto: not held back")

    def test_the_send_gets_an_ack_id_like_every_instruction(self):
        out = lead_depends.plan({}, self.ctx(graph(link())))
        send = out[0]
        with mock.patch.object(acks, "stamp_send", wraps=acks.stamp_send) as stamp, \
                mock.patch("deliver.send", return_value=None), mock.patch.object(tick.mtm_scan, "log"):
            tick.execute(send, "/x/farmer-hal2", "/x/hal2", {"done": []}, mock.Mock(role="farmer"))
        stamp.assert_called_once()
        self.assertEqual(send["do"], "send", "typed into the idle session's prompt")

    def test_until_main_waits_for_main_and_says_restock(self):
        open_ = link("pushed", False, until="main")
        self.assertEqual(lead_depends.plan({}, self.ctx(graph(open_))), [])
        out = lead_depends.plan({}, self.ctx(graph(link("main", True, until="main"))))
        self.assertIn("plan 0514 is main (ab12cd3): restock (/mfm) and go on with step 22", out[0]["text"])

    def test_a_whole_plan_dependency_says_your_plan(self):
        out = lead_depends.plan({}, self.ctx(graph(link(steps=[]))))
        self.assertIn("merge origin/38 and go on with your plan", out[0]["text"])

    def test_nothing_unreached_without_a_session_or_without_the_cli(self):
        self.assertEqual(lead_depends.plan({}, self.ctx(graph(link("open", False)))), [])
        self.assertEqual(lead_depends.plan({}, self.ctx(graph(link()), panes={})), [], "no session: told later")
        self.assertEqual(lead_depends.plan({}, self.ctx(None)), [])
        self.assertEqual(lead_depends.plan({}, self.ctx({})), [])
        self.assertEqual(self.told(), [])

    def test_a_missing_cli_changes_nothing_in_the_lead_round(self):
        ctx = {k: v for k, v in self.ctx(None).items() if k != "depends"}
        with mock.patch.object(depends_view, "read", return_value=None) as read:
            out = queue_mode.plan_lead({}, ctx, {"queue": []}, {"needs_help": []})
            again = queue_mode.plan_lead({}, ctx, {"queue": []}, {"needs_help": []})
        self.assertEqual((out, again), ([], []))
        read.assert_called_once_with("/x/hal2")  # one read a round, also when it found nothing

    def test_the_lead_round_carries_it(self):
        out = queue_mode.plan_lead({}, self.ctx(graph(link())), {"queue": []}, {"needs_help": []})
        self.assertEqual([a["kind"] for a in out], ["depends-reached", "depends-told"])

    def test_a_paused_field_is_not_told(self):
        import field_pause
        planned = lead_depends.plan({}, self.ctx(graph(link())))
        skipped = field_pause.skip(planned, {"57": {"since": "x"}})
        self.assertNotIn("send", [a["do"] for a in skipped])


NEED = {"kind": "idle-in-plan", "why": "idle for 40 min inside plan 0543", "slot": "57", "pane": "t:57",
        "session": "s57", "since": 1000, "plan": "0543 · agents view", "plan_number": 543, "next_step": "22",
        "said": "Step 21 done.\n\nNext I'll run step 22."}


class Blocked(Base):
    def lead(self, nodes, **over):
        ctx = self.ctx(nodes)
        return duties.plan_lead({}, ctx, {"needs_help": [{**NEED, **over}]}), ctx

    def test_a_foreman_held_by_an_open_dependency_is_not_nudged(self):
        out, ctx = self.lead(graph(link("open", False)))
        self.assertEqual(out, [])
        self.assertEqual(ctx["waits"], {"57": "waits for 0514 (open)"})

    def test_a_free_step_or_a_reached_dependency_is_nudged_as_before(self):
        out, ctx = self.lead(graph(link("open", False)), next_step="5")  # step 5 is not one of 22-27, 36
        self.assertEqual([a["do"] for a in out], ["send", "run"])
        self.assertNotIn("waits", ctx)
        out, _ = self.lead(graph(link("pushed", True)))
        self.assertEqual([a["do"] for a in out], ["send", "run"])
        out, _ = self.lead(None)  # no CLI: nothing known, nobody held back
        self.assertEqual([a["do"] for a in out], ["send", "run"])

    def test_a_dependency_of_the_whole_plan_holds_every_step(self):
        out, ctx = self.lead(graph(link("open", False, steps=[])), next_step="5")
        self.assertEqual((out, ctx["waits"]), ([], {"57": "waits for 0514 (open)"}))

    def test_the_wake_is_dropped_too_other_stops_still_wake(self):
        out, _ = self.lead(graph(link("open", False)), said="Step 21 done. Which option do you want?")
        self.assertEqual(out, [])
        out, _ = self.lead(graph(link("open", False)), kind="blocked", why="a dialog waits")
        self.assertEqual([(a["do"], a["kind"]) for a in out], [("wake", "blocked")])

    def test_the_plan_number_falls_back_to_the_plan_text(self):
        out, _ = self.lead(graph(link("open", False)), plan_number=None)
        self.assertEqual(out, [])

    def test_the_summary_says_who_waits(self):
        snap = {"now": NOW.timestamp(), "queue": [], "findings": [], "landings": [], "worktrees": [],
                "load": {"load1": 1.0, "cores": 8}}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(tick.mtm_scan, "snapshot", return_value=snap), \
                mock.patch("scan_cache.scan", return_value=snap), \
                mock.patch.object(tick.mtm_scan, "summary_dir", return_value=Path(d)):
            out = {"done": [], "waits": {"57": "waits for 0514 (open)"}}
            tick.summarize("/x/hal2", "/x/farmer-hal2", out, graph={})
            self.assertIn("- waiting 57: waits for 0514 (open)", (Path(d) / "latest.md").read_text())


class Scan(Base):
    def test_the_scan_carries_the_plans_number_and_next_step(self):
        row = {"state": "idle", "since": 1000, "project": "/x/hal2", "session_id": "s57", "slot": "57",
               "plan": "0543 · agents view", "pane_id": "%57", "checkout": "/x/none", "context_percent": 10,
               "plan_progress": {"number": 543, "next": {"number": "22", "title": "t"}}}
        with mock.patch.object(lead_scan, "run_json", return_value=[row]), \
                mock.patch.object(lead_scan, "main_checkout", return_value="/x/hal2"), \
                mock.patch.object(lead_scan, "handled", return_value=set()), \
                mock.patch.object(lead_scan, "PROJECTS", self.data / "projects"), \
                mock.patch("time.time", return_value=1000 + 3600 * 3):
            got = lead_scan.scan("/x/hal2", False)["needs_help"]
        self.assertEqual([(h["kind"], h["plan_number"], h["next_step"]) for h in got], [("idle-in-plan", 543, "22")])


class Files(Base):
    SCHEMA = json.loads((SKILL / "schemas/depends-told.schema.json").read_text())

    def test_a_line_matches_its_schema(self):
        self.run_record(lead_depends.plan({}, self.ctx(graph(link()))))
        line = self.told()[0]
        self.assertEqual(set(line), set(self.SCHEMA["properties"]))
        self.assertEqual(set(self.SCHEMA["required"]), set(self.SCHEMA["properties"]))
        self.assertRegex(line["at"], self.SCHEMA["properties"]["at"]["pattern"])
        self.assertRegex(line["key"], self.SCHEMA["properties"]["key"]["pattern"])
        self.assertEqual(line["schema"], self.SCHEMA["properties"]["schema"]["maximum"])

    def test_the_manifest_declares_it_as_a_keyed_log_with_its_schema(self):
        files = tomllib.loads((SKILL / "manifest.toml").read_text())["files"]
        entry = next(f for f in files if f["path"] == lead_depends.FILE)
        self.assertEqual((entry["kind"], entry["key"], entry["schema"]),
                         ("keyed-log", "key", "schemas/depends-told.schema.json"))

    def test_hal2_cli_roles_accepts_the_file_and_refuses_a_bad_line(self):
        if not CHECKER:
            self.skipTest("no hal2-cli-roles: the Rust check of the manifest did not run")
        self.run_record(lead_depends.plan({}, self.ctx(graph(link()))))
        folder = self.data / "fixture"
        folder.mkdir()
        (folder / "ROLE.md").write_text("---\nnotify: never\n---\n\n# farmer\n")
        (folder / lead_depends.FILE).write_bytes((mtm_scan.state_dir("/x/hal2") / lead_depends.FILE).read_bytes())
        args = [CHECKER, "check", str(folder), "--manifest", str(SKILL / "manifest.toml"), "--json"]
        p = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual((p.returncode, json.loads(p.stdout)["problems"]), (0, []), p.stdout)
        with (folder / lead_depends.FILE).open("a") as f:
            f.write(json.dumps({"schema": 1, "key": "depends:514", "plan": 514}) + "\n")
        self.assertEqual(subprocess.run(args, capture_output=True, text=True).returncode, 1)


if __name__ == "__main__":
    unittest.main()
