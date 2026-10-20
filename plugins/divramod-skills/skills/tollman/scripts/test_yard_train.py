"""Hal2 plan 0294 step 8: the yard's car in whole rounds, on engine_farm.py's farm: the yard (the farm's main
checkout, a temporary clone) holds a file that may ride and one that may not; field 07 hitches, the tollman's
tick forms, lands and settles. The functions themselves are test_yard.py's."""

import json
import unittest

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import board
import train_state
import yard_rules
from engine_farm import OWN, Farm, out
from test_farmer import git

RECORD = "# Repo root\n\n## Decision\n\n- `docs/`: guides\n- `roles/<role>/`: a role's folder\n"
FARMER = "farmer-hal2"
LEFT = [{"path": ".env", "why": "secret-shaped"}]


class YardFarm(Farm):
    def setUp(self):
        super().setUp()
        self.commit(self.main, yard_rules.RECORD, RECORD, push=True)
        git(self.wm, "merge", "-q", "--ff-only", "main")
        self.fields[FARMER], self.panes = self.slot, {FARMER: "%1"}
        (self.main / "docs").mkdir()
        (self.main / "docs/note.md").write_text("from the yard\n")
        (self.main / ".env").write_text("A=1\n")
        self.before = self.yard()

    def yard(self):
        return out(self.main, "status", "--porcelain", "-uall"), out(self.main, "rev-parse", "HEAD")

    def first_parents(self):
        return out(self.cw, "log", "--first-parent", "--format=%s", "origin/main..HEAD").splitlines()  # plan 0375 D5

    def notes(self):
        """What the farmer may read on the board when it asks (plan 0360 step 8, D9): never typed into its session."""
        self.assertNotIn(self.panes[FARMER], [pane for pane, _ in self.typed], "nothing is sent to the farmer")
        return [r["text"] for r in board.lines(str(self.main), "note") if r["to"] == FARMER]

    def dry(self):
        return json.loads(self.call("train", "--dry-run", "--json", repo=self.main)[1])["yard"]


