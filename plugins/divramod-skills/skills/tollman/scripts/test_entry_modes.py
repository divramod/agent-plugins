"""Hal2 plan 0365 (D3, D5, D9): the tollman's sleep flag `sleep.json` and each entry's mode. The flag puts the round to
sleep in any mode (the record says `asleep: flag ...`, the flag first), a train already landing is never cut, the
checks are held back, and the way back from smuggle mode to production is noted only once the flag is off, so the
cars smuggled meanwhile are still found. Entry modes (`effective_mode`, else `mode`, else the queue's): in smuggle
mode an entry in production wakes the tollman for it alone, in production mode an entry in smuggle is no car. gh is
gh_fake.py's, the queue engine_farm's Gate, git a temporary repository."""

import json
import unittest

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import checks
import modes
import roles
from gh_fake import FakeGh, job
from test_modes import HITCHED, MAIN, OURS, SMUGGLE, STARTED, FORMED, TOP, WokenBase, kinds, plan, trains

FLAG = {"schema": 1, "by": "user", "at": "2026-10-18T09:00:00Z", "why": "the runners are down"}
FLAGGED = "asleep: flag since 2026-10-18T09:00:00Z (by user): the runners are down"


def entry(slot, mode=None, effective=None):
    """A hitched entry as `queue --json` of step 1 gives it (`mode` own or None, `effective_mode`)."""
    return {**HITCHED, "slot": slot, "mode": mode, **({"effective_mode": effective} if effective else {})}


class Pure(unittest.TestCase):
    def test_the_flag_sleeps_in_production_mode_and_says_why(self):
        out = trains.plan(TOP, MAIN, [HITCHED], [], {}, alive=lambda pid: False, result=lambda main: None,
                          mode=None, sleep_flag=FLAG)
        self.assertEqual(kinds(out), [("asleep", "record")])
        self.assertEqual(out[0]["text"], FLAGGED)
        self.assertTrue(modes.asleep(None, [HITCHED], FLAG))
        self.assertFalse(modes.asleep(None, [HITCHED], None))

    def test_the_flag_comes_before_smuggle_mode_and_a_landing_train_goes_on(self):
        FakeGh([OURS], jobs={"501": [job("d1-01-rust-test", "failure")]}, logs={"501": ""}).start(self)
        out = trains.plan(TOP, MAIN, [], [FORMED, STARTED], {}, alive=lambda pid: pid == 4711,
                          result=lambda main: None, mode=SMUGGLE, sleep_flag=FLAG)
        self.assertEqual(kinds(out), [("asleep", "record"), ("train-run", "run")], "watched, never cut")
        self.assertEqual(out[0]["text"], FLAGGED)
        self.assertEqual(modes.reason(SMUGGLE, [], FLAG), "flag")
        self.assertEqual(modes.reason(SMUGGLE, [], None), "smuggle")
        self.assertIsNone(modes.reason(None, [HITCHED], None))

    def test_the_checks_are_held_back_while_the_flag_stands(self):
        busy = modes.busy(None, [], FLAG)
        self.assertEqual(busy["reason"], FLAGGED[len("asleep: "):] + ": the tollman sleeps")
        self.assertIsNone(modes.busy(None, [], None))

    def test_smuggle_mode_wakes_for_a_production_entry_alone(self):
        one = [entry("11", "production", "production"), entry("12", None, "smuggle")]
        self.assertIsNone(modes.reason(SMUGGLE, one, None), "an entry in production is brought in by a train")
        self.assertEqual(modes.reason(SMUGGLE, [entry("12", None, "smuggle")], None), "smuggle")
        self.assertEqual(modes.reason(SMUGGLE, [dict(HITCHED, ready=None)], None), "smuggle", "not hitched: nothing")
        self.assertEqual(modes.reason(SMUGGLE, [entry("12", "smuggle")], None), "smuggle", "an older CLI: own mode")
        self.assertIsNone(modes.reason(SMUGGLE, [entry("12", "production")], None))
        self.assertNotIn(("asleep", "record"), kinds(plan([], one)), "awake: no asleep record")
        self.assertEqual(kinds(plan([], [entry("12", None, "smuggle")])), [("asleep", "record")])

    def test_fields_missing_read_as_the_queues_mode(self):
        self.assertEqual(modes.reason(SMUGGLE, [HITCHED], None), "smuggle", "no field at all: the queue's smuggle")
        self.assertIsNone(modes.reason(None, [HITCHED], None))
        self.assertIsNone(modes.reason({}, [], None))

    def test_a_smuggle_entry_is_no_car_in_production_mode(self):
        a, b, own = entry("11", None, "production"), entry("12", "smuggle", "smuggle"), entry("tollman-hal2", None, "smuggle")
        self.assertEqual([t["slot"] for t in modes.trainable([a, b, own], None, "tollman-hal2")], ["11", "tollman-hal2"])
        self.assertEqual([t["slot"] for t in modes.trainable([b, dict(b, ready=None, slot="13")], None, "x")], ["13"],
                         "a waiting entry without a hitch stays in the queue's view")
        self.assertEqual([t["slot"] for t in modes.trainable([HITCHED], None, "x")], ["11"], "older CLI: production")


