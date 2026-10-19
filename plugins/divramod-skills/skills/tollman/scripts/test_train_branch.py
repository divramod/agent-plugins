"""Hal2 plan 0383 step 1 (D2, L34): every train lands on its own branch `land/train-<plan>-<plan>-...`, named by
its cars' plans: `restart` writes the name into its `started` line and starts the landing with it, `land` passes it
to `hal2-cli-git worktree merge-to-main --land-ref`, and the watch looks for the run on that branch only. gh is
gh_fake.py's: no real call."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import engine
import train_branch
import train_state
import watch
from gh_fake import FakeGh, run

AT = "2026-10-18T10:00:00Z"
NAME = "02+07@" + AT
MAIN = "/no/such/farm"
CARS = [{"field": "02", "branch": "02", "head": "2" * 40, "plan": "0383-train-rules"},
        {"field": "07", "branch": "07", "head": "7" * 40, "plan": "0365-ci-lanes"}]


def line(kind, at=AT, **kw):
    return {"schema": 1, "at": at, "kind": kind, "slot": "tollman-hal2", "train": NAME, **kw}


FORMED = line("formed", cars=CARS, base="b" * 40)
STARTED = line("started", at="2026-10-18T10:05:00Z", pid=4711, land_ref="train-0383-0365")


class Name(unittest.TestCase):
    def test_the_train_s_branch_is_its_plans_numbers_in_train_order(self):
        self.assertEqual(train_branch.name(CARS), "train-0383-0365")
        self.assertEqual(train_branch.name(list(reversed(CARS))), "train-0365-0383")

    def test_a_car_without_a_plan_rides_by_its_field_and_a_part_is_named_once(self):
        cars = [{"field": "09", "plan": ""}, {"field": "Tollman_HAL2", "plan": "shots/3/fix-it"},
                {"field": "02", "plan": "0383-train-rules"}, {"field": "03", "plan": "0383-train-rules"}]
        self.assertEqual(train_branch.name(cars), "train-09-tollmanhal2-0383")
        self.assertEqual(train_branch.name([]), "train-car")

    def test_the_name_is_one_hal2_cli_git_takes(self):
        self.assertEqual(train_branch.name([{"field": "probe1"}]), "train-prb1", "never `probe`: a replay")
        long = [{"field": f"{n:02}", "plan": f"{1000 + n}-x"} for n in range(60)]
        name = train_branch.name(long)
        self.assertLessEqual(len("land/" + name), 200)
        self.assertRegex(name, r"^train-1000-1001-.*-plus\d+$")
        self.assertRegex(name, r"^train-[a-z0-9]+(-[a-z0-9]+)*$")

    def test_the_branch_watched_is_the_started_line_s_else_the_carrier_s(self):
        self.assertEqual(train_branch.land(train_state.standing([FORMED, STARTED])), "land/train-0383-0365")
        old = line("started", at="2026-10-18T10:05:00Z", pid=4711)
        self.assertEqual(train_branch.land(train_state.standing([FORMED, old])), "land/tollman-hal2",
                         "a train started before plan 0383")


class Watch(unittest.TestCase):
    def test_the_run_is_found_on_the_train_s_own_branch_only(self):
        ours = run(601, "land/train-0383-0365", "2026-10-18T10:06:00Z", status="in_progress")
        FakeGh([run(602, "land/tollman-hal2", "2026-10-18T10:07:00Z", status="in_progress"), ours]).start(self)
        rows = [FORMED, STARTED]
        self.assertEqual(watch.find(MAIN, train_state.standing(rows), rows), (ours["url"], True))
        FakeGh([run(602, "land/tollman-hal2", "2026-10-18T10:07:00Z")]).start(self)
        self.assertEqual(watch.find(MAIN, train_state.standing(rows), rows), (None, False),
                         "the carrier's old branch is another train's")


class Engine(unittest.TestCase):
    def test_restart_names_the_branch_in_its_started_line_and_lands_on_it(self):
        state = Path(tempfile.mkdtemp())
        written = []
        train = train_state.standing([FORMED])
        with (mock.patch.object(engine, "here", return_value=(MAIN, "tollman-hal2", train, "/farm/tollman-hal2")),
              mock.patch.object(engine.frozen, "complete", return_value=(0, "")),
              mock.patch.object(engine, "cli", return_value=(0, "")),
              mock.patch.object(engine.train_state, "folder", return_value=state),
              mock.patch.object(engine.train_state, "append", side_effect=lambda *a, **kw: written.append(kw)),
              mock.patch.object(engine, "spawn", return_value=4711) as spawn):
            code, text = engine.restart("/farm/tollman-hal2")
        self.assertEqual(code, 0, text)
        self.assertEqual(spawn.call_args.args[2], "train-0383-0365")
        self.assertEqual(written[-1]["land_ref"], "train-0383-0365")

    def test_land_passes_the_branch_to_merge_to_main(self):
        out = Path(tempfile.mkdtemp()) / "argv.json"
        script = f"import json, sys; json.dump(sys.argv[1:], open({str(out)!r}, 'w'))"
        with (mock.patch.object(engine, "LAND", [sys.executable, "-c", script, "--json"]),
              mock.patch.object(engine, "cli", return_value=(0, "")),  # the pid on the mark (plan 0375 D2)
              mock.patch.object(engine.next_train, "before_push", return_value=[]),
              mock.patch.object(engine.pretest_train, "before_landing", return_value=False)):
            self.assertEqual(engine.land(tempfile.mkdtemp(), "train-0383-0365"), 0)
        self.assertEqual(json.loads(out.read_text()), ["--json", "--land-ref", "train-0383-0365"])
        self.assertEqual(engine.LAND, ["hal2-cli-git", "worktree", "merge-to-main", "--json"])


if __name__ == "__main__":
    unittest.main()