class Riding(YardFarm):
    def test_the_dry_run_lists_placed_and_left_and_changes_nothing(self):
        self.crop("07", {"seven.txt": "7"})
        d = self.dry()
        self.assertEqual(([e["path"] for e in d["placed"]], d["left"], d["skipped"]), (["docs/note.md"], LEFT, None))
        self.assertIn("yard: placed: docs/note.md\nyard: left: .env: secret-shaped\n", self.call("train", "--dry-run")[1])
        r = json.loads(self.call("tick", "--dry-run", "--json")[1])
        self.assertEqual([(a["kind"], a["do"]) for a in r["planned"] if a["duty"] == "trains"],
                         [("form", "run"), ("yard-left", "record"), ("ran", "ran")])
        self.assertEqual((self.yard(), self.state(), self.subjects(), self.typed), (self.before, [], [], []))

    def test_the_yard_rides_as_the_first_car_and_is_settled_after_the_green_landing(self):
        self.crop("07", {"seven.txt": "7"}, plan="0294-tollman-role")
        self.round()
        self.assertEqual(self.last, [("form", "run", "-"), ("yard-left", "record", FARMER)])
        self.assertEqual(self.first_parents(), [f"Merge branch '07' into {self.carrier()}",
                                                "chore(yard): 1 file from the yard"], "before the wagons' merges")
        self.assertEqual((self.cw / "plans/CURRENT_PLAN").read_text(), "yard + 0294-tollman-role\n")
        self.assertEqual(self.gate.calls, [["worktree", "queue", "train", self.carrier(), "07", "--train", "1", "--attempt", "1"]], "the mark names only fields")
        self.assertEqual(self.state(), [("formed", self.carrier()), ("yard", self.carrier()), ("started", self.carrier())])
        car = train_state.lines(str(self.main))[1]
        self.assertEqual((car["commit"], car["files"], self.train()["yard"]),
                         (out(self.cw, "rev-parse", "HEAD^1"),
                          [{"path": "docs/note.md", "hash": out(self.cw, "rev-parse", "HEAD:docs/note.md")}], car["files"]))
        self.assertEqual(self.yard(), self.before, "the yard as it was: nothing there changes before the landing")
        (text,) = self.notes()
        self.assertRegex(text, r"^tollman \(yard\): 1 of the yard's uncommitted files stay "
                               r"there, the train does not bring them in: \.env \(secret-shaped\)\.")
        note = board.lines(str(self.main), "note")[-1]
        self.assertEqual((note["to"], note["from"], note["slot"]), (FARMER, OWN, FARMER))
        self.assertEqual(board.lines(str(self.main), "message"), [], "no message, no ack asked of the farmer")

        self.alive.add(40001)
        self.ends({"status": "landed", "commit": "c0ffee"}, land=True)
        self.round()
        self.assertIn(("landed", "run", "-"), self.last)
        self.assertEqual(train_state.lines(str(self.main))[-1]["yard"],
                         {"dropped": ["docs/note.md"], "kept": [], "pulled": True, "why": ""})
        self.assertEqual(self.yard(), ("?? .env", out(self.main, "rev-parse", "origin/main")), "clean and fast-forwarded")
        self.assertEqual((self.main / "docs/note.md").read_text(), "from the yard\n")
        self.crop("09", {"nine.txt": "9"})
        self.round()
        self.assertEqual((self.last, len(self.notes())), ([("form", "run", "-")], 1),
                         "the same files left: one note, not one every train")

    def test_a_red_train_leaves_the_yard_as_it_was_and_unhitch_yard_keeps_its_files_out(self):
        self.crop("07", {"seven.txt": "7"})
        self.assertEqual(self.call("unhitch", "yard", "--why", "x")[0], 1, "no train stands")
        self.round()
        self.alive.add(40001)
        self.assertIn("a running landing is never stopped", self.call("unhitch", "yard", "--why", "x")[1])
        self.ends({"status": "gate_failed", "run": "https://github.com/x/runs/9", "red": [{"name": "linux / records"}]})
        self.gate.of(self.carrier()).update(state="held", train=None, hold={"reason": "failed"})  # the landing's end
        r = self.round()
        self.assertIn("Cars: 07 (07), yard (1 files of the yard).", r["wake"][0]["text"])
        self.assertIn("frozen (plan 0360 D3)", r["wake"][0]["text"])
        self.assertEqual((self.yard(), self.train()["state"]), (self.before, "red"), "nothing in the yard changes")

        self.typed.clear()
        code, text = self.call("unhitch", "yard", "--why", "its record is malformed", repo=self.main)
        self.assertEqual(code, 1, "the session's unhitch of a frozen train's car is refused (plan 0360 D3)")
        self.assertIn("frozen (plan 0360 D3)", text)
        code, text = self.call("unhitch", "yard", "--why", "its record is malformed", "--by-user", repo=self.main)
        self.assertEqual((code, text), (0, "yard unhitched: its record is malformed; the rest of the train forms "
                                           f"again\nchain link 1: breakup -, form -, yard-left {FARMER}\n"
                                           "chain stops: a landing started\n"), "in the same call (plan 0333 step 6)")
        self.assertTrue(self.gate.of("07")["ready"], "the wagon keeps its place")
        self.assertEqual(self.first_parents(), [f"Merge branch '07' into {self.carrier()}"], "the train without the yard")
        self.assertEqual((self.state()[-4:], self.train()["yard"], self.yard()),
                         ([("unhitched", "yard"), ("cleared", self.carrier()), ("formed", self.carrier()), ("started", self.carrier())], [], self.before))
        self.assertIn("docs/note.md (unhitched from a red train: it stays until it changes)", self.notes()[-1])
        self.assertNotIn("yard", [c for call in self.gate.calls for c in call], "the yard has no ticket")
        self.assertEqual(board.lines(str(self.main), "unhitched"), [], "the yard is no field: no board line (D21)")
        (self.main / "docs/note.md").write_text("mended\n")
        self.assertEqual([e["path"] for e in self.dry()["placed"]], ["docs/note.md"], "changed: it may ride again")

    def test_a_carried_file_changed_meanwhile_stays_and_the_farmer_is_told_once(self):
        self.crop("07", {"seven.txt": "7"})
        self.round()
        self.alive.add(40001)
        (self.main / "docs/note.md").write_text("changed meanwhile\n")
        self.ends({"status": "landed"}, land=True)
        self.typed.clear()
        self.round()
        home = train_state.lines(str(self.main))[-1]["yard"]
        self.assertEqual((home["dropped"], home["kept"], home["pulled"]),
                         ([], [{"path": "docs/note.md", "why": "changed meanwhile"}], False))
        self.assertEqual((self.yard(), (self.main / "docs/note.md").read_text()), (self.before, "changed meanwhile\n"))
        self.assertEqual(self.last, [("landed", "run", "-"), ("in-the-barn", "relay", "07"), ("chain", "run", "-")])
        self.assertRegex(self.notes()[-1], r"\(yard\): train 07@\S+ is in the barn, but 1 of the files it carried "
                                            r"from the yard stay there as they are \(docs/note.md \(changed "
                                            r"meanwhile\)\) and the yard was not fast-forwarded \(")
        self.round()
        self.assertEqual((self.last, len([n for n in self.notes() if "is in the barn, but" in n])), ([], 1),
                         "once, on the board")


class Skipping(YardFarm):
    def test_a_yard_with_work_but_no_ready_wagon_forms_no_train_by_itself(self):
        self.round()
        self.assertEqual((self.last, self.state(), self.typed, self.yard()), ([], [], [], self.before))

    def test_a_yard_on_another_branch_is_said_and_the_train_forms_without_it(self):
        git(self.main, "checkout", "-q", "-b", "side")
        self.crop("07", {"seven.txt": "7"})
        self.assertEqual(self.dry()["skipped"], "the yard is on side, not on main")
        self.round()
        self.assertEqual(self.last, [("form", "run", "-"), ("yard-left", "record", FARMER)])
        self.assertIn("(yard): the yard's uncommitted work is not brought in: the yard is on side, not on main. "
                      "Nothing there was changed.", self.notes()[0])
        self.assertEqual((self.first_parents(), self.state(), self.yard()[0]),
                         ([f"Merge branch '07' into {self.carrier()}"], [("formed", self.carrier()), ("started", self.carrier())], self.before[0]))


if __name__ == "__main__":
    unittest.main()