class Round(WokenBase):
    def flag(self, on=True):
        """The flag where hal2-roles writes it: `roles/tollman/sleep.json` of the field `tollman-hal2`, its role
        folder ignored as the farm's committed `.gitignore` has it (else the round finds an untracked file)."""
        f = self.wm / "roles" / "tollman" / modes.SLEEP
        f.parent.mkdir(parents=True, exist_ok=True)
        (f.parent / ".gitignore").write_text(roles.GITIGNORE)
        f.unlink(missing_ok=True) if not on else f.write_text(json.dumps(FLAG) + "\n")

    def test_the_flag_reads_from_the_fields_role_folder(self):
        self.assertEqual(modes.flag_file(str(self.main)), self.wm / "roles" / "tollman" / modes.SLEEP)
        self.assertIsNone(modes.flag(str(self.main)))
        self.flag()
        self.assertEqual(modes.flag(str(self.main)), FLAG)
        self.assertEqual(modes.flag(str(self.wm)), FLAG, "the same file from the tollman's own field")
        modes.flag_file(str(self.main)).write_text("{broken")
        self.assertEqual(modes.flag(str(self.main)), {}, "an unreadable flag still sleeps")
        self.assertTrue(modes.asleep(None, [], modes.flag(str(self.main))))
        self.flag(False)
        self.assertIsNone(modes.flag(str(self.main)))
        self.assertIsNone(modes.flag("/no/such/farm"))

    def test_a_flag_in_farmer_dirs_state_folder_is_not_the_tollmans(self):
        """Review finding 8: with `$FARMER_DIR` the state folder moves, the flag hal2-roles writes does not."""
        self.assertNotEqual(self.wm_state, modes.flag_file(str(self.main)).parent, "the test farm sets FARMER_DIR")
        self.wm_state.mkdir(parents=True, exist_ok=True)
        (self.wm_state / modes.SLEEP).write_text(json.dumps(FLAG) + "\n")
        self.assertIsNone(modes.flag(str(self.main)))
        self.crop("07", {"seven.txt": "7"})
        self.round()
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["07"], "awake: the train forms")

    def test_the_flag_stops_the_trains_and_wakes_nobody_until_it_is_off(self):
        self.crop("07", {"seven.txt": "7"})
        self.flag()
        self.round()
        self.assertEqual(self.last, [("asleep", "record", "-")])
        self.assertEqual((self.spawned, self.train()), ([], None))
        self.assertEqual(self.round() and self.last, [("asleep", "record", "-")], "one line each round")
        self.flag(False)
        self.round()
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["07"], "awake: the train forms")

    def test_the_flag_holds_the_checks_back(self):
        self.flag()

        def run_json(args, cwd=None):
            return {"queue": []} if args[:3] == ["hal2-cli-git", "worktree", "queue"] else []
        held = checks.state(str(self.main), run_json, sessions=set())["busy"]
        self.assertIn("flag since", held["reason"])
        self.flag(False)
        self.assertIsNone(checks.state(str(self.main), run_json, sessions=set())["busy"])

    def test_the_barn_is_still_found_when_the_flag_is_off_after_smuggle_mode(self):
        self.crop("07", {"seven.txt": "7"})
        self.crop("09", {"nine.txt": "9"})
        self.panes = {"09": "%9"}
        self.smuggled("09")
        self.mode = SMUGGLE
        self.round()
        self.flag()
        self.mode = None
        self.round()
        self.assertEqual(self.last, [("asleep", "record", "-")], "the way back is not noted while the flag stands")
        self.assertEqual((modes.seen(str(self.main)), self.barn_lines()), ("smuggle", []))
        self.flag(False)
        self.round()
        self.assertEqual(self.barn_lines(), [("09", "hitch")])
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["07"])

    def test_a_production_entry_is_carried_in_smuggle_mode_and_a_smuggle_entry_is_not_in_production(self):
        self.crop("07", {"seven.txt": "7"})
        self.crop("09", {"nine.txt": "9"})
        self.gate.of("09").update(mode="smuggle", effective_mode="smuggle")
        self.gate.of("07").update(mode=None, effective_mode="production")
        self.round()
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["07"], "09 smuggles itself")
        self.assertTrue(self.gate.of("09")["ready"], "its hitch stays for its own /mtm")

    def test_smuggle_mode_with_a_production_entry_wakes_the_tollman_for_it_alone(self):
        self.crop("07", {"seven.txt": "7"})
        self.crop("09", {"nine.txt": "9"})
        self.mode = SMUGGLE
        self.gate.of("07").update(mode="production", effective_mode="production")
        self.gate.of("09").update(mode=None, effective_mode="smuggle")
        self.round()
        self.assertNotIn(("asleep", "record", "-"), self.last)
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["07"])
        self.assertEqual(modes.seen(str(self.main)), "smuggle")


if __name__ == "__main__":
    unittest.main()
