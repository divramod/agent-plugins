"""L127 (D15, plan 0490 step 11): train 27's c1-02-rust-build-mac ran 3 h (7 min on 10-28) and nobody flagged it.
A land-run job over 2x its median in the last green runs is flagged at once by the watch, once, and wakes."""

import datetime as dt
import json
import unittest

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import slow_jobs
from gh_fake import run
from test_minute import RUN, Pass

NOW = dt.datetime.now(dt.timezone.utc)
MAC = "c1-02-rust-build-mac"


def timed(name, minutes, status="completed", ago=0):
    end = NOW - dt.timedelta(minutes=ago)
    start = end - dt.timedelta(minutes=minutes)
    return {"name": name, "status": status, "conclusion": "success" if status == "completed" else None,
            "startedAt": start.isoformat(), "completedAt": end.isoformat() if status == "completed" else None}


class Events(unittest.TestCase):
    def test_over_twice_the_median_and_the_floor_is_slow_a_short_job_never(self):
        medians = {MAC: 7 * 60, "a1-01-lint": 40}
        jobs = [timed(MAC, 180, "in_progress"), timed("a1-01-lint", 3)]
        got = slow_jobs.events("501", jobs, medians, NOW)
        self.assertEqual([e["key"] for e in got], [f"slow:501:{MAC}"], "3 min against 40 s is under the floor")
        self.assertIn("runs 180 min, over 2x its median 7 min", got[0]["text"])
        self.assertEqual(slow_jobs.events("501", [timed(MAC, 13, "in_progress")], medians, NOW), [], "under 2x")
        self.assertEqual(slow_jobs.events("501", [{"name": MAC, "status": "queued"}], medians, NOW), [])


class Watch(Pass):
    def test_train_27_the_watch_flags_the_three_hour_mac_build_once_and_wakes(self):
        green = [run(r, f"land/train-{r}-1", "2026-10-28T08:00:00Z", conclusion="success") for r in (401, 402, 403)]
        self.gh.runs[:] = [RUN] + green
        for r, minutes in ((401, 7), (402, 8), (403, 6)):
            self.gh.jobs[str(r)] = [timed(MAC, minutes, ago=2000), timed("a1-01-lint", 1, ago=2000)]
        self.gh.jobs["501"] = [timed(MAC, 180, "in_progress"), timed("a1-01-lint", 1)]
        self.train("formed", "started")
        out = self.tick()
        self.assertIn(f"job slow: {MAC} runs 180 min, over 2x its median 7 min", out)
        state = json.loads((self.wm_state / "watch-events.json").read_text())
        self.assertEqual(state["base"], {MAC: 7 * 60, "a1-01-lint": 60}, "the medians are kept with the run")
        woke = json.loads((self.wm_state / "wake.json").read_text())["items"]
        self.assertEqual([(i["duty"], i["kind"]) for i in woke], [("trains", "slow-job")])
        calls = len(self.gh.calls)
        self.assertNotIn("job slow", self.tick(), "told once")
        self.assertFalse([c for c in self.gh.calls[calls:] if c[3:4] in (["401"], ["402"], ["403"])],
                         "the medians are not read again")


if __name__ == "__main__":
    unittest.main()
