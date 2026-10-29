"""Hal2 plan 0458 step 3: a paused field is never started, continued or woken by a tick. Fakes only: the pause is what
`hal2-cli-git worktree paused --json` says (a patched `mtm_scan.run_json`), no session, pane or tmux is touched, and
`tick.sh` / `deliver.send` record what would have been done. The end-to-end proof on the tollman's tick is
tollman/scripts/test_paused.py."""
# enforces .adr/paused-fields-never-woken.md (step 5 of the plan)

import io
import json
import unittest
from contextlib import redirect_stderr
from unittest import mock

import field_pause
import mtm_scan
import tick
from test_farmer import NOW, Repo

PAUSE = {"by": "farmer", "why": "reading its handoff", "since": "2026-10-28T09:00:00Z"}
DOC = {"schema": 1, "repo": "hal2", "fields": [{"field": "07", **PAUSE}, {"field": "12", **PAUSE, "by": "user"}]}
ORPHAN_ARGV = ["python3", "/s/orphan_start.py", "--path", "/w/07", "--slot", "07", "--main", "/y", "--", "hal2-cli-git",
               "worktree", "run", "07", "--agent", "claude", "--detach", "--prompt", "/handoff c"]
CLEAR_ARGV = ["hal2-cli-agents", "clear-and-continue", "--pane", "%7", "--session", "s1", "--await-handoff", "--detach"]
LAND_ARGV = ["hal2-cli-git", "worktree", "queue", "release", "07"]


def act(kind, do, slot="07", duty="mtm", **fields):
    return tick.act(duty, kind, do, slot, **fields)


class Load(unittest.TestCase):
    def setUp(self):
        field_pause._said = False

    def test_the_cli_answer_is_the_pause_by_field(self):
        with mock.patch.object(mtm_scan, "run_json", return_value=DOC) as run:
            self.assertEqual(field_pause.load("/y"), {"07": PAUSE, "12": {**PAUSE, "by": "user"}})
        run.assert_called_once_with(["hal2-cli-git", "worktree", "paused", "--json"], "/y")

    def test_an_old_cli_or_an_unreadable_answer_is_nothing_paused_said_once(self):
        err = io.StringIO()
        with redirect_stderr(err), mock.patch.object(mtm_scan, "run_json", return_value=None):
            self.assertEqual(field_pause.load("/y"), {})
            self.assertEqual(field_pause.load("/y"), {})
        self.assertEqual(err.getvalue().count("no field counts as paused"), 1)
        for odd in ([], {"fields": None}, {"fields": ["07", {"by": "x"}]}):
            with redirect_stderr(io.StringIO()), mock.patch.object(mtm_scan, "run_json", return_value=odd):
                self.assertEqual(field_pause.load("/y"), {})

    def test_the_round_asks_once(self):
        holder = {}
        with mock.patch.object(mtm_scan, "run_json", return_value=DOC) as run:
            self.assertIs(field_pause.of(holder, "/y"), field_pause.of(holder, "/y"))
        self.assertEqual(run.call_count, 1)


class Starters(unittest.TestCase):
    def test_what_starts_continues_or_wakes_a_session(self):
        for a in (act("x", "send", pane="%7", text="go"), act("x", "relay", text="go"), act("x", "wake", text="go"),
                  act("orphan", "run", argv=ORPHAN_ARGV), act("continue", "run", argv=CLEAR_ARGV),
                  act("x", "run", argv=["hal2-cli-agents", "send", "%7", "hi"]),
                  act("x", "run", argv=["hal2-cli-agents", "restart", "--all"]),
                  act("x", "run", argv=["hal2-cli-git", "worktree", "run", "07"])):
            self.assertTrue(field_pause.starts_session(a), a)

    def test_landings_trains_records_and_notices_stay(self):
        for a in (act("release", "run", argv=LAND_ARGV), act("land", "run", argv=["hal2-cli-git", "worktree", "land"]),
                  act("handled", "run", argv=["python3", "/s/lead_scan.py", "record"]),
                  act("x", "record", text="x"), act("x", "notify", text="x"), act("x", "ran", name="duty:mtm"),
                  act("x", "delegate", text="x")):
            self.assertFalse(field_pause.starts_session(a), a)


