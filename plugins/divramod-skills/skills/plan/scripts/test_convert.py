"""`plan.py convert` on one fixture per input kind of design §7 (hal2 plan 0376, row 10): a legacy plan (envelope from
its lines, legacy.md, ledgers, its step file moved and folded, links re-pointed, no uat.md: an empty 99-uat), a record
plan of schema 1 (`## Steps` into `## Overview`, the status mapping), a parallel plan (waves from Needs, touches,
`schedule: waves`), a uat.md with uat-results.jsonl (99-uat steps with their verdicts) and an archived uat.md."""
import json
import unittest
from pathlib import Path

import envelope
import shape
from shape_testing import TempPlan

DONE_ROWS = "| # | Step | Done when | Status |\n|---|---|---|---|\n| 1 | First | `true` passes | done |\n"
LEGACY = """# Plan 0001: Legacy sample

Landing: auto

Grilled: 2026-09-26

Finished: 2026-09-27

Created 2026-09-26. `plans/CURRENT_PLAN` names the active plan; helper files for this plan live next to this file.

## Goal

The legacy sample converts. It has two steps.

## Context

- [design](design.md).

## Steps

Each step is detailed when it is next.

| # | Step | Done when | Status |
|---|---|---|---|
| 1 | First | `true` passes | done |
| 2 | Second, see [design](design.md) | `true` again | done (shipped early) |

## Decisions

- 2026-09-26: kept verbatim.
"""
STEP_2 = """# Step 2: Second

<!-- Short and concise (hal2's record plans-short-and-concise): at most 120 lines; link the research, records and
code instead of repeating them. Status and who stay in plan.md's step table; the step's end adds `## Notes`. -->

## Task

Do it; read [the design](../design.md).

## Needs and touches

Needs 1.

Size: 100k of 1m
Done when: `true` again

## Notes

- noted.
"""
RECORD = """---
type: Plan
schema: 1
id: 2
title: "record sample"
description: "A record plan of schema 1."
status: open
landing: auto
run: claude-opus-5-5 medium 1m
created: 2026-10-01
---

# Plan 0002: record sample

## Goal

A record plan of schema 1 converts.

## Context

- none.

## Steps

One line per step.

| # | Step | Done when | Model | Effort | Window | Size | Status |
|---|---|---|---|---|---|---|---|
| 1 | Done one | `a` | opus | high | 1m | 100k | done |
| 2 | Blocked one | `b` | opus | high | 1m | 100k | blocked waits for the hub |
| 3 | Dropped one | `c` | opus | high | 1m | 100k | dropped |
| 4 | Odd one | `d` | sonnet | medium | 1m | 100k | wobbly |
| 5 | Next one | `e` | opus | high | 1m | 100k | next |

## Pre-authorized

- none: the plan needs no user-only decision
"""
PARALLEL = """# Plan 0003: Parallel sample

## Goal

A parallel plan converts into waves.

## Context

- none.

## Steps

| # | Step | Needs | Touches | Who | Done when | Status |
|---|---|---|---|---|---|---|
| 1 | A | - | rust:a | lead | `a` | done |
| 2 | B | - | rust:a | subagent | `b` | done |
| 3 | C | 1 | ts:b | | `c` | done |
| 4 | D | 2, 3 | docs | | `d` | done |
"""
UAT = """---
type: UAT
schema: 1
title: "uat sample"
description: "The checks of plan 0004."
status: {status}
plan: 4
created: 2026-10-01
shotfile: sample
---

# UAT 0004: uat sample

Before you start: main installed.

<!-- Checks only a human can do. The verdicts go to uat-results.jsonl beside this file, never into it. -->

## U1 The first check
Priority: p1
Tags: smoke, regression
Kind: scripted
Open: hal9k://plans

Steps:
1. Look.

Expected: it shows.

## U2 The second check
Priority: p3
Kind: manual

Expected: the second shows.
"""
RESULT = {"check": "U1", "note": "", "commit": "672e0b5abc", "uat_version": "sha256:a2ffae0c99", "by": "cli"}


def legacy_plan(title: str, rows: str = DONE_ROWS, extra: str = "") -> str:
    return f"# Plan 0004: {title}\n\n## Goal\n\n{title} converts.\n\n## Context\n\n- none.\n{extra}\n## Steps\n\n{rows}"


def write(root: Path, slug: str, files: dict) -> Path:
    folder = root / "plans" / slug
    for name, content in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(content)
    return folder


def legacy_files() -> dict:
    return {"plan.md": LEGACY, "steps/2.md": STEP_2, "design.md": "Row 2: [steps/2.md](steps/2.md), steps/2.md.\n"}


