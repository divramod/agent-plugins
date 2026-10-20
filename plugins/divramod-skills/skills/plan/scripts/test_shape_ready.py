"""`plan.py ready` on the one plan shape (hal2 plan 0376, row 8, design §2 A5, D19): both levels by `schedule`,
touches and the machine resources, 99-uat never ready, D19's who; and `prompt <ref>`, the hand's Agent call from the
step file. On a temp repository and on hal2-core's golden fixture, read in place."""
import unittest

import shape_ready
from shape_testing import TempPlan, fixture

ROOT = fixture()


class ReadyTest(TempPlan):
    def test_serial_one_subplan_is_the_foremans_and_its_first_step_a_hand(self):
        self.new("deploy the hub")
        info = self.plan("ready", "--json")
        self.assertEqual((info["schedule"], info["wave"]), ("serial", 1))
        self.assertEqual(info["subplans"]["ready"], [{"id": "01-deploy-the-hub", "wave": 1, "touches": [],
                                                       "who": "foreman"}])
        steps = info["steps"]["01-deploy-the-hub"]
        self.assertEqual([s["ref"] for s in steps["ready"]], ["01.01"])
        self.assertEqual(steps["waiting"], [{"ref": "01.02", "why": "serial: waits for 01.01"}])
        self.assertIn("step\t01.01\t<step>", self.run_plan("ready").stdout)

    def test_waves_give_each_ready_subplan_a_servant(self):
        folder = self.new("deploy the hub")
        self.set_plan_key(folder, "schedule", "waves")
        self.plan("subplan", "new", "cli")
        self.plan("subplan", "new", "gui", "--wave", "2")
        self.plan("subplan", "new", "convert")
        info = self.plan("ready", "--json")["subplans"]
        self.assertEqual([e["id"] for e in info["ready"]], ["01-deploy-the-hub"])
        self.assertEqual(info["waiting"][0], {"id": "02-cli", "why": "wave 2 waits for wave 1"})
        for ref in ("01.01", "01.02"):
            self.plan("status", ref, "done")
        info = self.plan("ready", "--json")
        ready = info["subplans"]["ready"]
        self.assertEqual(([e["id"] for e in ready], {e["who"] for e in ready}), (["02-cli", "03-gui"], {"servant"}))
        self.assertIn('create.py --from 30 --lead "07 0001-deploy-the-hub 02-cli"', ready[0]["command"])
        self.assertEqual(info["steps"], {})

    def test_touches_and_machine_resources(self):
        folder = self.new("deploy the hub")
        self.set_plan_key(folder, "schedule", "waves")
        for title in ("cli", "gui", "docs"):
            self.plan("subplan", "new", title, "--wave", "1")
        self.edit_subplan(folder, 1, touches=["@land"])
        self.edit_subplan(folder, 2, touches=["@land"])
        self.edit_subplan(folder, 3, touches=["@vm"])
        self.edit_subplan(folder, 4, touches=["@vm"])
        info = self.plan("ready", "--json")["subplans"]
        self.assertEqual([e["id"] for e in info["ready"]], ["01-deploy-the-hub", "03-gui", "04-docs"])
        self.assertEqual(info["waiting"], [{"id": "02-cli", "why": "`@land` is held by a running item"}])
        self.assertEqual(len(self.plan("ready", "--json", "--limit", "1")["subplans"]["ready"]), 1)

    def test_a_running_subplan_holds_the_foreman_and_its_wave_steps_are_parallel_hands(self):
        folder = self.new("deploy the hub")
        self.edit_subplan(folder, 1, schedule="waves")
        self.plan("step", "add", "1", "Third", "--wave", "1", "--size", "60k")
        self.plan("status", "01.01", "running")
        info = self.plan("ready", "--json")
        self.assertEqual(info["subplans"]["running"], [{"id": "01-deploy-the-hub", "status": "running", "who": None}])
        steps = info["steps"]["01-deploy-the-hub"]
        self.assertEqual(([s["ref"] for s in steps["ready"]], [s["ref"] for s in steps["running"]]),
                         (["01.03"], ["01.01"]))
        self.assertEqual(steps["waiting"], [{"ref": "01.02", "why": "wave 2 waits for wave 1"}])

    def test_99_uat_waits_for_the_landing(self):
        self.new("deploy the hub")
        self.plan("uat", "add", "The hub answers")
        for ref in ("01.01", "01.02"):
            self.plan("status", ref, "done")
        info = self.plan("ready", "--json")
        self.assertEqual(info["subplans"]["ready"], [])
        self.assertEqual(info["subplans"]["waiting"][0]["id"], "99-uat")

    def test_a_servant_sees_its_subplans_steps(self):
        folder = self.new("deploy the hub")
        self.plan("subplan", "new", "cli")
        self.plan("step", "add", "2", "Parse", "--size", "60k")
        self.edit_subplan(folder, 2, who="field 31")
        (self.root / "plans/LEAD").write_text("07 0001-deploy-the-hub 02-cli\n")
        self.assertEqual(list(self.plan("ready", "--json")["steps"]), ["02-cli"])


class PromptTest(TempPlan):
    def test_prompt_builds_the_hands_call_from_the_step_file(self):
        self.new("deploy the hub", "--goal", "The hub runs.")
        call = self.plan("prompt", "01.02")
        self.assertTrue(call["description"].startswith("Plan 0001 row 01.02: Write the UATs"), call["description"])
        self.assertEqual((call["model"], call["effort"], call["run_in_background"]), ("sonnet", "medium", True))
        for text in ("step 01.02 of plan 0001", "Task:\nThe user acceptance tests", "Size: 100k of 1m",
                     "Sub-plan 01-deploy-the-hub", "Deliverable: The hub runs.", "01.01 <step>",
                     "subplans/01-deploy-the-hub/steps/step-02.md"):
            self.assertIn(text, call["prompt"])
        self.assertIn("Plan 0001 row 01.02 part 2:", self.plan("prompt", "01.02", "--part", "2")["description"])

    def test_prompt_refuses_an_unwritten_task_an_unsized_step_and_a_bare_number(self):
        folder = self.new("deploy the hub")
        self.assertIn("no written `## Task`", self.refused("prompt", "01.01"))
        self.edit_step(folder, "01.02", size="500k")
        self.assertIn("plan-steps-sized", self.refused("prompt", "01.02"))
        self.assertIn("no ref", self.refused("prompt", "2"))


@unittest.skipUnless(ROOT, "the golden fixture is in the hal2 repository only")
class GoldenReadyTest(unittest.TestCase):
    def test_ready_on_the_fixture(self):
        info = shape_ready.ready(ROOT.parent, ROOT)
        self.assertEqual((info["schedule"], info["wave"], info["steps"]), ("waves", 2, {}))
        self.assertEqual(info["subplans"]["running"], [{"id": "02-readers", "status": "running", "who": "field 31"}])
        self.assertEqual(info["subplans"]["ready"], [])
        self.assertEqual([w["id"] for w in info["subplans"]["waiting"]], ["99-uat"])


if __name__ == "__main__":
    unittest.main()
