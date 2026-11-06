"""Hal2 plan 0383 step 1 (D2, L34), plan 0398 step 7 (D4) and plan 0607 step 6 (D4, D6): every train lands on its own
branch. A numbered train (`formed` line with `number`) is marked `--train <n> --attempt <starts+1>`, lands on the
`land/train-<n>-<a>` hal2-git names (no `--land-ref`), `restart` records what `worktree land-ref` says in its `started`
line and the watch looks for the run on that branch only. A train without a number is never started (no fallback
name). hal2-cli-git and gh are fakes: no real call."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import engine
import land_name
import train_branch
import train_state
import watch
from gh_fake import FakeGh, run

os.environ.setdefault("HAL2_WORKQUEUE_FREEZE", "0")  # no test takes a real workqueue hold (plan 0466)

AT = "2026-10-18T10:00:00Z"
NAME = "02+07@" + AT
MAIN = "/no/such/farm"
CARS = [{"field": "02", "branch": "02", "head": "2" * 40, "plan": "0383-train-rules"},
        {"field": "07", "branch": "07", "head": "7" * 40, "plan": "0365-ci-lanes"}]


def line(kind, at=AT, **kw):
    return {"schema": 1, "at": at, "kind": kind, "slot": "tollman-hal2", "train": NAME, **kw}


FORMED = line("formed", cars=CARS, base="b" * 40)
NUMBERED = line("formed", cars=CARS, base="b" * 40, number=7)
STARTED = line("started", at="2026-10-18T10:05:00Z", pid=4711, land_ref="train-0383-0365")


def land_ref(report):
    return lambda args, cwd: (0, json.dumps({"schema": 1, "slot": "tollman-hal2", "kind": "train", **report}))


class Name(unittest.TestCase):
    def test_the_branch_watched_is_hal2_git_s_current_else_the_started_line_s_never_a_built_one(self):
        started = train_state.standing([FORMED, STARTED])
        self.assertEqual(train_branch.land(started), "land/train-0383-0365", "the started line's, no CLI asked")
        said = land_ref({"current": "land/train-7-2", "next": "land/train-7-3"})
        self.assertEqual(train_branch.land(started, MAIN, said), "land/train-7-2")
        nothing = land_ref({"current": None, "next": "land/train-7-1"})
        self.assertEqual(train_branch.land(started, MAIN, nothing), "land/train-0383-0365", "null: the started line's")
        old = line("started", at="2026-10-18T10:05:00Z", pid=4711)
        self.assertIsNone(train_branch.land(train_state.standing([FORMED, old])), "no land/<carrier> fallback")

    def test_a_numbered_train_marks_its_next_start(self):
        one = train_state.standing([NUMBERED])
        two = train_state.standing([NUMBERED, line("started", at="2026-10-18T10:05:00Z", pid=1, land_ref="train-7-1")])
        self.assertEqual((train_branch.mark(one), train_branch.mark(two)),
                         (["--train", "7", "--attempt", "1"], ["--train", "7", "--attempt", "2"]))
        self.assertEqual(train_branch.mark(train_state.standing([FORMED])), [], "a train without a number: no mark")

    def test_every_start_of_a_numbered_train_is_its_own_and_no_other_train_s(self):
        train = train_state.standing([NUMBERED, line("started", pid=1, land_ref="train-7-2")])
        for mine in ("land/train-7-1", "land/train-7-2", "land/train-7-30"):
            self.assertTrue(train_branch.ours(train, mine), mine)
        for other in ("land/train-71-1", "land/train-6-1", "land/0383-train-rules-1", "land/07"):
            self.assertFalse(train_branch.ours(train, other), other)
        unnumbered = train_state.standing([FORMED, STARTED])
        self.assertEqual((train_branch.ours(unnumbered, "land/train-0383-0365"), train_branch.ours(unnumbered, "land/x")),
                         (True, False))


class Numbers(unittest.TestCase):
    def test_the_counter_gives_1_2_3_and_lives_beside_the_state(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(train_state, "folder", return_value=Path(d)):
            self.assertEqual([train_state.next_number(MAIN) for _ in range(3)], [1, 2, 3])
            self.assertEqual((Path(d) / train_state.NUMBER).read_text(), "3\n")


class Watch(unittest.TestCase):
    def setUp(self):  # hal2-cli-git cannot say: the started line's branch stands (no real call in a test)
        patch = mock.patch.object(land_name, "cli", lambda args, cwd: (127, "no hal2-cli-git"))
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_run_is_found_on_the_train_s_own_branch_only(self):
        ours = run(601, "land/train-0383-0365", "2026-10-18T10:06:00Z", status="in_progress")
        FakeGh([run(602, "land/tollman-hal2", "2026-10-18T10:07:00Z", status="in_progress"), ours]).start(self)
        rows = [FORMED, STARTED]
        self.assertEqual(watch.find(MAIN, train_state.standing(rows), rows), (ours["url"], True))
        FakeGh([run(602, "land/tollman-hal2", "2026-10-18T10:07:00Z")]).start(self)
        self.assertEqual(watch.find(MAIN, train_state.standing(rows), rows), (None, False),
                         "the carrier's old branch is another train's")

    def test_a_numbered_train_s_run_is_found_on_its_second_start_s_branch(self):
        rows = [NUMBERED, line("started", pid=1, land_ref="train-7-1"), line("red", status="gate_failed"),
                line("retry", why="flaky"), line("started", at="2026-10-18T10:20:00Z", pid=2, land_ref="train-7-2")]
        ours = run(701, "land/train-7-2", "2026-10-18T10:21:00Z", status="in_progress")
        FakeGh([run(700, "land/train-7-1", "2026-10-18T10:22:00Z", status="in_progress"), ours]).start(self)
        self.assertEqual(watch.find(MAIN, train_state.standing(rows), rows), (ours["url"], True))


class Engine(unittest.TestCase):
    def setUp(self):  # a start that names nothing writes its `attempt` line (plan 0620 D5): into a scratch, never a farm's
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        folder = mock.patch.object(train_state, "folder", return_value=Path(scratch.name))
        folder.start()
        self.addCleanup(folder.stop)

    def _restart(self, rows):
        """`engine.restart` of the standing train of `rows` with a fake hal2-cli-git that remembers the mark and
        answers `worktree land-ref` with it: (the mark call, the spawned --land-ref, the started line's land_ref)."""
        written, calls, marked = [], [], {}

        def cli(argv, cwd):
            if argv[:2] == ["worktree", "land-ref"]:
                name = f"land/train-{marked['--train']}-{marked['--attempt']}"
                return 0, json.dumps({"schema": 1, "slot": "tollman-hal2", "kind": "train", "current": None, "next": name})
            calls.append(argv)
            marked.update({k: argv[argv.index(k) + 1] for k in ("--train", "--attempt") if k in argv})
            return 0, ""

        train = train_state.standing(rows)
        with (mock.patch.object(engine, "here", return_value=(MAIN, "tollman-hal2", train, "/farm/tollman-hal2")),
              mock.patch.object(engine.frozen, "lacking", return_value=[]),
              mock.patch.object(engine, "fresh", return_value=(0, "c" * 40)),
              mock.patch.object(engine, "cli", side_effect=cli),
              mock.patch.object(engine.train_state, "folder", return_value=Path(tempfile.mkdtemp())),
              mock.patch.object(engine.train_state, "append", side_effect=lambda *a, **kw: written.append(kw)),
              mock.patch.object(engine.train_wt, "to_run", return_value=(0, "")) as named,  # no carrier here (D18)
              mock.patch.object(engine, "spawn", return_value=4711) as spawn):
            code, text = engine.restart("/farm/tollman-hal2")
        if not train.get("number"):
            return code, text, spawn
        self.assertEqual(code, 0, text)
        named.assert_called_once_with("/farm/tollman-hal2", train["number"], train["starts"] + 1)  # plan 0610 D18
        return calls[0], spawn.call_args.args[2], written[-1]["land_ref"]

    def test_a_numbered_train_s_first_start_records_what_land_ref_says_and_lands_on_it(self):
        mark, spawned_ref, land_ref_ = self._restart([NUMBERED])
        self.assertEqual(mark, ["worktree", "queue", "train", "tollman-hal2", "02", "07", "--train", "7", "--attempt", "1",
                                "--json"])
        self.assertEqual((spawned_ref, land_ref_), (None, "train-7-1"))

    def test_a_numbered_train_s_second_start_is_marked_train_n_attempt_2_and_lands_on_train_n_2(self):
        rows = [NUMBERED, line("started", pid=1, land_ref="train-7-1"), line("red", status="gate_failed"),
                line("retry", why="flaky")]
        mark, spawned_ref, land_ref_ = self._restart(rows)
        self.assertEqual(mark, ["worktree", "queue", "train", "tollman-hal2", "02", "07", "--train", "7", "--attempt", "2",
                                "--json"])
        self.assertEqual((spawned_ref, land_ref_), (None, "train-7-2"), "no --land-ref: merge-to-main picks the branch")

    def test_a_train_without_a_number_is_never_started_and_a_land_ref_the_cli_refuses_stops_the_start(self):
        code, text, spawn = self._restart([FORMED])
        self.assertEqual(code, 1)
        self.assertIn("no number", text)
        spawn.assert_not_called()
        train = train_state.standing([NUMBERED])
        refused = lambda argv, cwd: (1, json.dumps({"error": {"message": "tollman-hal2 has no numbered mark"}})) \
            if argv[:2] == ["worktree", "land-ref"] else (0, "")
        with (mock.patch.object(engine, "here", return_value=(MAIN, "tollman-hal2", train, "/farm/tollman-hal2")),
              mock.patch.object(engine.frozen, "lacking", return_value=[]),
              mock.patch.object(engine, "cli", side_effect=refused),
              mock.patch.object(engine.train_wt, "to_run", return_value=(0, "")),
              mock.patch.object(engine, "spawn") as spawn):
            code, text = engine.restart("/farm/tollman-hal2")
        self.assertEqual(code, 1)
        self.assertIn("was not named: tollman-hal2 has no numbered mark", text)
        spawn.assert_not_called()

    def test_spawn_adds_land_ref_only_when_given(self):
        for ref, tail in (("train-0383-0365", ["--land-ref", "train-0383-0365"]), (None, [])):
            with mock.patch.object(engine.subprocess, "Popen") as popen:
                popen.return_value.pid = 1
                engine.spawn("/farm/x", Path(tempfile.mkdtemp()) / "log", ref)
            self.assertEqual(popen.call_args.args[0][2:], ["land", "--repo", "/farm/x"] + tail)

    def test_land_passes_the_branch_to_merge_to_main(self):
        out = Path(tempfile.mkdtemp()) / "argv.json"
        script = f"import json, sys; json.dump(sys.argv[1:], open({str(out)!r}, 'w'))"
        with (mock.patch.object(engine, "LAND", [sys.executable, "-c", script, "--json"]),
              mock.patch.object(engine, "cli", return_value=(0, "")),  # the pid on the mark (plan 0375 D2)
              mock.patch.object(engine.land_name, "refuses", return_value=0),  # its own test: test_land_name
              mock.patch.object(engine.next_train, "before_push", return_value=[]),
              mock.patch.object(engine.pretest_train, "before_landing", return_value=False)):
            self.assertEqual(engine.land(tempfile.mkdtemp(), "train-0383-0365"), 0)
        self.assertEqual(json.loads(out.read_text()), ["--json", "--land-ref", "train-0383-0365"])
        self.assertEqual(engine.LAND, ["hal2-cli-git", "worktree", "merge-to-main", "--json"])


if __name__ == "__main__":
    unittest.main()
