"""Plan 0490 step 16 (L134 = L97): the watch follows only the landing workflow's run of the train's branch. The
other landing workflow's run, which GitHub skips after a second, is never followed (train 28's second start
followed merge-to-main-local 41021557135 while the real run was merge-to-main-cloud 41021557194). gh is
gh_fake.py's, listing per `--workflow`."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import gh_runs
import train_state
import watch
from gh_fake import FakeGh, run

AT = "2026-10-30T07:30:00Z"
NAME = "28+09@" + AT
BRANCH = "land/train-28-2"
FORMED = {"schema": 1, "at": AT, "kind": "formed", "slot": "tollman-hal2", "train": NAME, "base": "b" * 40,
          "cars": [{"field": "28", "branch": "28", "head": "2" * 40, "plan": "0490-x"}]}
STARTED = {"schema": 1, "at": "2026-10-30T07:39:00Z", "kind": "started", "slot": "tollman-hal2", "train": NAME,
           "pid": 1, "land_ref": "train-28-2"}
SKIPPED = run(41021557135, BRANCH, "2026-10-30T07:40:03Z", conclusion="skipped")  # newest
CLOUD = run(41021557194, BRANCH, "2026-10-30T07:40:02Z", status="in_progress")


class PerWorkflow(FakeGh):
    """The runs of each landing workflow file, each row carrying its file (`path`), as plan 0480's one runs list
    (`gh api .../actions/runs`) gives them; `by_file` may be replaced between two reads."""

    def __init__(self, by_file):
        super().__init__([])
        self.by_file = by_file

    @property
    def by_file(self):
        return self._by_file

    @by_file.setter
    def by_file(self, value):
        self._by_file = value
        self.runs = [{**r, "path": f".github/workflows/{f}"} for f, rs in value.items() for r in rs]


class Skipped(unittest.TestCase):
    def home(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return tmp.name

    def find(self, by_file, setting=None):
        PerWorkflow(by_file).start(self)
        home = self.home()
        if setting:
            Path(home, ".hal").mkdir()
            Path(home, ".hal", "landing.toml").write_text(f'workflow = "{setting}"\n')
        rows = [FORMED, STARTED]
        with mock.patch.dict(os.environ, {"HAL2_LAND_WORKFLOW": ""}):
            return watch.find(home, train_state.standing(rows), rows)

    def test_the_cloud_run_is_followed_not_the_skipped_local_one_on_the_same_branch(self):
        files = {"merge-to-main-local.yml": [SKIPPED], "merge-to-main-cloud.yml": [CLOUD]}
        self.assertEqual(self.find(files, "cloud"), (CLOUD["url"], True))
        self.assertEqual(self.find(files), (CLOUD["url"], True), "no setting: the skip alone decides")

    def test_a_lone_skipped_run_is_not_followed(self):
        self.assertEqual(self.find({"merge-to-main-local.yml": [SKIPPED]}, "cloud"), (None, False))

    def test_the_settings_workflow_comes_first_when_both_run(self):
        local = run(41021557300, BRANCH, "2026-10-30T07:41:00Z", status="in_progress")  # newer, the other file's
        files = {"merge-to-main-local.yml": [local], "merge-to-main-cloud.yml": [CLOUD]}
        self.assertEqual(self.find(files, "cloud"), (CLOUD["url"], True))
        self.assertEqual(self.find(files, "local"), (local["url"], True))
        self.assertEqual(self.find(files), (local["url"], True), "no setting: the newest, as before")

    def test_no_new_gh_call_the_round_s_lists_are_the_only_ones(self):
        gh = PerWorkflow({"merge-to-main-cloud.yml": [CLOUD]}).start(self)
        home = self.home()
        Path(home, ".hal").mkdir()
        Path(home, ".hal", "landing.toml").write_text('workflow = "cloud"\n')
        rows = [FORMED, STARTED]
        with mock.patch.dict(os.environ, {"HAL2_LAND_WORKFLOW": ""}), gh_runs.round(None):
            watch.find(home, train_state.standing(rows), rows)
        self.assertEqual((gh.runs_lists(), len(gh.calls)), (1, 1), "the round's one runs list, none more")


if __name__ == "__main__":
    unittest.main()
