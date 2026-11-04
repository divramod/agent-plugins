# Holds the record `one-continue`.
"""`/continue`'s code part (plan 0593 step 8; plan 0592's D3, D12-D18): one fixture per role (its handoff by the one
resolver and its way), the pause record, the restock rule, the empty since report's fast path and `/continue all`."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import continue_testkit as kit  # noqa: E402
import foremen  # noqa: E402
import since_check  # noqa: E402

GATHER = __import__("importlib").import_module("continue")  # `continue` is a keyword: no plain import


def run(*args, env=None, stdin=""):
    return subprocess.run([sys.executable, str(HERE / "continue.py"), *args], capture_output=True, text=True,
                          env={**os.environ, **(env or {})}, input=stdin)


class Roles(unittest.TestCase):
    """Each role's handoff and way; hal2's rule first (fake CLI), the folder rule without it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.farm = kit.Farm(cls.tmp / "farm")
        cls.foreman = cls.farm.field("07", plan="0001-x")
        cls.servant = cls.farm.field("31", plan="0001-x", lead="07 0001-x 3")
        cls.farmer = cls.farm.field("farmer-app")
        cls.tollman = cls.farm.field("tollman-app")
        cls.train = cls.farm.field("tollman-train-0574")
        cls.fakes = cls.tmp / "fakes"
        cls.env = kit.fakes(cls.fakes)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def setUp(self):
        shutil.rmtree(self.fakes / "role", True)
        shutil.rmtree(self.fakes / "since", True)
        patch = mock.patch.dict(os.environ, {**self.env, "PAUSE_ROOT": str(self.tmp / "pause"),
                                             "HAL_VILLAGE": str(self.tmp / "village"),
                                             "HAL_CITY": str(self.tmp / "city"), "HAL_PLANET": str(self.tmp / "planet")})
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("FARMER_DIR", None)

    def gather(self, path, role=None, lead=None):
        if role != "fallback":
            kit.answer(self.fakes, f"role/{Path(path).name}.json", kit.role_doc(Path(path), role, lead=lead))
        return GATHER.gather(Path(path))

    def test_foreman_continues_its_plan_from_the_plan_s_handoff(self):
        doc = self.gather(self.foreman, "foreman")
        self.assertEqual(doc["role"]["source"], "cli")
        self.assertEqual(doc["handoff"]["found"], str(self.foreman / "plans/0001-x/handoff.md"))
        self.assertEqual(doc["handoff"]["form"], "record")
        self.assertEqual(doc["way"]["load"], "/foreman duties")
        self.assertEqual(doc["way"]["way"], "plan")
        self.assertEqual(doc["check"]["plan"], "0001-x")

    def test_servant_continues_its_step_from_the_root_handoff(self):
        lead = {"field": "07", "plan": "0001-x", "step": "3"}
        (self.servant / "HANDOFF.md").write_text("# Handoff\n")
        self.addCleanup((self.servant / "HANDOFF.md").unlink)
        doc = self.gather(self.servant, "servant", lead=lead)
        self.assertEqual(doc["handoff"]["found"], str(self.servant / "HANDOFF.md"))
        self.assertEqual(doc["handoff"]["form"], "legacy")
        self.assertEqual((doc["way"]["load"], doc["way"]["way"]), ("/servant duties", "lead-step"))
        self.assertIn("step 3 of 0001-x for the foreman of field 07", doc["way"]["then"])
        self.assertEqual(doc["check"]["plan"], "0001-x")  # the foreman's plan is checked

    def test_farmer_reads_its_role_folder_s_handoff_then_its_wake_items(self):
        folder = self.farmer / "roles" / "farmer"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "owner-handoff.md").write_text("old\n")
        doc = self.gather(self.farmer, "farmer")
        self.assertEqual(doc["handoff"]["file"], str(folder / "handoff.md"))
        self.assertEqual(doc["handoff"]["found"], str(folder / "owner-handoff.md"))  # the old place, as a fallback
        self.assertFalse(doc["handoff"]["exists"])
        (folder / "handoff.md").write_text("# Farmer handoff\n")
        doc = self.gather(self.farmer, "farmer")
        self.assertTrue(doc["handoff"]["exists"])
        self.assertEqual((doc["way"]["way"], doc["check"]["state"], doc["mfm"]["run"]), ("wake", "none", False))

    def test_farmer_dir_moves_the_farmer_s_and_tollman_s_state(self):
        os.environ["FARMER_DIR"] = str(self.tmp / "state")
        self.assertEqual(self.gather(self.farmer, "farmer")["handoff"]["file"], str(self.tmp / "state/app/handoff.md"))
        self.assertEqual(self.gather(self.tollman, "tollman")["handoff"]["file"],
                         str(self.tmp / "state/app/tollman/handoff.md"))

    def test_tollman_acts(self):
        doc = self.gather(self.tollman, "tollman")
        self.assertEqual(doc["handoff"]["file"], str(self.tollman / "roles/tollman/handoff.md"))
        self.assertEqual((doc["way"]["load"], doc["way"]["way"]), ("/tollman duties", "act"))

    def test_steward_moves_from_the_root_handoff_to_its_role_folder(self):
        (self.farm.main / "HANDOFF.md").write_text("# Handoff\n")
        self.addCleanup((self.farm.main / "HANDOFF.md").unlink)
        doc = self.gather(self.farm.main, "steward")
        self.assertEqual(doc["handoff"]["file"], str(self.farm.main / "roles/steward/handoff.md"))
        self.assertEqual(doc["handoff"]["found"], str(self.farm.main / "HANDOFF.md"))
        self.assertEqual(doc["way"]["way"], "daybook")

    def test_mayor_lord_and_pope_continue_their_handoff(self):
        for role in ("mayor", "lord", "pope"):
            doc = self.gather(self.farm.main, role)
            self.assertEqual(doc["handoff"]["file"], str(self.farm.main / f"roles/{role}/handoff.md"), role)
            self.assertEqual((doc["way"]["load"], doc["way"]["way"]), (f"/{role} duties", "handoff"), role)

    def test_the_mayor_by_the_folder_rule_without_the_cli(self):
        os.environ["HAL_VILLAGE"] = str(self.farm.main)
        doc = self.gather(self.farm.main, "fallback")
        self.assertEqual((doc["role"]["role"], doc["role"]["source"]), ("mayor", "fallback"))

    def test_a_train_s_field_has_no_role_by_either_rule(self):
        for how in (None, "fallback"):
            doc = self.gather(self.train, how)
            self.assertIsNone(doc["role"]["role"], how)
            self.assertEqual(doc["way"]["way"], "stop")

    def test_the_folder_rule_without_the_cli(self):
        for path, want in ((self.foreman, "foreman"), (self.servant, "servant"), (self.farmer, "farmer"),
                           (self.tollman, "tollman"), (self.farm.main, "steward")):
            doc = self.gather(path, "fallback")
            self.assertEqual((doc["role"]["role"], doc["role"]["source"]), (want, "fallback"), path.name)
        self.assertEqual(self.gather(self.servant, "fallback")["role"]["lead"],
                         {"field": "07", "plan": "0001-x", "step": "3"})

    def test_the_pause_record_is_found(self):
        doc = self.gather(self.foreman, "foreman")
        self.assertFalse(doc["pause"]["exists"])
        record = Path(doc["pause"]["record"])
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text("# Paused\n")
        self.addCleanup(record.unlink)
        self.assertTrue(self.gather(self.foreman, "foreman")["pause"]["exists"])
        self.assertEqual(record.parent, self.tmp / "pause")

    def test_an_empty_since_report_needs_no_judgment(self):
        kit.answer(self.fakes, "since/0001-x.json", kit.since_doc("0001-x"))
        check = self.gather(self.foreman, "foreman")["check"]
        self.assertEqual((check["state"], check["items"]), ("empty", []))

    def test_a_cli_without_since_is_the_check_by_hand(self):
        self.assertEqual(self.gather(self.foreman, "foreman")["check"]["state"], "unavailable")

    def test_the_text_report_names_role_handoff_and_check(self):
        kit.answer(self.fakes, "role/07.json", kit.role_doc(self.foreman, "foreman"))
        kit.answer(self.fakes, "since/0001-x.json", kit.since_doc("0001-x"))
        done = run("--repo", str(self.foreman), env={**self.env, "PAUSE_ROOT": str(self.tmp / "pause")})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("role: foreman (07: fixture) [cli]", done.stdout)
        self.assertIn("check: empty", done.stdout)
        self.assertIn("then: /foreman duties", done.stdout)


