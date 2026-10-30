"""What a prune plan reads once for all fields (batch.py, field_facts.PlanIndex; hal2 plan 0480 step 04.02, D5): one
`ps -A`, one `git for-each-ref` with ahead-behind and one `hal2-cli-plans list --json` per plan, with the same answers
as the per-field calls, and the old per-field way wherever a batch cannot answer. Scratch farm and fake CLIs only."""

import contextlib
import io
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import batch
import fake_clis
import facts
import field_facts
import prune_proof
from test_farmer import git
from test_field_facts import lookup


class Counting(fake_clis.Farm):
    """A farm of fields 03 (free), 05 (a stale pointer), 06 (a commit), 07 (a side branch), 08 (detached before its tip),
    09 (uncommitted); `self.runs` records every program started in this process."""

    def setUp(self):
        super().setUp()
        self.add("03")
        pointer = self.add("05")
        (pointer / "plans").mkdir(exist_ok=True)
        (pointer / "plans/CURRENT_PLAN").write_text("0001-x\n")
        ahead = self.add("06")
        (ahead / "a.txt").write_text("a\n")
        git(ahead, "add", "."), git(ahead, "commit", "-qm", "a")
        side = self.add("07")
        git(side, "checkout", "-qb", "07-ui")
        (side / "b.txt").write_text("b\n")
        git(side, "add", "."), git(side, "commit", "-qm", "b")
        git(side, "checkout", "-q", "07")
        old = self.add("08")
        (old / "c.txt").write_text("c\n")
        git(old, "add", "."), git(old, "commit", "-qm", "c")
        git(old, "commit", "-q", "--allow-empty", "-m", "d")
        git(old, "checkout", "-q", "--detach", "HEAD~1")  # no branch is at this commit
        (self.add("09") / "dirty.txt").write_text("x\n")
        self.feed(plans={"0001-x": {"state": "done"}}, agents=[])
        self.runs = []
        real = subprocess.run

        def spy(argv, *a, **kw):
            self.runs.append(list(argv))
            return real(argv, *a, **kw)
        p = mock.patch.object(subprocess, "run", side_effect=spy)
        p.start()
        self.addCleanup(p.stop)

    def count(self, prefix):
        return [r for r in self.runs if r[:len(prefix)] == prefix]

    def refs_calls(self):
        return [r for r in self.runs if "for-each-ref" in r and any("ahead-behind" in x for x in r)]

    def collect(self, **kw):
        return facts.collect(str(self.main), measure=lambda main, fs, cached_only=False: {}, **kw)


class OnePerPlan(Counting):
    def test_one_ps_one_for_each_ref_and_one_plans_list_serve_every_field(self):
        found = self.collect()
        self.assertEqual(len(self.count(["ps"])), 1, self.count(["ps"]))
        self.assertEqual(len(self.refs_calls()), 1, self.refs_calls())
        self.assertEqual(len(self.calls("hal2-cli-plans", "list")), 1)
        self.assertEqual(self.calls("hal2-cli-plans", "show"), [], "no show per field: the list knew the plan")
        self.assertEqual([r for r in self.runs if any("cleanup.py" in x for x in r)], [], "no cleanup.py program per field")
        by = {f["slot"]: f for f in found["fields"]}
        self.assertEqual(by["05"]["pointer"], {"plan": "0001-x", "state": "finished"})
        self.assertTrue(by["03"]["free"] and by["03"]["proof"] is None)
        self.assertIn("1 commit(s) not on origin/main", by["06"]["proof"])
        self.assertIn("side branch 07-ui: 1 commit(s) not on origin/main", by["07"]["proof"])
        self.assertIn("uncommitted", by["09"]["proof"])

    def test_the_batched_unsaved_work_is_the_per_field_unsaved_work(self):
        """The same reasons as the old rev-list per field, also for the field whose HEAD is no branch tip (08)."""
        refs = batch.Refs(str(self.main))
        for f in facts.fields(str(self.main)):
            old = prune_proof.unsaved(f["path"], f["slot"], "origin/main")
            new = prune_proof.unsaved(f["path"], f["slot"], "origin/main", refs, f["head"])
            self.assertEqual(new, old, f["slot"])
        self.assertEqual(len(self.refs_calls()), 1)
        self.assertEqual(prune_proof.unsaved(str(self.base / "08"), "08", "origin/main", refs, git(self.base / "08", "rev-parse", "HEAD")),
                         ["1 commit(s) not on origin/main"])

    def test_a_scan_asks_the_branches_once_and_git_per_field_only_for_a_head_that_is_no_tip(self):
        refs = batch.Refs(str(self.main))
        prune_proof.scan(str(self.main), {}, [], None, lambda path: False, refs)
        self.assertEqual(len(self.refs_calls()), 1)
        heads = [r for r in self.runs if r[:3] == ["git", "rev-list", "--count"] and r[-1] == "origin/main..HEAD"]
        self.assertEqual(len(heads), 1, "just 08, whose HEAD is no branch tip")
        self.assertEqual([r for r in self.runs if r[:2] == ["git", "for-each-ref"] and r not in self.refs_calls()], [],
                         "no side-branch listing per field")


