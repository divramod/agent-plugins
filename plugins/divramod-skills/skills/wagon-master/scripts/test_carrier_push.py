"""Hal2 plan 0313 step 1: a split or breakup puts the carrier's remote branch back on the train's base. The case of
2026-10-14 (the wagon master's train.jsonl, UTC): train 06@07:04 was split at 08:27:07, train 07 formed on the base
at 08:27:22, and its landing's push to origin/wagon-master-hal2 was refused at 08:32:42 as not a fast-forward,
because the remote branch still held the dead train. On engine_farm's farm (a bare origin, no landing, D5)."""

import os
import unittest

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import engine
import train_state
from engine_farm import OWN, Farm, out
from test_farmer import git

REF = f"refs/heads/{OWN}"


class CarrierPush(Farm):
    def setUp(self):
        super().setUp()
        self.origin = self.tmp / "hal2.git"

    def landing_push(self):
        """What the landing does with the carrier first: its head pushed to its remote branch, without force."""
        return engine.git(str(self.wm), "push", "-q", "origin", f"HEAD:{REF}")

    def remote(self):
        """The remote branch's tip, None without one."""
        code, sha = engine.git(str(self.origin), "rev-parse", "--verify", "-q", REF)
        return sha if code == 0 else None

    def cleared(self):
        return [e for e in train_state.lines(str(self.main)) if e["kind"] == "cleared"][-1]

    def test_the_split_of_a_red_train_puts_the_remote_branch_back_and_the_next_push_fast_forwards(self):
        self.crop("06", {"six.txt": "6"}, plan="0255-plugin-tmux-2-move-tmux-plugin-here")
        self.crop("07", {"seven.txt": "7"}, plan="0301-shada-guard")
        base = out(self.wm, "rev-parse", "HEAD")
        self.round()
        dead = out(self.wm, "rev-parse", "HEAD")
        self.assertEqual(self.landing_push()[0], 0, "the dead train's landing pushed the carrier")
        self.ends({"status": "gate_failed", "run": "https://github.com/x/runs/1", "red": [{"name": "python-lint"}]})
        self.gate.of(OWN).update(state="held", train=None, hold={"reason": "failed"})
        self.round()
        self.assertEqual(self.train()["state"], "red")
        self.assertEqual(self.call("unhitch", "06", "--why", "the names check", repo=self.main)[0], 0)
        self.round()  # split after red: breakup, then the train of 07 alone forms on the base
        self.assertEqual(self.last, [("breakup", "run", "-"), ("unhitched", "relay", "06"), ("form", "run", "-")])
        self.assertEqual(self.remote(), base, "the dead train is gone from origin")
        self.assertEqual(self.cleared()["pushed"], f"origin's {REF} back on {base[:12]} (was {dead[:12]})")
        self.assertEqual(self.train()["base"], base)
        code, text = self.landing_push()
        self.assertEqual(code, 0, f"the next train's push fast-forwards: {text}")
        self.assertEqual(self.remote(), out(self.wm, "rev-parse", "HEAD"))

    def test_a_breakup_without_a_remote_branch_or_on_the_base_pushes_nothing(self):
        self.crop("07", {"seven.txt": "7"})
        self.round()
        self.assertIsNone(self.remote())
        self.alive.clear()
        code, text = engine.breakup(str(self.wm), "its landing never started")
        self.assertEqual((code, text), (0, "train " + self.cleared()["train"] + " broken up: its landing never started"))
        self.assertNotIn("pushed", self.cleared())
        self.assertIsNone(self.remote(), "no remote branch made")

    def test_a_refused_push_is_told_never_forced_and_the_local_reset_stands(self):
        self.crop("07", {"seven.txt": "7"})
        base = out(self.wm, "rev-parse", "HEAD")
        self.round()
        dead = out(self.wm, "rev-parse", "HEAD")
        self.assertEqual(self.landing_push()[0], 0)
        hook = self.origin / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\necho 'refused by the test' >&2\nexit 1\n")
        os.chmod(hook, 0o755)
        self.alive.clear()
        code, text = engine.breakup(str(self.wm), "its landing never started")
        self.assertEqual(code, 0, text)
        self.assertIn(f"origin's {REF} still holds the dead train {dead[:12]}, not pushed", text)
        self.assertIn("pre-receive hook declined", self.cleared()["pushed"])
        self.assertEqual((out(self.wm, "rev-parse", "HEAD"), self.remote(), self.train()), (base, dead, None))

    def test_a_car_that_does_not_merge_puts_a_dead_train_left_on_the_remote_back_too(self):
        self.crop("07", {"seven.txt": "7"})
        base = out(self.wm, "rev-parse", "HEAD")
        self.commit(self.wm, "dead.txt", "a dead train's commit")
        self.assertEqual(self.landing_push()[0], 0)
        git(self.wm, "reset", "-q", "--hard", base)  # an older breakup reset the carrier, not its remote branch
        car = {"field": "07", "branch": "07", "head": "0" * 40, "plan": ""}
        code, text = engine.form(str(self.wm), [car])
        self.assertEqual(code, 1, text)
        self.assertIn(f"origin's {REF} back on {base[:12]}", text)
        self.assertEqual(self.remote(), base)
        self.assertTrue(self.cleared()["pushed"].startswith(f"origin's {REF} back on"))


if __name__ == "__main__":
    unittest.main()
