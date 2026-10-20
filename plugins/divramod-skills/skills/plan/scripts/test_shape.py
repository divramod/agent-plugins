"""shape.py, the plan skill's model of the one plan shape (hal2 plan 0376, row 7), on hal2-core's golden fixture
`code/rust/libs/hal2-core/tests/golden/plan-shape/`, read in place (never a copy): the overview is byte-equal to the
fixture's generated block, the written statuses are the derived ones, every file round trips, an unknown key the test
seeds itself is kept, and the fixture's ledgers (decisions, questions, handoffs) are ignored by the model."""
import os
import tempfile
import unittest
from pathlib import Path

import plan
import shape
import shape_overview as overview
from shape_docs import PlanStep, parse_step
from shape_front import Writer, Fields
from shape_names import ShapeError, StepRef


def fixture() -> Path | None:
    for folder in Path(__file__).resolve().parents:
        found = folder / "code/rust/libs/hal2-core/tests/golden/plan-shape"
        if found.is_dir():
            return found
    return None


ROOT = fixture()
LEDGERS = ("decisions.md", "questions.md", "handoff.md", "subplans/02-readers/handoff.md")


@unittest.skipUnless(ROOT, "the golden fixture is in the hal2 repository only")
class GoldenFixtureTest(unittest.TestCase):
    def setUp(self):
        self.files = shape.files(ROOT)
        self.plan_md = (ROOT / "plan.md").read_text()
        self.shape = shape.load(ROOT)

    def text_of(self, path: str) -> str:
        return (ROOT / path).read_text()

    def test_the_overview_is_byte_equal_to_the_fixtures_block(self):
        self.assertEqual(overview.render(self.shape), overview.written("plan.md", self.plan_md))

    def test_the_fixture_is_current(self):
        self.assertEqual(overview.regenerate(self.plan_md, self.shape), [])

    def test_a_stale_overview_and_status_are_written_as_the_fixture(self):
        start, end = overview.block("plan.md", self.plan_md)
        stale = (self.plan_md[:start] + "\n" + self.plan_md[end:]).replace("status: open", "status: done")
        self.assertEqual(overview.regenerate(stale, self.shape), [("plan.md", self.plan_md)])

    def test_a_stale_subplan_status_is_written_as_the_fixture(self):
        path = "subplans/99-uat/subplan.md"
        files = [(p, t.replace("status: blocked", "status: open") if p == path else t) for p, t in self.files]
        changed = overview.regenerate(self.plan_md, shape.Shape.from_files(files))
        self.assertEqual(changed, [(path, self.text_of(path))])

    def test_every_file_round_trips(self):
        seen = 0
        for sub in self.shape.subplans:
            self.assertEqual(sub.doc.render(), self.text_of(sub.file), sub.file)
            for step in sub.steps:
                self.assertEqual(step.doc.render(), self.text_of(step.file), step.file)
                seen += 1
        self.assertEqual(seen, 8)

    def test_an_unknown_key_seeded_here_round_trips_last(self):
        path = "subplans/01-model/steps/step-01.md"
        text = self.text_of(path).replace("\n---\n\n", "\nreviewer: arvid\n---\n\n", 1)
        self.assertNotEqual(text, self.text_of(path))
        step = parse_step(path, text, False)
        self.assertEqual(step.rest, [("reviewer", "arvid")])
        self.assertEqual(step.render(), text)

    def test_the_fixtures_ledgers_are_ignored(self):
        for name in LEDGERS:
            self.assertTrue((ROOT / name).is_file(), name)  # the fixture holds them, the model skips them
        read = [s.file for s in self.shape.subplans] + [st.file for s in self.shape.subplans for st in s.steps]
        self.assertEqual((len(read), set(read) & set(LEDGERS)), (11, set()))
        garbled = self.files + [(name, "not a record at all\n") for name in LEDGERS[:3]]
        garbled = [(p, "---\nbroken\n" if p == LEDGERS[3] else t) for p, t in garbled]
        self.assertEqual(shape.Shape.from_files(garbled), self.shape)

    def test_the_statuses_are_derived_from_the_steps(self):
        self.assertEqual([s.derived() for s in self.shape.subplans], ["done", "running", "blocked"])
        self.assertEqual(self.shape.derived(), "open")
        finished = [(p, t.replace("status: running", "status: done").replace("status: open", "status: dropped")
                     if p.startswith("subplans/02-") and "/steps/" in p else t) for p, t in self.files]
        finished = shape.Shape.from_files(finished)
        self.assertEqual(finished.derived(), "uat")
        self.assertEqual(finished.derived("abandoned"), "abandoned")

    def test_the_overview_is_read_as_a_step_table(self):
        steps = plan.read_steps(self.plan_md)
        self.assertEqual([s["number"] for s in steps], ["01.01", "01.02", "02.01", "02.02", "02.03"])
        self.assertEqual(sum(1 for s in steps if s["status"] == "done"), 3)
        self.assertIn("round trip | render", steps[0]["done_when"])

    def test_refs_resolve_in_the_fixture(self):
        with self.assertRaisesRegex(ShapeError, "ambiguous"):
            self.shape.resolve("3")
        self.assertEqual(self.shape.resolve("3", lead=2), StepRef(2, 3))
        self.assertEqual(self.shape.step(self.shape.resolve("02.03")).doc.title, "Python readers")
        self.assertIsNone(self.shape.step(StepRef(2, 9)))
        self.assertEqual(str(StepRef(1, 104)), "01.104")

    def test_a_step_without_its_subplan_is_refused(self):
        with self.assertRaisesRegex(ShapeError, "no `subplan.md`"):
            shape.Shape.from_files([(p, t) for p, t in self.files if "/steps/" in p])

    def test_long_cells_are_cut_and_bars_escaped(self):
        self.assertEqual(overview.cell(" a | b "), "a \\| b")
        cut = overview.cell("x" * 205)
        self.assertEqual((len(cut), cut[-1]), (200, "…"))
        self.assertEqual(overview.cell("y" * 200), "y" * 200)


