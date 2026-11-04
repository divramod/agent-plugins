"""Hal2 plan 0595 (D8, D9): `question add` refuses for a field with a plan; `question twins [--drop]` drops the farmer's
copies of a plan's questions. A temp repository and state, a stub for hal2-cli-plans; never the real farm."""

import json
import os
import stat
from unittest import mock

import question_twins
import questions
from test_questions import Base, OPEN_Q

PLAN = "0595-plan-gaps"
BODY = "Land it now?"
ASKED = f"Q9: {BODY}\n  a) (Recommended) yes — now\n  b) no — later\n  c) ask — wait"


class Twins(Base):
    def field(self, name, plan=PLAN, qs=()):
        path = self.slot(name)
        if plan:
            (path / "plans" / plan).mkdir(parents=True)
            (path / "plans" / plan / "plan.md").write_text("# Plan\n")
            (path / "plans" / "CURRENT_PLAN").write_text(plan + "\n")
            (path / "plans" / plan / "questions.md").write_text("# Questions\n" + "".join(qs))
        return path

    def stub(self, code=0):
        """A stand-in for hal2-cli-plans that logs its arguments."""
        self.log = self.dir / "cli.log"
        script = self.dir / "cli-stub"
        script.write_text(f'#!/bin/sh\necho "$@" >> "{self.log}"\nexit {code}\n')
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        patch = mock.patch.dict(os.environ, {"HAL2_CLI_PLANS": str(script)})
        patch.start()
        self.addCleanup(patch.stop)

    def setUp(self):
        super().setUp()
        self.folder.mkdir(parents=True)

    def load(self):
        return {e["n"]: e for e in questions.load(self.folder)}


class Refusal(Twins):
    def test_a_field_with_a_plan_is_refused_with_the_command_to_use(self):
        self.field("36")
        code, out, err = self.call("question", "add", "--slot", "36", "--text", "Q?: Why?")
        self.assertEqual((code, out), (2, ""))
        self.assertIn(f"hal2-cli-plans questions add", err)
        self.assertIn(f"--plan {PLAN}", err)
        self.assertIn(str(self.fields / "36"), err)
        self.assertEqual(self.load(), {})

    def test_the_farmer_a_field_without_a_plan_and_an_unknown_slot_keep_working(self):
        self.field("35", plan="")
        self.field("34")
        (self.fields / "34" / "plans" / "CURRENT_PLAN").write_text("shots/3/fix-it\n")  # a shot is no plan
        for slot in ("farmer", "35", "34", "99"):
            code, out, _ = self.call("question", "add", "--slot", slot, "--text", "Q?: Why?")
            self.assertEqual((code, out), (0, f"Q{len(self.load())} added for {slot}\n"), slot)

    def test_the_plan_name_forms(self):
        path = self.dir / "plain"
        (path / "plans").mkdir(parents=True)
        for text, want in (("0595-x\n", "0595-x"), ("plans/0595-x\n", "0595-x"), ("plans/0595-x/plan.md\n", "0595-x"),
                           ("shots/3/fix\n", ""), ("some-task\n", ""), ("", "")):
            (path / "plans" / "CURRENT_PLAN").write_text(text)
            self.assertEqual(question_twins.plan_of(path), want, text)


class Find(Twins):
    def setUp(self):
        super().setUp()
        self.field("36", qs=(OPEN_Q.format(n=86, text=BODY), OPEN_Q.format(n=87, text="Other?")))
        self.field("05", plan="")

    def test_the_same_stem_is_a_twin_whatever_the_number_case_or_spacing(self):
        questions.add(self.folder, "36", "Q7:  land IT now?\n  a) x — y")
        questions.add(self.folder, "36", "A different one?")
        questions.add(self.folder, "05", ASKED)  # a field without a plan: no twin
        questions.add(self.folder, "farmer", ASKED)
        code, out, _ = self.call("question", "twins")
        self.assertEqual(code, 0)
        self.assertEqual(out, f"36: farmer Q1 (open) = plan {PLAN} Q86 (open, by stem)\n")
        self.assertEqual(self.load()[1]["state"], "open")  # without --drop nothing changes

    def test_a_pair_names_a_twin_with_another_wording(self):
        questions.add(self.folder, "36", "Which wording is the farmer's?")
        data = json.loads(self.call("question", "twins", "--pair", "36:1=87", "--json")[1])
        self.assertEqual([(t["farmer_n"], t["plan_n"], t["how"]) for t in data["twins"]], [(1, 87, "pair")])
        self.assertEqual(self.call("question", "twins", "--pair", "36:1=99")[1], "no twins\n")  # no such plan question

    def test_a_bad_pair_is_one_line_exit_1(self):
        code, out, err = self.call("question", "twins", "--pair", "nonsense")
        self.assertEqual((code, out, err.count("\n")), (1, "", 1))

    def test_a_dropped_farmer_entry_is_no_twin(self):
        questions.add(self.folder, "36", ASKED)
        questions.close(self.folder, 1, "dropped")
        self.assertEqual(self.call("question", "twins")[1], "no twins\n")


class Drop(Twins):
    def setUp(self):
        super().setUp()
        self.stub()
        self.field("36", qs=(OPEN_Q.format(n=86, text=BODY),))

    def test_drop_closes_an_open_twin_with_the_link(self):
        questions.add(self.folder, "36", ASKED)
        questions.add(self.folder, "36", "Not a twin?")
        code, out, _ = self.call("question", "twins", "--drop")
        self.assertEqual(code, 0)
        self.assertIn("-> dropped", out)
        e = self.load()
        self.assertEqual((e[1]["state"], e[1]["answer"]), ("dropped", f"twin of {PLAN} Q86"))
        self.assertEqual(e[2]["state"], "open")
        self.assertFalse(self.log.exists())  # the plan's Q was open: nothing to answer
        self.assertEqual(self.call("question", "twins", "--drop")[1], "no twins\n")  # idempotent

    def test_a_twin_answered_only_on_the_farmer_side_answers_the_plan_first(self):
        questions.add(self.folder, "36", ASKED)
        questions.close(self.folder, 1, "answered", "yes, now")
        self.assertEqual(self.call("question", "twins", "--drop")[0], 0)
        self.assertEqual(self.log.read_text().split(), ["questions", "answer", "86", "yes,", "now", "--repo",
                                                        str(self.fields / "36"), "--plan", PLAN])
        e = self.load()[1]
        self.assertEqual((e["state"], e["answer"]), ("dropped", f"twin of {PLAN} Q86"))

    def test_a_failing_or_missing_cli_keeps_the_twin_and_says_so(self):
        questions.add(self.folder, "36", ASKED)
        questions.close(self.folder, 1, "answered", "yes")
        self.stub(code=2)
        code, _, err = self.call("question", "twins", "--drop")
        self.assertEqual(code, 1)
        self.assertIn("not dropped", err)
        self.assertEqual(self.load()[1]["state"], "answered")
        with mock.patch.object(question_twins, "cli", return_value=None):
            code, _, err = self.call("question", "twins", "--drop")
        self.assertEqual(code, 1)
        self.assertIn("not installed", err)
        self.assertEqual(self.load()[1]["state"], "answered")
