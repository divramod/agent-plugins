"""Plan 0490 step 11: ci-health tells a queued job's problem once for its run's life (L72: b1-01-ci-changes of run
39483749722 woke twice in an hour as the problem flapped) and reads the standing train's own runner list for a job
the barn's list cannot serve (L91: car 17 renamed mac-host-a to mac-host-hal2-a, train 16 woke `unserved`)."""

import datetime as dt
import unittest

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import ci_fleet
import train_state
from gh_fake import api_job, runner
from test_ci_health import Health, stamp

AZ02 = ["self-hosted", "linux", "x64", "az02-host-gone"]  # in no runner list
RENAMED = ["self-hosted", "macOS", "ARM64", "mac-host-renamed-a"]


class Flap(Health):
    def test_l72_a_flapping_job_problem_wakes_once_for_its_run(self):
        job = api_job(9, "b1-01-ci-changes", AZ02, stamp(self.now - dt.timedelta(minutes=4)))
        self.queue(job)
        (a,) = self.check(0)
        self.assertIn("no runner of hal2-runners.toml has these labels", a["text"])
        self.queue()
        self.assertEqual(self.check(1), [], "cleared for a pass")
        self.queue(job)
        self.assertEqual(self.check(2), [], "back: the same run's job, told already")
        self.assertEqual(self.check(30), [], "half an hour later still")
        self.queue(api_job(10, "b1-01-ci-changes", AZ02, stamp(self.now)))
        self.assertEqual(len(self.check(40)), 1, "a new job (a new run's) is a new problem")


class TrainRunners(Health):
    def test_l91_a_label_only_the_train_s_runner_list_has_is_served(self):
        job = api_job(11, "c1-02-rust-build-mac", RENAMED, stamp(self.now - dt.timedelta(minutes=4)))
        self.queue(job)
        self.assertEqual(len(self.check(0)), 1, "no standing train: unserved")
        wt = self.tmp / "tollman-train-0417"
        (wt / ".github").mkdir(parents=True)
        (wt / ci_fleet.TOML).write_text((self.main / ci_fleet.TOML).read_text() + '\n[[runners]]\ncode = '
                                        '"mac-host-renamed-a"\nname = "mac-renamed-a"\nlabels = ["self-hosted", '
                                        '"macOS", "ARM64", "mac-host-renamed-a"]\n')
        train_state.append(str(self.main), "formed", "tollman-hal2", train="17@x", cars=[], base="b" * 40,
                           worktree=str(wt))
        self.gh.runners = self.gh.runners + [runner("mac-renamed-a", "online", RENAMED)]
        self.queue(api_job(12, "c1-02-rust-build-mac", RENAMED, stamp(self.now - dt.timedelta(minutes=4))))
        self.assertEqual(self.check(1), [], "the train's runner carries the labels and is online")


if __name__ == "__main__":
    unittest.main()
