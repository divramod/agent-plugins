#!/usr/bin/env python3
"""Tests for the pushes of transplant.py (D25) on a scratch clone with a bare origin, and for the handoff skill's
`where.py` on a transplanted field: nothing here touches a real repository or remote."""
import json
import subprocess
import sys
import unittest

from test_support import HERE, Scratch, commit, sh

WHERE = HERE.parents[1] / "handoff" / "scripts" / "where.py"
PLAN = "---\ntype: Plan\nschema: 1\nid: 1\ntitle: Demo\ndescription: A demo\nstatus: open\n---\n\n# Plan 0001\n"


class TestPush(Scratch):
    def setUp(self):
        super().setUp()
        self.tip = commit(self.f34, "work")  # the foreman's commit on 34, pushed by the skill's step 5
        sh(self.f34, "push", "-q", "-u", "origin", "34")
        sh(self.f09, "merge", "-q", "--ff-only", "34")  # the drive
        sh(self.f34, "reset", "-q", "--hard", "origin/main")  # the reset to the barn

    def origin_sha(self, branch):
        return sh(self.origin, "rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False)

    def push(self, repo):
        code, result, err = self.run_script("push", "34", "09", repo=repo)
        self.assertEqual(code, 0, err)
        return result

    def test_from_the_old_fields_own_session_the_lease_push_makes_origins_branch_the_barns(self):
        result = self.push(self.f34)
        self.assertEqual((result["pushed"], result["old"]), (["09"], "lease"))
        self.assertEqual(self.origin_sha("09"), self.tip)
        self.assertEqual(self.origin_sha("34"), self.base)

    def test_from_another_session_the_target_only_and_the_old_tip_is_named(self):
        result = self.push(self.app)
        self.assertEqual((result["pushed"], result["old"]), (["09"], "kept"))
        self.assertIn(f"origin/34 still holds the old tip {self.tip[:7]}", result["note"])
        self.assertEqual((self.origin_sha("09"), self.origin_sha("34")), (self.tip, self.tip))

    def test_no_lease_push_before_origins_target_holds_the_tip(self):
        other = self.t / "other"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(other)], check=True)
        sh(other, "checkout", "-q", "34")
        later = commit(other, "someone-else")
        sh(other, "push", "-q", "origin", "34")  # origin/34 moved on: origin/09 does not hold it
        result = self.push(self.f34)
        self.assertEqual(result["old"], "kept")
        self.assertIn("origin/09 does not hold", result["note"])
        self.assertEqual(self.origin_sha("34"), later)

    def test_a_plain_push_where_the_barn_already_holds_the_tip(self):
        sh(self.app, "merge", "-q", "--ff-only", "09")  # the plan was brought in, and the barn moved on
        commit(self.app, "next")
        sh(self.app, "push", "-q", "origin", "main")
        sh(self.f34, "fetch", "-q", "origin")
        sh(self.f34, "reset", "-q", "--hard", "origin/main")
        result = self.push(self.f34)
        self.assertEqual(result["old"], "plain")  # a fast-forward: no lease needed
        self.assertEqual(self.origin_sha("34"), self.origin_sha("main"))
        self.assertNotEqual(self.origin_sha("34"), self.tip)

    def test_nothing_when_the_old_field_is_not_on_the_barn(self):
        commit(self.f34, "stray")
        result = self.push(self.f34)
        self.assertEqual(result["old"], "kept")
        self.assertIn("not on the barn", result["note"])
        self.assertEqual(self.origin_sha("34"), self.tip)

    def test_nothing_when_origin_has_no_branch_of_the_old_field(self):
        sh(self.app, "push", "-q", "origin", ":34")
        self.assertEqual(self.push(self.f34)["old"], "absent")

    def test_a_target_on_another_branch_is_not_pushed(self):
        sh(self.f09, "switch", "-q", "-c", "09-side")
        code, _, err = self.run_script("push", "34", "09", repo=self.f34)
        self.assertEqual(code, 1)
        self.assertIn("not 09", err)
        self.assertEqual(self.origin_sha("09"), "")

    def test_a_farm_without_origin_pushes_nothing(self):
        sh(self.app, "remote", "remove", "origin")
        result = self.push(self.f34)
        self.assertEqual((result["origin"], result["pushed"]), (False, []))


class TestHandoffWhere(Scratch):
    def test_the_handoff_skills_where_finds_the_plan_handoff_of_a_transplanted_field(self):
        (self.f09 / "plans" / "0001-demo").mkdir(parents=True)
        (self.f09 / "plans" / "CURRENT_PLAN").write_text("0001-demo\n")  # carried by the transplant, gitignored
        (self.f09 / "plans" / "0001-demo" / "plan.md").write_text(PLAN)
        r = subprocess.run([sys.executable, "-B", str(WHERE), "--root", str(self.f09), "--json"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        found = json.loads(r.stdout)
        self.assertEqual((found["file"], found["form"]), ("plans/0001-demo/handoff.md", "record"))
        self.assertEqual(sh(self.f09, "branch", "--show-current"), "09")


if __name__ == "__main__":
    unittest.main()
