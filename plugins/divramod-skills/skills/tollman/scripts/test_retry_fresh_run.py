"""Hal2 plan 0313 step 13 (D19): `retry` lands a red train again on a fresh land run, never on the red one. The case
of 2026-10-14 (the tollman's train.jsonl, UTC): train 09@11:57:18Z went red at 12:27:07 (gate_failed, run
38560326710, rust-test flakes), the session said `retry` at 12:27:55, the tick started its landing again at 12:32:54,
and at 12:37:10 it was red again with the same run 38560326710: nothing was tested again. hal2-git builds the
candidate as a commit of the barn and HEAD with HEAD's dates (`ci/git.rs` `candidate_with`) and finds its land run
by that commit (`ci/gh.rs` `run_of`, `head_sha`): the same HEAD on the same barn is the same candidate, its run the
red one. `Runs` is that lookup as data, on engine_farm's farm (no landing, no GitHub, D5)."""

import os
import subprocess
import unittest

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import engine
import train_state
from engine_farm import OWN, Farm, out

RED = 38560326710


class Runs:
    """The land runs by their candidate's commit, as GitHub lists them for `head_sha` (a new candidate pushed: a
    new run)."""

    def __init__(self):
        self.by_sha, self.next = {}, RED

    def land(self, top) -> int:
        """What a landing of the field `top` does with its run: the candidate built, its run found by its commit,
        or a new one started by its push."""
        sha = candidate(top)
        if sha not in self.by_sha:
            self.by_sha[sha], self.next = self.next, self.next + 1
        return self.by_sha[sha]


def candidate(top) -> str:
    """The landing's candidate the way hal2-git builds it: HEAD's tree, the barn and HEAD as parents, HEAD's author
    and committer, a message of the branch and the field (a deterministic commit)."""
    who = out(top, "log", "-1", "--format=%cn%x00%ce%x00%cI", "HEAD").split("\0")
    env = {"GIT_AUTHOR_NAME": who[0], "GIT_AUTHOR_EMAIL": who[1], "GIT_AUTHOR_DATE": who[2],
           "GIT_COMMITTER_NAME": who[0], "GIT_COMMITTER_EMAIL": who[1], "GIT_COMMITTER_DATE": who[2]}
    p = subprocess.run(["git", "commit-tree", "HEAD^{tree}", "-p", "origin/main", "-p", "HEAD", "-m",
                        f"Merge branch '{OWN}' into main"], cwd=top, capture_output=True, text=True, check=True,
                       env={**os.environ, **env})
    return p.stdout.strip()


class RetryFreshRun(Farm):
    def setUp(self):
        super().setUp()
        self.crop("09", {"nine.txt": "9"}, plan="0274-masterplan-halverse-plugin")
        self.runs = Runs()

    def red(self, run):
        self.ends({"status": "gate_failed", "run": f"https://github.com/divramod/hal2/actions/runs/{run}",
                   "red": [{"name": "02-hz01-host-x/rust-test"}]})
        self.gate.of(OWN).update(state="held", train=None, hold={"reason": "failed"})  # the landing's end
        self.round()

    def test_a_retried_red_train_lands_on_a_fresh_run_never_the_red_one(self):
        self.round()  # 11:57:18: formed, started
        self.assertEqual(self.runs.land(self.wm), RED, "the first landing's run")
        self.red(RED)  # 12:27:07
        self.assertEqual(self.train()["state"], "red")
        red_head = out(self.wm, "rev-parse", "HEAD")
        why = "rust-test: 2 of 6924 failed, both timing under load"
        self.assertEqual(self.call("retry", "--why", why)[0], 0)  # 12:27:55
        self.round()  # 12:32:54: started again
        self.assertEqual((self.last, self.train()["state"], self.train()["starts"]),
                         ([("restart", "run", "-")], "landing", 2))
        run = self.runs.land(self.wm)
        self.assertNotEqual(run, RED, "the retry's landing adopted the red run: nothing was tested again")
        self.assertEqual(out(self.wm, "rev-parse", "HEAD^"), red_head, "one commit on the red train's head")
        self.assertEqual(out(self.wm, "diff", "--stat", "HEAD^", "HEAD"), "", "an empty commit: the train as it is")
        self.assertEqual(out(self.wm, "log", "-1", "--format=%s"), "chore(wagon-train): land the train again on a fresh run (retry 1)")
        self.assertIn(why, out(self.wm, "log", "-1", "--format=%b"))
        started = [e for e in train_state.lines(str(self.main)) if e["kind"] == "started"]
        self.assertEqual((started[0].get("commit"), started[1]["commit"]), (None, out(self.wm, "rev-parse", "HEAD")))

        self.red(run)  # red again, and retried again: a third run, the second red one not adopted either
        self.assertEqual(self.call("retry", "--why", "flaky again")[0], 0)
        self.round()
        self.assertNotIn(self.runs.land(self.wm), (RED, run))
        self.assertEqual(out(self.wm, "log", "-1", "--format=%s"), "chore(wagon-train): land the train again on a fresh run (retry 2)")

    def test_a_restart_whose_mark_was_refused_commits_no_second_time(self):
        self.round()
        self.red(RED)
        self.call("retry", "--why", "flaky")
        self.gate.refuse = "train"
        self.assertEqual(engine.restart(str(self.wm))[0], 1, "the mark refused")
        head = out(self.wm, "rev-parse", "HEAD")
        self.gate.refuse = ""
        code, text = engine.restart(str(self.wm))
        self.assertEqual(code, 0, text)
        self.assertEqual(out(self.wm, "rev-parse", "HEAD"), head, "the same retry commit, not a second one")

    def test_an_interrupted_landing_restarts_without_a_commit_and_adopts_its_run(self):
        self.round()
        head = out(self.wm, "rev-parse", "HEAD")
        self.ends(None)  # the process gone without a word: the rerun adopts its run (landings-survive-their-process)
        self.round()
        self.assertEqual((self.last, out(self.wm, "rev-parse", "HEAD")), ([("restart", "run", "-")], head))

    def test_a_running_landing_is_never_touched_by_a_retry(self):
        self.round()
        self.alive.add(40001)
        head = out(self.wm, "rev-parse", "HEAD")
        self.assertEqual(self.call("retry", "--why", "flaky")[0], 1, "no red train: it lands")
        self.round()
        self.assertEqual((self.last, out(self.wm, "rev-parse", "HEAD")), ([], head))


if __name__ == "__main__":
    unittest.main()