class ConvertKindsTest(TempPlan):
    def convert(self, *slugs) -> dict:
        return self.plan("convert", *slugs, "--json")

    def test_legacy(self):
        folder = write(self.root, "0001-legacy-sample", legacy_files())
        self.commit_all()
        out = self.convert("0001")
        self.assertEqual(out["converted"], 1, out)
        plan = (folder / "plan.md").read_text()
        for key, value in (("schema", 2), ("landing", "auto"), ("status", "done"), ("finished", "2026-09-27"),
                           ("grilled", "2026-09-26"), ("created", "2026-09-26"), ("title", "Legacy sample")):
            self.assertEqual(envelope.get(plan, key), value, key)
        self.assertIn("## Overview", plan)
        self.assertIn("[legacy.md](legacy.md)", plan)
        self.assertNotIn("## Decisions", plan)
        self.assertIn("## Decisions\n\n- 2026-09-26: kept verbatim.", (folder / "legacy.md").read_text())
        self.assertEqual(envelope.get((folder / "decisions.md").read_text(), "status"), "closed")
        step = (folder / "subplans/01-legacy-sample/steps/step-02.md").read_text()
        self.assertFalse((folder / "steps").exists())
        self.assertIn("# Step 02: Second\n", step)
        self.assertNotIn("Size:", step)
        self.assertNotIn("\n## Needs and touches", step)
        self.assertIn("## Notes\n\n- noted.\n\n### Needs and touches\n\nNeeds 1.", step)
        self.assertIn("[the design](../../../design.md)", step)
        self.assertEqual(envelope.get(step, "why"), "(shipped early)")
        new = "subplans/01-legacy-sample/steps/step-02.md"
        self.assertEqual((folder / "design.md").read_text(), f"Row 2: [{new}]({new}), {new}.\n")
        self.assertEqual(shape.load(folder).uat().derived(), "done")
        self.assertIn("plans/0001-legacy-sample/steps/2.md", self.git("diff", "--cached", "-M", "--name-status"))

    def test_record_schema_1_and_the_status_mapping(self):
        folder = write(self.root, "0002-record-sample", {"plan.md": RECORD})
        out = self.convert("0002")
        self.assertEqual(out["plans"][0]["notes"], ["row 4: status `wobbly` is none known: open"])
        plan = (folder / "plan.md").read_text()
        self.assertEqual((envelope.get(plan, "schema"), envelope.get(plan, "status")), (2, "open"))
        self.assertEqual(envelope.get(plan, "run"), "claude-opus-5-5 medium 1m")
        self.assertNotIn("## Steps", plan)
        self.assertLess(plan.index("## Overview"), plan.index("## Pre-authorized"))
        steps = shape.load(folder).work()[0].steps
        self.assertEqual([(s.doc.status, s.doc.why) for s in steps],
                         [("done", None), ("blocked", "waits for the hub"), ("dropped", "dropped"), ("open", None),
                          ("next", None)])
        self.assertEqual(steps[3].doc.model, "sonnet")
        self.assertIn("| 01.05 | [Next one]", plan)

    def test_parallel_plan_into_waves(self):
        folder = write(self.root, "0003-parallel-sample", {"plan.md": PARALLEL})
        self.convert("0003")
        sub = shape.load(folder).work()[0]
        self.assertEqual(sub.doc.schedule, "waves")
        self.assertEqual([s.doc.wave for s in sub.steps], [1, 2, 2, 3])
        self.assertEqual([s.doc.touches for s in sub.steps], [["rust:a"], ["rust:a"], ["ts:b"], ["docs"]])
        self.assertNotIn("lead", (folder / sub.steps[0].file).read_text())

    def test_uat_md_with_results(self):
        results = [{**RESULT, "status": "pass", "at": "2026-10-02T10:00:00+02:00", "note": 'ok "now"'},
                   {**RESULT, "status": "fail", "at": "2026-10-01T10:00:00+02:00", "step": 1, "duration": 30}]
        folder = write(self.root, "0004-uat-sample", {
            "plan.md": legacy_plan("Uat sample"), "uat.md": UAT.format(status="active"),
            "uat-results.jsonl": "".join(json.dumps(r) + "\n" for r in results)})
        out = self.convert("0004")
        self.assertEqual((out["plans"][0]["checks"], out["plans"][0]["verdicts"]), (2, 2))
        self.assertFalse((folder / "uat.md").exists() or (folder / "uat-results.jsonl").exists())
        uat = shape.load(folder).uat()
        self.assertEqual(uat.doc.shotfile, "sample")
        self.assertIn("## Before you start\n\nmain installed.", (folder / uat.file).read_text())
        one, two = (s.doc for s in uat.steps)
        self.assertEqual((one.check, one.priority, one.tags, one.verdict, one.status),
                         ("U1", "p1", ["smoke", "regression"], "pass", "done"))
        self.assertIn("## Verdicts\n\n- 2026-10-01T10:00:00+02:00 · fail · by cli · at 672e0b5 · v a2ffae0c · step 1 · "
                      "30s\n- 2026-10-02T10:00:00+02:00 · pass · by cli · at 672e0b5 · v a2ffae0c — \"ok 'now'\"\n",
                      one.body)
        self.assertNotIn("Priority:", one.body)
        self.assertEqual((two.check, two.kind, two.status, two.verdict), ("U2", "scripted", "open", None))
        self.assertIn("Kind: manual", two.body)
        self.assertEqual(envelope.get((folder / "plan.md").read_text(), "status"), "uat")

    def test_archived_uat_drops_its_checks(self):
        folder = write(self.root, "0004-uat-sample", {"plan.md": legacy_plan("Uat sample"),
                                                      "uat.md": UAT.format(status="archived")})
        self.convert("0004")
        self.assertEqual([s.doc.status for s in shape.load(folder).uat().steps], ["dropped", "dropped"])
        self.assertEqual(envelope.get((folder / "plan.md").read_text(), "status"), "done")

    def test_a_result_of_no_check_puts_the_plan_back(self):
        folder = write(self.root, "0004-uat-sample", {
            "plan.md": legacy_plan("Uat sample"), "uat.md": UAT.format(status="active"),
            "uat-results.jsonl": json.dumps({**RESULT, "check": "U9", "status": "pass", "at": "x"}) + "\n"})
        result = self.run_plan("convert", "0004")
        self.assertEqual(result.returncode, 1)
        self.assertIn("failed 0004-uat-sample: ShapeError: uat-results.jsonl line 1 names check `U9`", result.stdout)
        self.assertTrue((folder / "uat.md").is_file())
        self.assertFalse((folder / "subplans").exists())


if __name__ == "__main__":
    unittest.main()