class FrontMatterTest(unittest.TestCase):
    def test_written_values_read_back_unchanged(self):
        rest = [("a", "x: y"), ("b", ["rust:c", "@vm", "docs"]), ("c", {"k": "v w"}), ("d", None), ("e", "12"),
                ("f", 7)]
        text = Writer("T").quoted("title", 'say "hi"').text("who", "field 07").rest(rest).finish("body\n")
        self.assertIn('b: ["rust:c", "@vm", docs]\n', text)
        fields, body = Fields.read("f", text, "T")
        self.assertEqual((body, fields.text("title"), fields.text("who")), ("body\n", 'say "hi"', "field 07"))
        self.assertEqual(fields.rest, rest)

    def test_a_wrong_kind_schema_or_value_is_refused(self):
        text = "---\ntype: Subplan\nschema: 2\n---\n"
        with self.assertRaisesRegex(ShapeError, "schema"):
            Fields.read("f", text, "Subplan")
        with self.assertRaisesRegex(ShapeError, "not a"):
            Fields.read("f", text, "Plan Step")
        step = PlanStep("t", "d", "open", 1, 1).render()
        with self.assertRaisesRegex(ShapeError, "StepStatus"):
            parse_step("s", step.replace("status: open", "status: later"), False)
        with self.assertRaisesRegex(ShapeError, "is a `Plan Step`"):
            parse_step("s", step, True)


class CliFallbackTest(unittest.TestCase):
    """`hal2-cli-plans overview` is used when the binary has it, else shape.py's own render."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bin = Path(self.tmp.name)
        self.env = os.environ.get(shape.CLI_ENV)
        shape.cli_has_overview.cache_clear()

    def tearDown(self):
        os.environ.pop(shape.CLI_ENV, None)
        if self.env is not None:
            os.environ[shape.CLI_ENV] = self.env
        shape.cli_has_overview.cache_clear()
        self.tmp.cleanup()

    def fake(self, body: str) -> Path:
        path = self.bin / "hal2-cli-plans"
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)
        os.environ[shape.CLI_ENV] = str(path)
        return path

    def test_an_older_binary_without_overview_is_not_used(self):
        self.fake('echo "unknown command" >&2; exit 2\n')
        self.assertIsNone(shape.cli())

    def test_a_stub_that_answers_anything_is_not_used(self):
        self.fake('echo \'{"store": "x", "problems": []}\'\nexit 0\n')  # qstub's questions stub
        self.assertIsNone(shape.cli())

    def test_a_missing_binary_is_not_used(self):
        os.environ[shape.CLI_ENV] = str(self.bin / "none")
        self.assertIsNone(shape.cli())

    def test_a_binary_with_overview_writes_it(self):
        log = self.bin / "calls"
        self.fake(f'echo "$@" >> {log}\n[ "$2" = --help ] && echo "Usage: overview <plan> [--write]"\nexit 0\n')
        self.assertTrue(shape.write_by_cli(Path("/repo"), Path("/repo/plans/0001-x")))
        self.assertEqual(log.read_text().splitlines(), ["overview --help", "overview 0001-x --repo /repo --write"])


if __name__ == "__main__":
    unittest.main()
