"""`tollman.py triage` (hal2 plan 0360 step 5): the standing train's run triaged for the session, gh faked."""

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import tollman
import train_state
import triage
from gh_fake import FakeGh, job

AT = "2026-10-17T10:00:00Z"
NAME = "07+09@" + AT
URL = "https://github.com/x/actions/runs/701"


class TriageCli(unittest.TestCase):
    def setUp(self):
        self.main = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.main, True)
        for p in (mock.patch.object(triage.mtm_scan, "main_checkout", lambda top: self.main),
                  mock.patch.object(triage, "main_head", lambda main: "")):
            p.start()
            self.addCleanup(p.stop)
        train_state.folder(self.main).mkdir(parents=True)
        self.addCleanup(shutil.rmtree, train_state.folder(self.main).parents[2], True)
        FakeGh(jobs={"701": [job("d1-01-rust-test", step="cargo nextest")]},
               logs={"701": "test hub::tenant_rls ... FAILED\n"}).start(self)

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = tollman.main(["triage", *argv, "--repo", self.main])
        return code, out.getvalue()

    def test_the_standing_train_s_run_or_a_named_one(self):
        self.assertEqual(self.cli()[0], 1, "no train, no run: nothing to triage")
        train_state.append(self.main, "formed", "tollman-hal2", train=NAME, cars=[], base="b" * 40)
        train_state.append(self.main, "started", "tollman-hal2", train=NAME, pid=1)
        train_state.append(self.main, "run", "tollman-hal2", train=NAME, run=URL)
        code, text = self.cli()
        self.assertEqual(code, 0)
        for part in ("triage: car", "d1-01-rust-test: cargo nextest", "hub::tenant_rls"):
            self.assertIn(part, text)
        code, text = self.cli("701", "--json")
        self.assertEqual((code, json.loads(text)["kind"]), (0, "car"))


if __name__ == "__main__":
    unittest.main()