class Fallbacks(Counting):
    def test_a_git_without_ahead_behind_asks_per_field_as_before(self):
        real = batch.tick.git
        with mock.patch.object(batch.tick, "git", side_effect=lambda repo, *a: "" if any("ahead-behind" in x for x in a)
                               else real(repo, *a)):
            why = {f["slot"]: f["proof"] for f in self.collect()["fields"]}
        self.assertIn("1 commit(s) not on origin/main", why["06"])
        self.assertIn("side branch 07-ui", why["07"])

    def test_refs_of_another_base_are_not_used(self):
        refs = batch.Refs(str(self.main), "origin/main")
        path = str(self.base / "06")
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True).stdout.strip()
        got = prune_proof.unsaved(path, "06", "origin/other", refs, head)
        self.assertEqual(got, prune_proof.unsaved(path, "06", "origin/other"))
        self.assertEqual(self.refs_calls(), [], "a base the table was not read for is not asked of the table")


class Processes(unittest.TestCase):
    def test_one_listing_answers_every_path_and_an_empty_one_counts_as_busy(self):
        listing = "10 /usr/bin/cargo build --manifest-path /w/hal2/03/Cargo.toml\n11 /bin/zsh\n12 vim /w/hal2/033/x\n"
        ps = batch.Processes(listing)
        self.assertTrue(ps.running("/w/hal2/03"))
        self.assertFalse(ps.running("/w/hal2/04"))
        self.assertFalse(ps.running("/w/hal2/033/y"), "03 is not 033")
        self.assertTrue(batch.Processes("  \n").running("/w/hal2/04"), "a failed ps is no proof of idle")

    def test_the_listing_is_taken_on_first_use_and_once(self):
        with mock.patch.object(batch.cleanup(), "process_listing", return_value="1 x\n") as ps:
            p = batch.Processes()
            self.assertEqual(ps.call_count, 0)
            p.running("/a"), p.running("/b"), p.running("/c")
        self.assertEqual(ps.call_count, 1)

    def test_cleanup_busy_takes_a_listing_and_its_callers_stay_as_they_are(self):
        c = batch.cleanup()
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        with mock.patch.object(c, "toplevel", return_value=Path("/w/hal2/03")), \
                mock.patch.object(c, "process_listing", side_effect=AssertionError("given a listing")):
            self.assertEqual(c.cmd_busy([], "5 sleep /w/hal2/03/x\n"), 1)
        with mock.patch.object(c, "toplevel", return_value=Path("/w/hal2/03")), \
                mock.patch.object(c, "process_listing", return_value="5 sleep 1\n"):
            self.assertEqual(c.cmd_busy([]), 0)


class PlanIndex(unittest.TestCase):
    def index(self, plans, shows=None):
        calls = []
        shows = shows or {}

        def run(plan, repo):
            calls.append((plan, repo))
            return shows.get(plan, (1, "", f'no plan matches "{plan}"'))
        return field_facts.PlanIndex("/main", lambda repo: plans, run), calls

    def test_one_list_answers_by_slug_or_number_and_a_show_is_the_fallback(self):
        listed = []
        plans = [{"slug": "0001-x", "number": 1, "state": "done", "finished": "2026-10-01"},
                 {"slug": "0480-y", "number": 480, "state": "active", "finished": None}]
        idx, calls = self.index(plans, {"0777-z": (0, '{"state": "active"}', "")})
        idx._list = lambda repo: listed.append(repo) or plans
        for name, want in (("0001-x", "finished"), ("0480", "open"), ("480", "open"), ("0480-y", "open")):
            self.assertEqual(idx(name, ["/field", "/main"]), want, name)
        self.assertEqual(listed, ["/main"], "listed once")
        self.assertEqual(calls, [])
        self.assertEqual(idx("0777-z", ["/field", "/main"]), "open", "a plan of the field's branch only: show as before")
        self.assertEqual(idx("shots/3/x", ["/field", "/main"]), "missing")
        self.assertEqual(len(calls), 3)

    def test_an_unreadable_list_is_the_old_way(self):
        idx, calls = self.index(None, {"0001-x": (0, '{"state": "done"}', "")})
        self.assertEqual(idx("0001-x", ["/field", "/main"]), "finished")
        self.assertEqual(calls, [("0001-x", "/field")])

    def test_the_list_is_main_s_only_when_main_is_asked(self):
        idx, calls = self.index([{"slug": "0001-x", "number": 1, "state": "done"}])
        self.assertEqual(idx("0001-x", ["/field"]), "missing", "a lookup that excludes main never uses its list")


if __name__ == "__main__":
    unittest.main()
