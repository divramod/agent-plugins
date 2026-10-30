"""Plan 0294 D25: a plans/LEAD marker of a running servant is in use, never stale."""

import tempfile
import unittest
from pathlib import Path

import unit_scripts  # noqa: F401  (the skills unit's scripts/ on the import path: git_seed)
import git_seed
import lead_marker
from test_farmer import git

LEAD = {"slot": "09", "plan": "0275-masterplan", "step": "3"}
OPEN = "| # | Step | Status |\n|---|---|---|\n| 1 | a | done |\n| 2 | b | open |\n"
DONE = "| # | Step | Status |\n|---|---|---|\n| 1 | a | done |\n| 2 | b | Done (landed) |\n"


class Fields(unittest.TestCase):
    """Fields 09 (the foreman) and 34 (its servant) of a repository, origin/main set by hand: no network, no session."""

    def grow(self):
        """The repository and the fields 09 and 34, grown once and shared by every process (git_seed)."""
        self.main.mkdir()
        git(self.main, "init", "-q", "-b", "main")
        git(self.main, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "root")
        git(self.main, "update-ref", "refs/remotes/origin/main", "HEAD")
        for name, path in (("09", self.foreman), ("34", self.servant)):
            git(self.main, "worktree", "add", "-q", "-b", name, str(path), "main")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.main, self.foreman, self.servant = base / "hal2", base / "wt/09", base / "wt/34"
        git_seed.guard(self)
        git_seed.grow(base, "test_lead_marker.Fields", self.grow)
        (self.servant / "plans").mkdir()
        (self.servant / "plans/LEAD").write_text("09 0275-masterplan 3\n")
        (self.servant / "plans/CURRENT_PLAN").write_text("0275-masterplan\n")
        self.plan(OPEN)

    def plan(self, text):
        (self.foreman / "plans/0275-masterplan").mkdir(parents=True, exist_ok=True)
        (self.foreman / "plans/0275-masterplan/plan.md").write_text(text)

    def session(self, state="idle"):
        return [{"checkout": str(self.servant), "state": state}, {"checkout": str(self.foreman), "state": "idle"}]

    def state(self, agents, **kw):
        return lead_marker.state(self.servant, lead_marker.marker(self.servant), agents, "origin/main", **kw)

    def commit(self):
        (self.servant / "work.txt").write_text("x")
        git(self.servant, "add", "work.txt")
        git(self.servant, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "work")


class State(Fields):
    def test_a_running_servant_of_an_open_plan_is_in_use(self):
        got = self.state(self.session())
        self.assertEqual(got["state"], "in-use")
        self.assertIn("is open", got["reason"])
        self.assertIn("an agent session runs", got["reason"])

    def test_the_foremans_plan_done_is_stale_even_with_a_session(self):
        self.plan(DONE)
        got = self.state(self.session())
        self.assertEqual(got["state"], "stale")
        self.assertIn("plan 0275-masterplan of field 09 is done", got["reason"])

    def test_dropped_rows_are_no_open_work(self):
        """A schema 2 plan (hal2 plan 0376) keeps its dropped rows in the overview's step table."""
        self.plan("| # | Step | Status |\n|---|---|---|\n| 01.01 | a | done |\n| 01.02 | b | dropped |\n")
        self.assertEqual(self.state(self.session())["state"], "stale")

    def test_the_foremans_plan_gone_is_stale(self):
        (self.foreman / "plans/0275-masterplan/plan.md").unlink()
        got = self.state(self.session())
        self.assertEqual(got["state"], "stale")
        self.assertIn("is gone from field 09", got["reason"])

    def test_no_session_and_no_unmerged_work_is_stale(self):
        got = self.state([])
        self.assertEqual(got["state"], "stale")
        self.assertIn("no agent session and no unmerged work", got["reason"])
        self.assertEqual(self.state(self.session("ended"))["state"], "stale")  # an ended session is none

    def test_no_session_but_unmerged_work_is_in_use(self):
        self.commit()
        got = self.state([])
        self.assertEqual(got["state"], "in-use")
        self.assertIn("1 commit(s) not on origin/main", got["reason"])
        git(self.servant, "reset", "-q", "--hard", "main")
        (self.servant / "new.txt").write_text("x")  # an uncommitted change counts too, plans/LEAD does not
        self.assertIn("uncommitted changes", self.state([])["reason"])

    def test_what_cannot_be_read_is_unknown_never_stale(self):
        got = self.state(None)  # no session list
        self.assertEqual(got["state"], "unknown")
        self.assertIn("the agent list is missing", got["reason"])
        self.assertEqual(self.state(self.session(), foreman=self.foreman.parent / "99")["state"], "unknown")
        self.plan("no table here\n")
        self.assertEqual(self.state(self.session())["state"], "unknown")
        self.plan(OPEN)
        bad = {"bad": True, "text": "x", "error": "broken"}
        self.assertEqual(lead_marker.state(self.servant, bad, [], "origin/main")["state"], "unknown")
        self.assertEqual(lead_marker.state(self.servant, LEAD, [], "origin/nowhere")["state"], "unknown")


class Words(Fields):
    def test_a_marker_is_named_by_what_it_is_and_only_a_stale_one_is_called_so(self):
        self.assertEqual(lead_marker.describe(LEAD), "servant of field 09's plan 0275-masterplan (step 3)")
        for st, has in (({"state": "in-use", "reason": "r"}, False), ({"state": "unknown", "reason": "r"}, False),
                        ({"state": "stale", "reason": "r"}, True)):
            text = lead_marker.say(LEAD, st)
            self.assertIn("servant of field 09's plan 0275-masterplan", text)
            self.assertEqual("stale" in text, has, text)
            self.assertNotIn("delete", text)


if __name__ == "__main__":
    unittest.main()
