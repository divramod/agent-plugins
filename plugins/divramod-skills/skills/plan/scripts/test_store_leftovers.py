"""The plan skill's store-home leftovers of hal2 plan 0409 (step 13), each on a scratch farm whose plans live in its
plan store: `new --masterplan` picks its crop from the store's masterplans (no other field's `plans/` glob), and
`convert` turns a schema-1 plan of the store into the one shape on a view (render, convert, apply), nothing staged
and nothing in the tree; a landing's sync trigger marks the fragments its CHANGELOG.md took in (`fragment.landed`). Runs this checkout's debug build of hal2-cli-plans (skipped without)."""

import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import test_convert  # noqa: E402
from store_testkit import DEBUG, StoreFarm  # noqa: E402

PLAN = HERE / "plan.py"
CHANGELOG_CLI = DEBUG.with_name("hal2-cli-changelog") if DEBUG else None  # this checkout's debug build beside it
FRAGMENT = ("---\ntype: Changelog\nschema: 1\nplan: 1\ntitle: Changelog of plan 0001\ndescription: What plan 0001 "
            "changes for the people using hal2.\nstatus: active\n---\n\n# Changelog of plan 0001\n\n## Added\n\n"
            "- `x`: a page.\n")
# A hal2-cli-records new enough that convert runs its records check (0.7.0): no problem found.
RECORDS = "#!/bin/sh\ncase \"$1\" in --version) echo 'hal2-cli-records 0.7.0';; *) echo '{\"problems\": []}';; esac\n"


@unittest.skipUnless(DEBUG, "no hal2-cli-plans with the store home (cargo build -p hal2-cli-plans)")
class StoreLeftovers(StoreFarm, unittest.TestCase):
    def plan(self, *args: str) -> dict:
        return json.loads(self.run_ok(sys.executable, str(PLAN), *args))

    def test_a_new_masterplans_crop_is_the_first_the_stores_masterplans_leave(self):
        first = self.plan("new", "First season", "--masterplan", "--no-current")
        second = self.plan("new", "Second season", "--masterplan", "--no-current")
        self.assertEqual((first["crop"], second["crop"]), ("wheat", "corn"))
        self.assert_clean()

    def test_convert_turns_a_schema_1_plan_of_the_store_into_the_one_shape(self):
        records = self.tmp / "hal2-cli-records"
        records.write_text(RECORDS)
        records.chmod(records.stat().st_mode | stat.S_IEXEC)
        patch = mock.patch.dict(os.environ, {"HAL2_CLI_RECORDS": str(records)})
        patch.start()
        self.addCleanup(patch.stop)
        test_convert.write(self.repo, "0002-record-sample", {"plan.md": test_convert.RECORD})
        self.assertEqual(self.cli("import")["report"]["plans"], 1)
        shutil.rmtree(self.repo / "plans")
        self.assertEqual(self.rendered("2"), ["plan.md"])
        out = self.plan("convert", "2", "--json")
        self.assertEqual(out["converted"], 1, out)
        self.assertEqual(out["plans"][0]["records"], "records checked by the plan store when the view is applied")
        files = self.rendered("2")
        self.assertIn("subplans/01-record-sample/steps/step-05.md", files)
        self.assertIn("schema: 2", (self.tmp / "check" / "0002-record-sample" / "plan.md").read_text())
        self.assertEqual(self.plan("convert", "2", "--json")["skipped"], 1, "idempotent")
        self.assert_clean()

    @unittest.skipUnless(CHANGELOG_CLI and CHANGELOG_CLI.is_file(), "no hal2-cli-changelog beside hal2-cli-plans")
    def test_the_landing_trigger_marks_the_fragments_its_changelog_took_in(self):
        patch = mock.patch.dict(os.environ, {"HAL2_CLI_CHANGELOG": str(CHANGELOG_CLI)})
        patch.start()
        self.addCleanup(patch.stop)
        self.cli("new", "A plan", "--no-current")
        view = self.tmp / "view"
        self.cli("render", "1", "--to", str(view))
        (view / "0001-a-plan" / "changelog.md").write_text(FRAGMENT)
        self.cli("apply", str(view))
        generated = json.loads(self.run_ok(str(CHANGELOG_CLI), "generated", "--rev", "HEAD"))
        text = generated["files"]["CHANGELOG.md"]
        self.assertIn("- `x`: a page. (0001)", text)
        self.assertNotIn("(plans/", text)
        (self.repo / "CHANGELOG.md").write_text(text)
        self.git("add", "CHANGELOG.md")
        self.git("commit", "-q", "-m", "landed")
        import planread  # noqa: E402  (the plan skill's own, on sys.path)
        done = planread.sync(self.repo, "landing")
        self.assertEqual((done or {}).get("fragments_landed"), ["0001-a-plan"], done)
        head = self.git("rev-parse", "HEAD").strip()
        farm = self.git("config", "--get", "hal.farm").strip()
        with sqlite3.connect(self.tmp / "data" / "plans" / f"{farm}.db") as db:
            self.assertEqual(db.execute("SELECT landed FROM fragment").fetchall(), [(head,)])


if __name__ == "__main__":
    unittest.main()
