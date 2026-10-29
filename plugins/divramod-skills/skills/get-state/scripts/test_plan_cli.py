"""The foreman page through `hal2-cli-plans --json` (hal2 plan 0409 step 6): a plan the CLI answers for is shown with no
file under plans/ (the store home), its plan store's state (sync off and why, a locked gpg agent, conflicts) as a
section; and, when this checkout's debug build of the CLI is there, the same end to end on a real store."""

import os
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import plan_cli
import state
import views
from test_state import Fixture

REAL_RUN = plan_cli.run  # before a fixture's setUp mocks it

STEPS = [{"number": "1", "step": "one", "done_when": "x", "status": "done"},
         {"number": "2", "step": "two", "done_when": "x", "status": "next"},
         {"number": "3", "step": "after", "done_when": "after the landing: y", "status": ""}]
ROOT = Path(__file__).resolve().parents[8]
DEBUG = ROOT / "code/rust/target/debug" / ("hal2-cli-plans.exe" if os.name == "nt" else "hal2-cli-plans")


def answers(args: list[str]):
    """The CLI as a farm with plan 0042 in its store: show, open questions, home and state status."""
    if args[0] == "show":
        return {"title": "the answer", "goal": "What 42 brings in.", "landing": "auto", "steps": STEPS}
    if args[:2] == ["questions", "list"]:
        return {"entries": [{"n": 4, "question": "Which  bucket?", "state": "open"}]}
    if args[0] == "home":
        return {"home": "store", "farm": "f-1", "store": "/data/plans/f-1.db", "plans": 1}
    if args[:2] == ["state", "status"]:
        return {"sync": "off", "why": "no GPG key for secrets", "locked": True, "conflicts": 2, "unsynced": 3}
    return None


class PlanCli(Fixture):
    def page(self, field: str = "02"):
        data = state.collect(str(self.main))
        ctx = {"repo": "proj", "checkout": field, "top": str(self.wt / field), "main": str(self.main)}
        return views.build("foreman", data, ctx)

    def test_a_store_plan_is_shown_without_its_files(self):
        shutil.rmtree(self.plan_dir)
        self.mock(plan_cli, "run", answers)
        title, sections = self.page()
        by = {s["heading"]: s for s in sections}
        self.assertEqual(list(by), ["the answer", "Progress", "Steps", "Next step", "Open questions", "Plan store"])
        self.assertEqual(by["the answer"]["items"][:2], ["What 42 brings in.", "Landing: auto (wait)"])
        self.assertEqual(by["Progress"]["bar"], [1, 3])
        self.assertEqual(by["Next step"]["text"], "2: two Done when: x")
        self.assertEqual(by["Open questions"]["items"], ["Q4: Which bucket?"])
        self.assertEqual(by["Plan store"]["items"], [
            "Home: store (farm f-1)", "Sync: off: no GPG key for secrets",
            "The gpg agent is locked: unlock it, a sync waits for it", "Conflicts: 2 (hal2-cli-plans conflicts)"])

    def test_a_farm_without_a_store_has_no_store_section(self):
        self.mock(plan_cli, "run", lambda args: answers(args) if args[0] != "home" else {"home": "files", "store": None})
        by = {s["heading"]: s for s in self.page()[1]}
        self.assertNotIn("Plan store", by)
        self.assertEqual(by["Steps"]["rows"][2][:2], ["3", "after"])

    def test_an_unreadable_answer_falls_back_to_the_files(self):
        self.mock(plan_cli, "run", lambda args: {"steps": "garbage"} if args[0] == "show" else None)
        by = {s["heading"]: s for s in self.page()[1]}
        self.assertEqual(by["Progress"]["bar"], [1, 3])
        self.assertIn("Plan 0042: the answer", by)


@unittest.skipUnless(DEBUG.is_file(), "no debug build of hal2-cli-plans in this checkout (cargo build -p hal2-cli-plans)")
class StorePlanEndToEnd(Fixture):
    """The real CLI on a scratch data root: the fixture's plan imported into its store, `home store`, the plan folder
    removed; `/s` shows the store's plan."""

    def setUp(self):
        super().setUp()
        env = {"HAL2_CLI_PLANS": str(DEBUG), "HAL2_DATA_ROOT": str(self.tmp / "data"),
               "HAL2_STATE_DIR": str(self.tmp / "hal-state"), "HAL2_CONFIG_DIR": str(self.tmp / "config")}
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)
        self.mock(plan_cli, "run", REAL_RUN)

    def cli(self, *args: str) -> None:
        done = subprocess.run([str(DEBUG), *args], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_the_foreman_page_shows_a_store_plan(self):
        top = str(self.wt / "02")
        self.cli("import", "--from", top, "--json")
        self.cli("home", "store", "--repo", top, "--json")
        shutil.rmtree(self.plan_dir)
        title, sections = views.build("foreman", state.collect(str(self.main)),
                                      {"repo": "proj", "checkout": "02", "top": top, "main": str(self.main)})
        by = {s["heading"]: s for s in sections}
        self.assertEqual(by["Progress"]["bar"], [1, 3], sections)
        self.assertEqual([r[:2] for r in by["Steps"]["rows"]], [["1", "one"], ["2", "two"], ["3", "three"]])
        self.assertEqual(by["Plan store"]["items"][0].split(" (")[0], "Home: store")
        self.assertTrue(by["Plan store"]["items"][1].startswith("Sync: off"), by["Plan store"])
        self.assertTrue((self.tmp / "data/plans").is_dir(), "the store is the scratch data root's")


if __name__ == "__main__":
    unittest.main()
