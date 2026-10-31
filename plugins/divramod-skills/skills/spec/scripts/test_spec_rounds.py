"""spec.py as a loop (hal2 plan 0502 step 3, D6 to D8): `new` makes the plan in state spec, `iterate` ends a round
with the checkpoint, `update` starts one on any spec and flags a planned plan for review, `abandon`, `reviewed`,
`new --seed`. Scratch repositories only; the seed tests run a fake hal2-cli-shooter."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spec_testkit import FILLED, RECORDS, SpecCase, envelope, spec  # noqa: F401

FAKE_SHOOTER = """#!/bin/sh
echo "$@" >> "$FAKE_LOG"
case "$2" in
  list-open) printf '%s\\n' '{"shots": [{"file": "skill-spec", "number": "4", "title": "passkeys for login"}]}' ;;
  mark-sent) echo '{}' ;;
esac
"""


class RoundsTest(SpecCase):
    def run_json(self, *args) -> dict:
        code, out, err = self.run_spec(*args, "--json")
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_new_writes_the_plan_in_state_spec_with_a_pointer_brief_and_the_ledgers(self):
        info = self.new()
        text = self.plan_text(info)
        meta = envelope.parse(envelope.split(text)[0])
        self.assertEqual((meta["type"], meta["schema"], meta["status"], meta["id"]), ("Plan", 1, "spec", 8))
        body = envelope.split(text)[1]
        self.assertEqual(envelope.headings(body, 2), ["Goal", "Brief", "Context", "Pre-authorized"])
        self.assertIn("[spec.md](spec.md)", envelope.section(body, "Brief"))
        self.assertNotIn("<", envelope.section(body, "Brief"))
        for name in ("decisions.md", "questions.md", "handoff.md"):
            self.assertEqual(envelope.get((self.root / info["folder"] / name).read_text(), "status"), "open")

    @unittest.skipUnless(RECORDS, "no hal2-cli-records")
    def test_every_step_of_the_loop_leaves_a_folder_the_checker_passes(self):
        info = self.new()
        self.assertEqual(self.problems(), [])
        self.run_json("iterate")
        self.assertEqual(self.problems(), [])
        self.run_json("update", "--what", "scope changed")
        self.assertEqual(self.problems(), [])
        self.run_json("abandon")
        self.assertEqual(self.problems(), [], "an abandoned spec closes its plan, ledgers and handoff")
        self.assertEqual(envelope.get(self.plan_text(info), "status"), "abandoned")
        self.assertEqual(envelope.get((self.root / info["folder"] / "handoff.md").read_text(), "status"), "closed")

    def test_iterate_counts_the_round_and_recommends_another_round_while_something_is_open(self):
        info = self.new()
        done = self.run_json("iterate")
        self.assertEqual((done["iteration"], done["checkpoint"]["recommended"]), (1, "another_round"))
        self.assertEqual(done["checkpoint"]["open"]["placeholders"], 12)
        self.assertEqual([o["id"] for o in done["checkpoint"]["options"]],
                         ["another_round", "plan_now", "bring_in"], "the recommended option first")
        self.assertEqual(envelope.get((self.root / info["spec"]).read_text(), "iteration"), 1)
        self.assertEqual(self.run_json("iterate")["iteration"], 2)

    def test_the_checkpoint_recommends_plan_now_only_when_nothing_is_left_open(self):
        info = self.new()
        path = self.fill(info)
        self.assertEqual(self.run_json("iterate")["checkpoint"]["recommended"], "plan_now")
        text = path.read_text()
        for old, new, what in (("## Not yet specified\n\n- none", "## Not yet specified\n\n- the recovery flow", "not_yet_specified"),
                               ("## Open questions\n\n- none", "## Open questions\n\n- which browsers?", "open_questions")):
            path.write_text(text.replace(old, new))
            done = self.run_json("iterate")["checkpoint"]
            self.assertEqual((done["recommended"], len(done["open"][what])), ("another_round", 1), what)
        path.write_text(text)
        self.run_ok_questions(info)
        self.assertEqual(self.run_json("iterate")["checkpoint"]["open"]["plan_questions"], 1)
        self.assertEqual(self.run_json("iterate")["checkpoint"]["recommended"], "another_round")

    def run_ok_questions(self, info: dict) -> None:
        path = self.root / info["folder"] / "questions.md"
        path.write_text(path.read_text() + "\n## Q1 · 2026-10-30 · agent · open\n\n**Q:** which browsers?\n")

    def test_iterate_reseeds_the_brief_of_a_plan_without_steps_from_the_spec(self):
        info = self.new()
        self.fill(info)
        done = self.run_json("iterate")
        brief = envelope.section(envelope.split(self.plan_text(done))[1], "Brief")
        self.assertIn("- In: passkey sign-up and login", brief)
        self.assertIn("- Out: recovery (a later plan)", brief)
        self.assertIn("A1", brief)

    def test_iterate_refuses_a_spec_that_is_not_a_draft(self):
        self.new()
        self.fill(self.run_json("show"))
        self.run_json("approve")
        code, _, err = self.run_spec("iterate")
        self.assertEqual(code, 1)
        self.assertIn("is approved, not a draft", err)
        self.assertIn("spec.py update", err)

    def test_update_starts_a_round_on_an_approved_spec_and_reseeds_an_unplanned_brief(self):
        info = self.new()
        path = self.fill(info)
        self.run_json("approve")
        path.write_text(path.read_text().replace("recovery (a later plan)", "recovery by e-mail"))
        done = self.run_json("update", "--what", "recovery is in")
        self.assertEqual((done["status"], done["iteration"], done["what"], done["flagged"]),
                         ("draft", 1, "recovery is in", False))
        self.assertIn("- Out: recovery by e-mail", self.plan_text(done))
        self.assertIsNone(envelope.get(self.plan_text(done), "spec_review"))
        self.assertEqual(done["checkpoint"]["iteration"], 1)

    def test_update_flags_a_planned_plan_and_never_rewrites_its_brief_or_steps(self):
        info = self.new()
        self.fill(info)
        self.add_steps(info)
        before = self.plan_text(info)
        done = self.run_json("update", "--what", "new requirement")
        self.assertTrue(done["flagged"])
        self.assertEqual((done["review"], done["review_due"], done["iteration"]), (1, True, 1))
        after = self.plan_text(done)
        self.assertEqual(envelope.set_key(after, "spec_review", None), before)
        self.assertIn("REVIEW DUE", self.run_spec("list")[1])
        self.assertEqual(self.run_json("update")["review"], 2, "the next update moves the flag to its round")
        cleared = self.run_json("reviewed")
        self.assertEqual((cleared["review"], cleared["review_due"]), (None, False))
        self.assertEqual(self.plan_text(cleared), before)

    def test_abandon_closes_an_unplanned_plan_but_refuses_a_planned_one(self):
        info = self.new()
        done = self.run_json("abandon")
        self.assertEqual((done["status"], done["state"]), ("abandoned", "abandoned"))
        self.assertEqual(self.run_spec("abandon")[0], 1)
        self.assertEqual(self.run_spec("update")[0], 1)
        self.assertEqual(self.run_spec("approve")[0], 1)
        other = self.new("Sync status")
        self.add_steps(other)
        code, _, err = self.run_spec("abandon")
        self.assertEqual(code, 1)
        self.assertIn("the plan has steps", err)
        self.assertEqual(envelope.get((self.root / other["spec"]).read_text(), "status"), "draft")

    def test_a_seed_is_linked_into_the_plan_and_marked_sent(self):
        shooter = self.root.parent / f"{self.root.name}-shooter"
        shooter.write_text(FAKE_SHOOTER)
        shooter.chmod(0o755)
        log = self.root.parent / f"{self.root.name}-log"
        env = {"HAL2_CLI_SHOOTER": str(shooter), "FAKE_LOG": str(log)}
        self.addCleanup(lambda: (shooter.unlink(missing_ok=True), log.unlink(missing_ok=True)))
        with mock.patch.dict(os.environ, env):
            info = self.run_json("new", "Passkey login", "--seed", "skill-spec#4")
        self.assertTrue(info["seed"]["marked"], info["seed"])
        self.assertIn("- Seed: skill-spec#4 (passkeys for login)", self.plan_text(info))
        self.assertIn("mark-sent skill-spec 4", log.read_text())

    def test_a_bad_seed_fails_before_a_number_is_taken(self):
        reserved = dict(spec.plan_number.reservations(self.root))
        code, _, err = self.run_spec("new", "Passkey login", "--seed", "nonsense")
        self.assertEqual(code, 2)
        self.assertIn("<seedbag>#<n>", err)
        self.assertEqual(spec.plan_number.reservations(self.root), reserved)
        self.assertFalse((self.root / "plans" / "0008-passkey-login").exists())

    def test_grilled_stamps_the_spec_and_its_plan(self):
        info = self.new()
        done = self.run_json("grilled", "--how", "autogrill x1")
        today = __import__("datetime").date.today().isoformat()
        self.assertEqual(done["grilled"], f"{today} (autogrill x1)")
        self.assertEqual(envelope.get(self.plan_text(info), "grilled"), f"{today} (autogrill x1)")
        self.assertEqual(self.run_json("grilled")["grilled"], today)

    def test_list_names_the_state_round_and_review(self):
        self.new()
        self.run_json("iterate")
        self.assertIn("0008-login-with-passkeys: draft, round 1, no design.html, plan spec", self.run_spec("list")[1])


if __name__ == "__main__":
    unittest.main()
