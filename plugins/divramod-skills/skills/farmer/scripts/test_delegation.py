import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import delegation
import mtm_scan
import tick

import sys
sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import repo_root, sibling  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)
NOW = dt.datetime(2026, 10, 3, 10, 0)
MAIN = "/x/hal2"


def flaky():
    return tick.act("mtm", "flaky", "delegate", "08", key="flaky:t", text="disable the load-flaky test t",
                    brief={"finding": {"test": "t"}})


class Ledger(unittest.TestCase):
    """The farmer's state folder in a temp dir, free.py listing `self.free`, create.py starting worktree 18."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.calls = []

        self.free = []
        self.transplants = None  # the records `worktree transplants --json` prints; None: a CLI without the command
        self.live = {"model": "claude-opus-5-5", "effort": "medium"}  # what session.py reads in a reused session

        def call(argv, cwd):
            self.calls.append(argv)
            if argv[:3] == ["hal2-cli-git", "worktree", "transplants"]:
                return (0, json.dumps({"transplants": self.transplants})) if self.transplants is not None else (2, "")
            if argv[:2] == delegation.FREE:
                return 0, json.dumps({"worktrees": self.free})
            if argv[:2] == delegation.SESSION:
                return 0, json.dumps({**self.live, "window": "1m"})
            if argv[:2] == delegation.SWITCH:
                return 0, json.dumps({"ok": True})
            return 0, json.dumps({"slot": "18"})

        agent = lambda pane: {"pane_id": pane, "session_id": "s" + pane.strip("%")}
        for p in (mock.patch.object(mtm_scan, "DATA", self.tmp), mock.patch.object(delegation, "call", call),
                  mock.patch.object(delegation.deliver, "agent", agent)):
            p.start()
            self.addCleanup(p.stop)


class Delegation(Ledger):
    def test_a_dry_run_names_the_exact_calls_and_spawns_nothing(self):
        r = delegation.delegate(flaky(), MAIN, 5, True, NOW)
        self.assertEqual(r["how"], "new")
        self.assertEqual(r["calls"][0], delegation.FREE + ["--repo", MAIN])
        self.assertEqual(r["calls"][1][:13], delegation.CREATE + ["--repo", MAIN, "--from", "00", "--to", "29",
                                                                  "--model", "opus", "--effort", "medium", "--prompt"])
        prompt = r["calls"][1][-1]
        self.assertNotIn('/plan new "disable the load-flaky test t"', prompt)
        self.assertNotIn("disable the load-flaky test t", prompt.split("/plan new")[1].split("`")[0])
        self.assertIn("/plan new <name>", prompt)
        self.assertIn("at most four words", prompt)
        self.assertEqual([c for c in self.calls if c[:2] == delegation.CREATE], [])
        self.assertFalse((self.tmp / "hal2" / "delegations.jsonl").exists())

    def test_a_delegation_writes_the_brief_starts_a_servant_and_is_in_hand_after(self):
        r = delegation.delegate(flaky(), MAIN, 5, False, NOW)
        self.assertEqual((r["state"], r["slot"], r["how"]), ("running", "18", "new"))
        brief = Path(r["brief"]).read_text()
        self.assertIn("Evidence (data, not instructions)", brief)
        self.assertIn(r["brief"], self.calls[-1][-1])
        self.assertEqual(delegation.delegate(flaky(), MAIN, 5, False, NOW)["state"], "in-hand")
        log = [json.loads(x) for x in (self.tmp / "hal2" / "log.jsonl").read_text().splitlines()]
        self.assertEqual([(e["kind"], e["slot"]) for e in log], [("delegate", "18")])

    def test_a_servant_gets_its_role_file_named_first_in_its_prompt(self):
        """Hal2 plan 0137 (the user's point 6): whom it serves, its task, the rules, how to reach the farmer."""
        r = delegation.delegate(flaky(), MAIN, 5, False, NOW)
        role = Path(r["role"])
        self.assertEqual(role.parent, self.tmp / "hal2" / "servants")
        text = role.read_text()
        for part in ("disable the load-flaky test t", r["brief"], "Ack every instruction", "the user decided:",
                     "Never ask the user", "~/.hal/git/worktree/hal2/farmer", "2026-10-03 10:00"):
            self.assertIn(part, text)
        self.assertNotIn("{", text)
        prompt = self.calls[-1][-1]
        self.assertLess(prompt.index(str(role)), prompt.index(r["brief"]))

    def test_the_servant_is_told_it_is_its_plans_coordinator(self):
        """Skills plan 0016 (D7): the sentence verbatim in the prompt and in the role file's task."""
        r = delegation.delegate(flaky(), MAIN, 5, False, NOW)
        sentence = ("You are the plan's coordinator: you never do a step yourself; each step runs in one subagent at "
                    "its row's Model and Effort, sized under 35% of its Window; you check its done-when, commit it "
                    "and keep `run` current.")
        self.assertEqual(delegation.COORDINATOR, sentence)
        self.assertIn(sentence, self.calls[-1][-1])
        self.assertIn(sentence, Path(r["role"]).read_text())
        reference = (Path(delegation.__file__).parents[1] / "reference.md").read_text()
        self.assertIn(sentence, " ".join(line.strip().lstrip("> ") for line in reference.splitlines()))

    def test_a_new_servant_starts_at_the_role_settings_model_and_effort_and_the_ledger_keeps_them(self):
        values = delegation.servant_values({"servant_model": "claude-opus-5-5", "servant_effort": "high"})
        r = delegation.delegate(flaky(), MAIN, 5, False, NOW, values)
        create = [c for c in self.calls if c[:2] == delegation.CREATE][0]
        self.assertEqual(create[create.index("--model") + 1], "claude-opus-5-5")
        self.assertEqual(create[create.index("--effort") + 1], "high")
        self.assertEqual((r["model"], r["effort"]), ("claude-opus-5-5", "high"))
        self.assertEqual({k: delegation.ledger(MAIN)["flaky:t"][k] for k in ("model", "effort")},
                         {"model": "claude-opus-5-5", "effort": "high"})
        log = [json.loads(x) for x in (self.tmp / "hal2" / "log.jsonl").read_text().splitlines()]
        self.assertIn("at claude-opus-5-5 high", log[-1]["note"])
        self.assertEqual(delegation.servant_values({}), {"model": "opus", "effort": "medium"})

    def test_at_the_limit_it_waits_and_starts_once_a_servant_has_landed(self):
        delegation.delegate(flaky(), MAIN, 1, False, NOW)
        second = dict(flaky(), key="flaky:u", text="disable u")
        self.assertEqual(delegation.delegate(second, MAIN, 1, False, NOW)["state"], "waiting")
        later = NOW + dt.timedelta(minutes=5)
        self.assertEqual(delegation.follow_up(MAIN, {"18": {"plan": "", "ahead": 0}}, 1, False, later), [])
        done = delegation.follow_up(MAIN, {"18": {"plan": "", "ahead": 0}}, 1, False, NOW + dt.timedelta(hours=2))
        self.assertEqual([(d["state"], d["slot"]) for d in done], [("landed", "18"), ("running", "18")])
        self.assertIn(delegation.STOP + ["18", "--repo", MAIN], self.calls)
        self.assertEqual(delegation.ledger(MAIN)["flaky:u"]["state"], "running")

    def test_auto_starts_servants_while_the_load_allows_one_per_round(self):
        self.assertEqual(delegation.parse_limit(None), "auto")
        self.assertEqual(delegation.parse_limit("auto"), "auto")
        self.assertEqual(delegation.parse_limit("3"), 3)
        with mock.patch.object(delegation, "machine_load", return_value=0.5):
            self.assertEqual(delegation.delegate(flaky(), MAIN, "auto", False, NOW)["state"], "running")
        with mock.patch.object(delegation, "machine_load", return_value=0.9):
            for key in ("flaky:u", "flaky:v"):
                r = delegation.delegate(dict(flaky(), key=key, text=key), MAIN, "auto", False, NOW)
                self.assertEqual(r["state"], "waiting", key)
            busy = {"18": {"plan": "0120-fix-t", "ahead": 2}}
            self.assertEqual(delegation.follow_up(MAIN, busy, "auto", False, NOW), [])
        with mock.patch.object(delegation, "machine_load", return_value=0.5):
            started = delegation.follow_up(MAIN, busy, "auto", False, NOW)
        self.assertEqual([d["state"] for d in started], ["running"], "one per round")

    def test_a_number_still_caps_whatever_the_load(self):
        with mock.patch.object(delegation, "machine_load", return_value=0.0):
            delegation.delegate(flaky(), MAIN, 1, False, NOW)
            second = dict(flaky(), key="flaky:u", text="disable u")
            self.assertEqual(delegation.delegate(second, MAIN, 1, False, NOW)["state"], "waiting")

    def test_a_running_servant_with_its_plan_is_left_alone(self):
        delegation.delegate(flaky(), MAIN, 5, False, NOW)
        busy = {"18": {"plan": "0120-fix-t", "ahead": 2}}
        self.assertEqual(delegation.follow_up(MAIN, busy, 5, False, NOW + dt.timedelta(hours=2)), [])

    def moved(self, minutes=5, state="arrived"):
        """A transplant of slot 18 to 09 driven `minutes` after the servant started, in the record's UTC form."""
        driven = (NOW.astimezone() + dt.timedelta(minutes=minutes)).astimezone(dt.timezone.utc).isoformat()
        return {"id": "t1", "from": "18", "to": "09", "state": state, "driven": driven}

    def test_a_transplanted_servant_runs_on_in_the_target_not_landed(self):
        """Plan 0286 D26: the old field has no plan and no commits ahead, but its foreman moved to 09."""
        delegation.delegate(flaky(), MAIN, 5, False, NOW)
        self.transplants = [self.moved()]
        later = NOW + dt.timedelta(hours=2)
        done = delegation.follow_up(MAIN, {"18": {"plan": "", "ahead": 0}}, 5, False, later)
        self.assertEqual([(d["key"], d["state"], d["slot"], d["from"]) for d in done],
                         [("flaky:t", "running", "09", "18")])
        self.assertEqual([c for c in self.calls if c[:len(delegation.STOP)] == delegation.STOP], [])
        held = delegation.ledger(MAIN)["flaky:t"]
        self.assertEqual((held["state"], held["slot"], held["from"], held["title"]),
                         ("running", "09", "18", "disable the load-flaky test t"))
        log = [json.loads(x) for x in (self.tmp / "hal2" / "log.jsonl").read_text().splitlines()]
        self.assertEqual([(e["kind"], e["slot"]) for e in log], [("delegate", "18"), ("transplant", "09")])
        # the next round reads the target: its plan keeps it running; later, the target landing is a landing
        self.assertEqual(delegation.follow_up(MAIN, {"09": {"plan": "0120-x", "ahead": 1}}, 5, False, later), [])
        done = delegation.follow_up(MAIN, {"09": {"plan": "", "ahead": 0}}, 5, False, later + dt.timedelta(hours=2))
        self.assertEqual([(d["state"], d["slot"]) for d in done], [("landed", "09")])
        self.assertIn(delegation.STOP + ["09", "--repo", MAIN], self.calls)

    def test_a_dry_round_reports_the_move_and_writes_nothing(self):
        delegation.delegate(flaky(), MAIN, 5, False, NOW)
        self.transplants = [self.moved()]
        done = delegation.follow_up(MAIN, {}, 5, True, NOW + dt.timedelta(hours=2))
        self.assertEqual([d["slot"] for d in done], ["09"])
        self.assertEqual(delegation.ledger(MAIN)["flaky:t"]["slot"], "18")

    def test_a_landed_field_is_recorded_landed_as_before(self):
        delegation.delegate(flaky(), MAIN, 5, False, NOW)
        for transplants in (None, [], [self.moved(-30)], [self.moved(5, "prepared")], [dict(self.moved(), **{"from": "07"})]):
            self.transplants = transplants
            done = delegation.follow_up(MAIN, {"18": {"plan": "", "ahead": 0}}, 5, True, NOW + dt.timedelta(hours=2))
            self.assertEqual([(d["state"], d["slot"]) for d in done], [("landed", "18")], transplants)
        self.transplants = None
        done = delegation.follow_up(MAIN, {"18": {"plan": "", "ahead": 0}}, 5, False, NOW + dt.timedelta(hours=2))
        self.assertEqual(delegation.ledger(MAIN)["flaky:t"]["state"], "landed")
        self.assertIn(delegation.STOP + ["18", "--repo", MAIN], self.calls)


class ForemanFields(Ledger):
    """Plan 0333 step 9 (D11): a foreman never starts in a field 30-99, where the tollman refuses its wagon."""

    def create_says(self, code, out):
        """create.py answers `(code, out)`, every other call as in Ledger.setUp."""
        base = delegation.call

        def call(argv, cwd):
            if argv[:2] == delegation.CREATE:
                self.calls.append(argv)
                return code, out
            return base(argv, cwd)
        p = mock.patch.object(delegation, "call", call)
        p.start()
        self.addCleanup(p.stop)

    def test_all_fields_00_29_busy_nothing_starts_and_the_action_waits_with_the_reason(self):
        """Today's 44-50: with 00-29 full create.py went on to 44. Now the range ends at 29 and the delegation waits."""
        self.create_says(delegation.NO_FREE_EXIT, "")
        with mock.patch.object(delegation.deliver, "send", return_value=None) as send:
            self.free = [{"slot": "44", "panes": ["%44"]}, {"slot": "main", "panes": ["%1"]}]
            r = delegation.delegate(flaky(), MAIN, 5, False, NOW)
        send.assert_not_called()  # the idle session in field 44 is not taken
        self.assertEqual((r["state"], r["reason"]), ("waiting", "no free field 00-29"))
        create = [c for c in self.calls if c[:2] == delegation.CREATE]
        self.assertEqual(len(create), 1)
        self.assertEqual(create[0][create[0].index("--from"):create[0].index("--from") + 4], ["--from", "00", "--to", "29"])
        entry = delegation.ledger(MAIN)["flaky:t"]
        self.assertEqual((entry["state"], entry["reason"]), ("waiting", "no free field 00-29"))
        log = [json.loads(x) for x in (self.tmp / "hal2" / "log.jsonl").read_text().splitlines()]
        self.assertIn("no free field 00-29", log[-1]["note"])
        # retried every round for the same reason: not noted nor logged again
        again = delegation.follow_up(MAIN, {}, 5, False, NOW + dt.timedelta(minutes=5))
        self.assertEqual([(d["state"], d["reason"]) for d in again], [("waiting", "no free field 00-29")])
        self.assertEqual(len((self.tmp / "hal2" / "log.jsonl").read_text().splitlines()), len(log))

    def test_a_waiting_delegation_starts_once_a_field_is_free(self):
        self.create_says(delegation.NO_FREE_EXIT, "")
        self.assertEqual(delegation.delegate(flaky(), MAIN, 5, False, NOW)["state"], "waiting")
        self.create_says(0, json.dumps({"slot": "07"}))
        later = delegation.follow_up(MAIN, {}, 5, False, NOW + dt.timedelta(minutes=5))
        self.assertEqual([(d["state"], d["slot"]) for d in later], [("running", "07")])

    def test_a_done_cleaned_field_07_is_reused(self):
        self.create_says(0, json.dumps({"slot": "07"}))
        r = delegation.delegate(flaky(), MAIN, 5, False, NOW)
        self.assertEqual((r["state"], r["slot"], r["how"]), ("running", "07", "new"))

    def test_the_limit_bypass_hands_create_the_same_range(self):
        """`farmer.py delegate` and the tick call the same delegate(): no path passes a range reaching 30."""
        with mock.patch.object(delegation, "machine_load", return_value=0.0):
            r = delegation.delegate(flaky(), MAIN, 999, True, NOW)
        argv = r["calls"][1]
        self.assertEqual(argv[argv.index("--from") + 1:argv.index("--from") + 4], ["00", "--to", "29"])

    def test_a_create_that_lands_in_44_is_refused(self):
        self.create_says(0, json.dumps({"slot": "44"}))
        r = delegation.delegate(flaky(), MAIN, 5, False, NOW)
        self.assertEqual(r["state"], "error")
        self.assertIn("field 44", r["error"])
        self.assertIn("outside 00-29", r["error"])

    def test_a_free_session_in_30_99_is_never_taken(self):
        self.create_says(delegation.NO_FREE_EXIT, "")
        for slot in ("30", "44", "99"):
            self.assertFalse(delegation.servant_slot(slot))
        for slot in ("00", "07", "29"):
            self.assertTrue(delegation.servant_slot(slot))


class ServantSlots(Ledger):
    """Plan 0270 (D13): the farmer's sessions (foremen) work in the first free worktree counting from 00; a foreman's
    own servants stay in 30-99 (skills plan 0013)."""

    def delegate_free(self, free):
        self.free = free
        with mock.patch.object(delegation.deliver, "send", return_value=None) as send:
            return delegation.delegate(flaky(), MAIN, 5, False, NOW), send

    def test_a_free_session_below_30_is_reused(self):
        """Fails on the old behaviour: slot 05 was skipped and a new session started at 30."""
        r, send = self.delegate_free([{"slot": "05", "panes": ["%5"]}, {"slot": "31", "panes": ["%31"]}])
        self.assertEqual((r["state"], r["slot"], r["how"]), ("running", "05", "free"))
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], "%5")
        self.assertEqual([c for c in self.calls if c[:2] == delegation.CREATE], [])

    def test_slot_00_is_taken_when_free_and_the_lowest_slot_wins(self):
        r, send = self.delegate_free([{"slot": "31", "panes": ["%31"]}, {"slot": "12", "panes": ["%12"]},
                                      {"slot": "00", "panes": ["%0"]}])
        self.assertEqual((r["slot"], r["how"]), ("00", "free"))
        self.assertEqual(send.call_args.args[0], "%0")

    def test_main_and_the_role_slots_are_never_taken(self):
        r, send = self.delegate_free([{"slot": "main", "panes": ["%1"]}, {"slot": "farmer-hal2", "panes": ["%2"]},
                                      {"slot": "21", "panes": ["%21"]}])
        self.assertEqual((r["slot"], r["how"]), ("21", "free"))
        self.assertEqual(send.call_args.args[0], "%21")

    def test_with_no_free_session_a_new_one_starts_from_00(self):
        r, send = self.delegate_free([{"slot": "main", "panes": ["%1"]}])
        send.assert_not_called()
        self.assertEqual((r["state"], r["how"]), ("running", "new"))
        create = [c for c in self.calls if c[:2] == delegation.CREATE]
        self.assertEqual(len(create), 1)
        self.assertEqual(create[0][2:6], ["--repo", MAIN, "--from", "00"])

    def test_a_foremans_servants_still_work_only_in_30_to_99(self):
        self.assertEqual(delegation.TO + 1, 30, "a foreman's fields end where the servants' begin")
        record = repo_root(delegation.__file__) / ".adr" / "subservants-in-slots-30-99.md"
        if record.exists():  # the repository's record stays as it is
            self.assertIn("A servant MUST work only in a worktree from 30 to 99", record.read_text())

    def test_a_reused_session_at_other_values_is_switched_never_typed_into(self):
        """Skills plan 0016: a free session at sonnet or another effort restarts at the foreman's values."""
        self.free = [{"slot": "21", "panes": ["%21"]}]
        for live in ({"model": "claude-sonnet-5-5", "effort": "medium"}, {"model": "opus[1m]", "effort": "max"},
                     {"model": "", "effort": ""}):
            self.live, self.calls[:] = live, []
            key = f"flaky:{live['model']}{live['effort']}"
            with mock.patch.object(delegation.deliver, "send", return_value=None) as send:
                r = delegation.delegate(dict(flaky(), key=key), MAIN, 5, False, NOW)
            send.assert_not_called()
            self.assertEqual((r["slot"], r["how"]), ("21", "switch"), live)
            switch = [c for c in self.calls if c[:2] == delegation.SWITCH][0]
            self.assertEqual(switch[2:7], ["%21", "--model", "opus", "--effort", "medium"])
            self.assertIn("--detach", switch)
            self.assertIn(delegation.COORDINATOR, switch[switch.index("--prompt") + 1])

    def test_model_families_match_aliases_and_ids(self):
        self.assertTrue(delegation.same_model("claude-opus-5-5", "opus"))
        self.assertTrue(delegation.same_model("opus[1m]", "opus"))
        self.assertFalse(delegation.same_model("claude-sonnet-5-5", "opus"))
        self.assertFalse(delegation.same_model("claude-opus-4-6", "claude-opus-5-5"))

    def test_follow_up_never_touches_a_session_it_did_not_start(self):
        """A session in worktree 21 that is not in the farmer's ledger (a user's, or a former servant) is neither
        recorded nor stopped, even when its worktree looks landed."""
        delegation.delegate(flaky(), MAIN, 5, False, NOW)
        slots = {"18": {"plan": "0120-fix-t", "ahead": 2}, "21": {"plan": "", "ahead": 0}}
        self.assertEqual(delegation.follow_up(MAIN, slots, 5, False, NOW + dt.timedelta(hours=2)), [])
        self.assertFalse([c for c in self.calls if c[:len(delegation.STOP)] == delegation.STOP])
        self.assertNotIn("21", {e.get("slot") for e in delegation.ledger(MAIN).values()})


if __name__ == "__main__":
    unittest.main()