class Skip(unittest.TestCase):
    def test_a_paused_field_s_starter_acts_become_keyed_records_and_their_followers_go(self):
        acts = [act("orphan", "run", argv=ORPHAN_ARGV, key="orphan:07"),
                act("handled", "run", argv=["x"], after="orphan:07"),
                act("idle", "send", "12", pane="%1", text="go", key="idle:12"),
                act("idle", "send", "09", pane="%2", text="go", key="idle:09"),
                act("release", "run", argv=LAND_ARGV, key="release:07"),
                act("ci", "notify", text="x")]
        out = field_pause.skip(acts, {"07": PAUSE, "12": {**PAUSE, "by": "user"}})
        self.assertEqual([(a["slot"], a["kind"], a["do"]) for a in out],
                         [("07", "paused-skip", "record"), ("12", "paused-skip", "record"), ("09", "idle", "send"),
                          ("07", "release", "run"), ("07", "ci", "notify")])
        first = out[0]
        self.assertEqual((first["key"], first["window"]), ("paused-skip:07:mtm:orphan", 24 * 3600))
        self.assertEqual(first["text"], "skipped run orphan: field 07 paused by farmer: reading its handoff")
        self.assertIn("paused by user", out[1]["text"])

    def test_nothing_paused_changes_nothing(self):
        acts = [act("orphan", "run", argv=ORPHAN_ARGV)]
        self.assertIs(field_pause.skip(acts, {}), acts)


class Round(Repo):
    """plan_round: the due duties' acts for a paused field are records, the rest of the round is as it was."""

    def setUp(self):
        super().setUp()
        self.handlers = {"duty:lead": lambda item, ctx: [
            act("idle-in-plan", "send", "07", "lead", pane="%7", text="continue", key="lead:s1:1"),
            act("handled", "run", "07", "lead", argv=["x"], after="lead:s1:1"),
            act("idle-in-plan", "wake", "07", "lead", key="lead:s2:1", text="idle"),
            act("orphan", "run", "07", "lead", argv=ORPHAN_ARGV, key="orphan:07"),
            act("idle-in-plan", "send", "09", "lead", pane="%9", text="continue", key="lead:s3:1")]}

    def kinds(self, rnd):
        return [(a["slot"], a["kind"], a["do"]) for a in rnd["actions"] if a["duty"] == "lead"]

    def test_a_paused_field_gets_records_not_sends_wakes_or_starts(self):
        rnd = tick.plan_round(str(self.slot), self.handlers, NOW, paused={"07": PAUSE})
        self.assertEqual(self.kinds(rnd), [("07", "paused-skip", "record"), ("07", "paused-skip", "record"),
                                           ("07", "paused-skip", "record"), ("09", "idle-in-plan", "send"),
                                           ("-", "ran", "ran")])

    def test_an_unpaused_round_is_as_before(self):
        rnd = tick.plan_round(str(self.slot), self.handlers, NOW, paused={})
        self.assertEqual([k for k in self.kinds(rnd) if k[0] == "07"],
                         [("07", "idle-in-plan", "send"), ("07", "handled", "run"), ("07", "idle-in-plan", "wake"),
                          ("07", "orphan", "run")])

    def test_the_pause_is_asked_when_the_caller_gave_none(self):
        with mock.patch.object(mtm_scan, "run_json", return_value=DOC):
            rnd = tick.plan_round(str(self.slot), self.handlers, NOW)
        self.assertEqual(self.kinds(rnd)[0], ("07", "paused-skip", "record"))

    def test_the_planner_sees_the_paused_fields(self):
        seen = []
        tick.plan_round(str(self.slot), {"duty:lead": lambda item, ctx: seen.append(ctx["paused_fields"]) or []},
                        NOW, paused={"07": PAUSE})
        self.assertEqual(seen, [{"07": PAUSE}])


