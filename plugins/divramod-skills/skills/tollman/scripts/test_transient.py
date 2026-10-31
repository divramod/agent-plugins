"""Hal2 plan 0490 step 9: the transient patterns (transient.py) against the words of the learnings' cases, and the
red landing without a run (train_red.no_run). L51: train 10's carrier push ended `error` with 'Connection to
github.com closed by remote host' and no run, and stood red 2 h until a wake: now a runner fault, retried by code.
L59: train 8's codesign timestamp red. L68: train 9's Hetzner capacity red. L101: protoc's dyld error is the Mac's
(MAC), never a CI runner's (TRANSIENT)."""

import unittest

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import train_red
import trains
import transient

NAME = "10@2026-10-20T11:00:00Z"
TRAIN = {"train": NAME, "at": "2026-10-20T11:00:00Z", "carrier": "tollman-hal2", "base": "b" * 40, "state": "landing",
         "starts": 1, "pid": 4711, "unhitched": [], "yard": [], "runner_retries": 0,
         "cars": [{"field": "10", "branch": "10", "head": "h" * 40, "plan": "0370-x"}]}
PUSH = {"status": "error", "message": "git push origin land/tollman-hal2: Connection to github.com closed by remote "
                                      "host\nfatal: the remote end hung up unexpectedly"}


def shape(actions):
    return [(a["kind"], a["do"]) for a in actions]


class Patterns(unittest.TestCase):
    def test_the_learnings_words_are_transient(self):
        for words in ("Connection to github.com closed by remote host",  # L51
                      "fetch-pack: unexpected disconnect while reading sideband packet",
                      "fatal: early EOF",
                      "The timestamp service is not available.",  # L59
                      "Warning: A timestamp was expected but was not found.",
                      "hcloud: server create failed: resource_unavailable",  # L68
                      "Hetzner placed no cx33 in fsn1/nbg1/hel1 in 5 rounds",
                      "npm ERR! network read ECONNRESET"):
            self.assertTrue(transient.TRANSIENT.search(words), words)

    def test_a_cars_red_is_not(self):
        for words in ("assertion failed: tenant", "error[E0425]: cannot find value `x`", "test placed nothing",
                      "dyld[83121]: Library not loaded: /opt/homebrew/opt/abseil/lib/libabsl.dylib"):
            self.assertFalse(transient.TRANSIENT.search(words), words)

    def test_the_macs_dyld_error(self):
        self.assertTrue(transient.MAC.search("dyld[83121]: Library not loaded: /opt/homebrew/opt/abseil/lib/x.dylib"))
        self.assertTrue(transient.MAC.search("Library not loaded: /usr/local/opt/icu4c/lib/libicuuc.74.dylib"))
        self.assertFalse(transient.MAC.search("ld: library not found for -lfoo"))


class NoRun(unittest.TestCase):
    def settle(self, result, train=TRAIN):
        return trains.settle("/tmp/never-read/tollman-hal2", train, result, {})

    def test_a_push_the_network_cut_is_retried_by_code_and_wakes_nobody(self):
        out = self.settle(PUSH)
        self.assertEqual(shape(out), [("red", "run"), ("retry", "run"), ("restart", "run")])
        self.assertEqual(out[1]["argv"][2:5], ["retry", "--why", "runner: closed by remote host"])

    def test_the_runner_count_still_bounds_it(self):
        out = self.settle(PUSH, dict(TRAIN, runner_retries=train_red.MAX_RUNNER))
        self.assertEqual(shape(out), [("red", "run"), ("train-runner-broken", "wake")])

    def test_any_other_red_without_a_run_still_wakes(self):
        for result in ({"status": "error", "message": "the candidate does not build"},
                       {"status": "pretest_red", "red": [{"name": "python-lint"}], "suspects": ["10"],
                        "message": "pretest: python-lint red, car 10 (connection refused in a test)"},
                       {"status": "conflict", "message": "connection reset while merging? no: a conflict"}):
            self.assertEqual(shape(self.settle(result)), [("red", "run"), ("train-failed", "wake")], result)


if __name__ == "__main__":
    unittest.main()