class Restock(unittest.TestCase):
    """D16: /mfm only behind origin/main and neither hitched, landing nor paused."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.farm = kit.Farm(cls.tmp / "farm")
        cls.foreman = cls.farm.field("07", plan="0001-x")
        (cls.farm.main / "new.txt").write_text("x\n")
        kit.git(cls.farm.main, "add", "new.txt")
        kit.git(cls.farm.main, "commit", "-q", "-m", "later")
        kit.git(cls.farm.main, "update-ref", "refs/remotes/origin/main", "main")
        cls.fakes = cls.tmp / "fakes"
        cls.env = kit.fakes(cls.fakes)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def setUp(self):
        for name in ("queue.json", "paused.json"):
            (self.fakes / name).unlink(missing_ok=True)
        patch = mock.patch.dict(os.environ, self.env)
        patch.start()
        self.addCleanup(patch.stop)

    def decide(self, role="foreman"):
        return GATHER.freshness.decide(self.foreman, role, "07")

    def test_behind_and_free_restocks(self):
        self.assertEqual((self.decide()["run"], self.decide()["behind"]), (True, 1))

    def test_a_hitched_field_stays_on_its_head(self):
        kit.answer(self.fakes, "queue.json", {"queue": [{"slot": "07", "state": "waiting", "ready": {"at": "t"}}]})
        found = self.decide()
        self.assertFalse(found["run"])
        self.assertIn("hitched", found["why"])

    def test_a_landing_owns_its_checkout(self):
        kit.answer(self.fakes, "queue.json", {"queue": [{"slot": "07", "state": "active", "holding": True}]})
        self.assertIn("landing", self.decide()["why"])

    def test_a_paused_field_is_left_alone(self):
        kit.answer(self.fakes, "queue.json", {"queue": []})
        kit.answer(self.fakes, "paused.json", {"schema": 1, "fields": [{"field": "07", "by": "user"}]})
        self.assertIn("paused by user", self.decide()["why"])

    def test_only_fields_restock(self):
        self.assertFalse(self.decide("farmer")["run"])
        self.assertFalse(self.decide("steward")["run"])


class ContinueAll(unittest.TestCase):
    """D18: the farmer's list, paused and unfinished foremen, oldest first; `checked` marks a passed check."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.farm = kit.Farm(self.tmp / "farm")
        self.fakes = self.tmp / "fakes"
        patch = mock.patch.dict(os.environ, kit.fakes(self.fakes))
        patch.start()
        self.addCleanup(patch.stop)

    def row(self, name, done, total, last, agents=(), paused=None):
        path = self.farm.field(name, plan="0001-x", lead="07 0001-x 3" if name == "31" else None)
        return {"name": name, "path": str(path), "main": False, "plan": "0001-x", "last_commit": last,
                "plan_progress": {"slug": "0001-x", "done": done, "total": total,
                                  "next": {"number": "2", "title": "Send the report"}},
                "agents": list(agents), "paused": paused}

    def test_paused_and_unfinished_foremen_oldest_first(self):
        rows = [{"name": "main", "path": str(self.farm.main), "main": True},
                self.row("05", 1, 3, 300), self.row("06", 1, 3, 100, paused={"by": "user"}),
                self.row("08", 3, 3, 50), self.row("09", 1, 3, 10, agents=[{"state": "idle"}]),
                self.row("31", 1, 3, 5)]
        kit.answer(self.fakes, "list.json", {"worktrees": rows})
        found = foremen.listing(self.farm.main)
        self.assertEqual([f["field"] for f in found], ["06", "05"])  # finished, running and a servant left out
        self.assertEqual(found[0]["paused"], {"by": "user"})
        self.assertIsNone(found[0]["checked"])
        done = run("checked", "--repo", found[0]["path"])
        self.assertEqual(done.returncode, 0, done.stderr)
        at = foremen.listing(self.farm.main)[0]["checked"]
        self.assertRegex(at, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(run("checked", "--repo", found[0]["path"], "--after", at).returncode, 0)
        self.assertEqual(run("checked", "--repo", found[0]["path"], "--after", "2999-01-01T00:00:00Z").returncode, 1)
        self.assertEqual(run("checked", "--repo", found[1]["path"], "--after", at).returncode, 1)  # never checked

    def test_no_answer_is_said(self):
        done = run("all", "--repo", str(self.farm.main), env=dict(os.environ))
        self.assertEqual(done.returncode, 2)


class Items(unittest.TestCase):
    def test_strong_items_name_a_link_or_file_weak_ones_words(self):
        doc = kit.since_doc("0001-x", decisions=[
            {"plan": "0002-y", "id": "D4", "text": "mail is gone", "why": [{"kind": "link", "what": "names 0001"}],
             "steps": ["2"]},
            {"plan": "0003-z", "id": "D1", "text": "views", "why": [{"kind": "words", "what": "view"}], "steps": ["3"]}])
        items = since_check.items_of(doc)
        self.assertEqual([i["strength"] for i in items], ["strong", "weak"])
        self.assertEqual(since_check.by_step(doc, items), {"2": ["0002-y D4"], "3": ["0003-z D1"]})


if __name__ == "__main__":
    unittest.main()