class Execute(Repo):
    """execute: the second guard, for acts that never went through the planner (minute.py, chain.py, orders_cli.py)."""

    def setUp(self):
        super().setUp()
        self.ran, self.typed = [], []
        for p in (mock.patch.object(tick, "sh", lambda argv, cwd, timeout=900: self.ran.append(argv) or (0, "ok")),
                  mock.patch.object(tick.deliver, "send", lambda pane, text, s=None: self.typed.append((pane, text)))):
            p.start()
            self.addCleanup(p.stop)
        self.out = {"paused_fields": {"07": PAUSE}}

    def go(self, a):
        tick.execute(a, str(self.slot), str(self.main), self.out)
        return a

    def test_no_starter_act_of_a_paused_field_runs_types_or_wakes(self):
        for a in (act("orphan", "run", argv=ORPHAN_ARGV, key="orphan:07"), act("continue", "run", argv=CLEAR_ARGV),
                  act("x", "run", argv=["hal2-cli-git", "worktree", "run", "07"]),
                  act("x", "run", argv=["hal2-cli-agents", "send", "%7", "hi"]),
                  act("idle", "send", pane="%7", text="go", key="idle:07"), act("idle", "wake", text="x"),
                  act("idle", "relay", text="x")):
            self.go(a)
            self.assertEqual((a["do"], a["kind"]), ("record", "paused-skip"), a)
        self.assertEqual((self.ran, self.typed, self.out.get("wake"), self.out.get("relay")), ([], [], None, None))
        entries = [e for e in self.log() if e["kind"] == "paused-skip"]
        self.assertEqual(len(entries), 7)
        self.assertTrue(all(e["slot"] == "07" and e["by"] == "tick" and e["do"] == "record" for e in entries))
        self.assertIn("field 07 paused by farmer: reading its handoff", entries[0]["what"])

    def test_the_acts_after_a_dropped_one_go_with_it(self):
        self.go(act("orphan", "run", argv=ORPHAN_ARGV, key="orphan:07"))
        follower = self.go(act("handled", "run", argv=["python3", "record"], after="orphan:07"))
        self.assertEqual((follower["do"], self.ran), ("record", []))

    def test_landings_notices_other_fields_and_the_frame_are_carried_out(self):
        self.go(act("release", "run", argv=LAND_ARGV))
        self.go(act("idle", "send", "09", pane="%9", text="go"))
        self.go(act("idle", "wake", "09"))
        self.go(act("stay", "run", "-", "frame", argv=["git", "status"]))
        self.go(act("ci", "notify", text="n"))
        self.assertEqual(self.ran, [LAND_ARGV, ["git", "status"]])
        self.assertEqual([(p, t.splitlines()[0]) for p, t in self.typed], [("%9", "farmer [09-1]: go")])
        self.assertEqual([a["kind"] for a in self.out["wake"]], ["idle"])
        self.assertEqual([a["kind"] for a in self.out["notify"]], ["ci"])

    def test_the_pause_is_not_asked_for_an_act_that_cannot_start_anything(self):
        self.out = {}
        with mock.patch.object(mtm_scan, "run_json", return_value=DOC) as ask:
            self.go(act("release", "run", argv=LAND_ARGV))
            self.go(act("x", "notify", text="n"))
            self.go(act("x", "send", "-", pane="%1", text="go"))
            self.assertEqual(ask.call_count, 0)
            self.go(act("orphan", "run", "07", argv=ORPHAN_ARGV))
            self.go(act("orphan", "run", "09", argv=ORPHAN_ARGV))
            self.go(act("orphan", "run", "12", argv=ORPHAN_ARGV))
            self.assertEqual(ask.call_count, 1, "once for the round")
        self.assertEqual(self.ran, [LAND_ARGV, ORPHAN_ARGV], "only 09's was carried out")
        self.assertEqual(self.out["paused_fields"], {k: {f: v[f] for f in PAUSE} for k, v in
                                                     {"07": DOC["fields"][0], "12": DOC["fields"][1]}.items()})


class WholeRound(Repo):
    """tick.run: a paused field's acts of a real (not dry) round are logged records and nothing is carried out."""

    def test_a_round_with_a_paused_field_starts_nothing_in_it(self):
        ran, typed = [], []
        real = tick.sh

        def sh(argv, cwd, timeout=900):
            if argv[0] == "hal2-cli-git":
                return 0, json.dumps({"status": "ok"})
            ran.append(argv)
            return real(argv, cwd, timeout)

        handlers = {"duty:lead": lambda item, ctx: [
            act("orphan", "run", "07", "lead", argv=["hal2-cli-git", "worktree", "run", "07"], key="orphan:07"),
            act("idle-in-plan", "send", "07", "lead", pane="%7", text="go", key="lead:07"),
            act("idle-in-plan", "send", "09", "lead", pane="%9", text="go", key="lead:09")]}
        with mock.patch.object(tick, "sh", sh), mock.patch.object(tick, "summarize"), \
                mock.patch.object(tick.deliver, "send", lambda pane, text, s=None: typed.append(pane)), \
                mock.patch.object(mtm_scan, "run_json", lambda args, cwd=None: DOC if args[2:3] == ["paused"] else None):
            r = tick.run(str(self.slot), False, handlers, NOW)
        self.assertEqual(r["paused_fields"].keys(), {"07", "12"})
        self.assertEqual(typed, ["%9"])
        self.assertEqual([a for a in ran if "run" in a], [])
        kinds = [(e["slot"], e["kind"]) for e in self.log() if e["slot"] in ("07", "09")]
        self.assertEqual(sorted(kinds), [("07", "paused-skip"), ("07", "paused-skip"), ("09", "ask-ack"),
                                         ("09", "idle-in-plan")], "no ack is asked of a session nothing was sent to")


if __name__ == "__main__":
    unittest.main()
