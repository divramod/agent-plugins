import datetime as dt
import unittest

import mtm_ci


def run(rid, branch, status="completed", conclusion="success", at="2026-10-05T06:00:00Z"):
    return {"databaseId": rid, "headBranch": branch, "headSha": "a" * 40, "status": status,
            "conclusion": conclusion, "createdAt": at, "url": f"https://x/runs/{rid}"}


class MtmCiTest(unittest.TestCase):
    def test_land_runs_become_landing_rows_and_probes_are_left_out(self):
        jobs = {2: [{"name": "linux / rust-test", "conclusion": "failure"},
                    {"name": "park", "conclusion": "failure"}, {"name": "gate", "conclusion": "failure"}]}
        rows = mtm_ci.summary([run(1, "land/07"), run(2, "land/03", conclusion="failure"),
                               run(3, "land/12-probe"), run(4, "land/05", status="in_progress", conclusion=""),
                               run(5, "main")], lambda rid: jobs.get(rid, []), 0)
        self.assertEqual([(r["slot"], r["outcome"], r["task"]) for r in rows],
                         [("07", "landed", ""), ("03", "failed", "linux / rust-test, gate"), ("05", "running", "")])
        self.assertEqual(mtm_ci.running_run(rows, "05")["url"], "https://x/runs/4")

    def test_a_run_is_landed_once_merge_succeeded_whatever_its_ship_jobs_do(self):
        jobs = {1: [{"name": "merge", "conclusion": "success"}, {"name": "ship / deliver", "conclusion": "failure"}],
                2: [{"name": "merge", "conclusion": "success"}, {"name": "ship / publish", "conclusion": None}],
                3: [{"name": "gate", "conclusion": "failure"}, {"name": "ship / deliver", "conclusion": "failure"}]}
        rows = mtm_ci.summary([run(1, "land/07", conclusion="failure"),
                               run(2, "land/03", status="in_progress", conclusion=""),
                               run(3, "land/05", conclusion="failure")], lambda rid: jobs.get(rid, []), 0)
        self.assertEqual([(r["slot"], r["outcome"], r["task"]) for r in rows],
                         [("07", "landed", ""), ("03", "landed", ""), ("05", "failed", "gate")])

    def test_a_red_macos_build_job_is_no_red_of_a_candidate(self):
        # Plan 0263 D64: `mac-vm-build`'s jobs run beside the checks, outside `gate`'s needs, and carry no stop step.
        build = {"name": "03-lmm1vx/rust-bundle-apps-macos", "conclusion": "failure"}
        jobs = {1: [{"name": "05-xxx1hx/merge", "conclusion": "success"}, build,
                    {"name": "06-lmm1ha/deliver", "conclusion": "failure"}],
                2: [{"name": "02-vhl1hb/rust-test", "conclusion": "failure"}, build,
                    {"name": "03-lmm1vx/ts-bundle-desktop-macos", "conclusion": "cancelled"},
                    {"name": "04-xxx1hx/gate", "conclusion": "failure"}]}
        rows = mtm_ci.summary([run(1, "land/07", conclusion="failure"), run(2, "land/03", conclusion="failure")],
                              lambda rid: jobs.get(rid, []), 0)
        self.assertEqual([(r["slot"], r["outcome"], r["task"]) for r in rows],
                         [("07", "landed", ""), ("03", "failed", "02-vhl1hb/rust-test, 04-xxx1hx/gate")])
        self.assertTrue(mtm_ci.is_build("03-lmm1va/ts-bundle-desktop-macos"))
        # Plan 0263 D128: the build's plan on the Mac host, red (no VM came up): the landing stands, the candidate's
        # red is its check's alone.
        plan = {"name": "03-lmm1ha/mac-vm-build-plan", "conclusion": "failure"}
        jobs = {1: [{"name": "05-xxx1hx/merge", "conclusion": "success"}, plan],
                2: [{"name": "02-vhl1hb/rust-test", "conclusion": "failure"}, plan,
                    {"name": "04-xxx1hx/gate", "conclusion": "failure"}]}
        rows = mtm_ci.summary([run(1, "land/07", conclusion="failure"), run(2, "land/03", conclusion="failure")],
                              lambda rid: jobs.get(rid, []), 0)
        self.assertEqual([(r["slot"], r["outcome"], r["task"]) for r in rows],
                         [("07", "landed", ""), ("03", "failed", "02-vhl1hb/rust-test, 04-xxx1hx/gate")])
        self.assertTrue(mtm_ci.is_build("04-lmm1vx/rust-bundle-apps-macos"))
        self.assertFalse(any(mtm_ci.is_build(n) for n in (
            "03-lmm1vx/bash-test", "02-vhl1hb/rust-bundle-apps-linux", "03-xxx1hx/macos-build-nothing-to-run",
            "rust-bundle-apps-macos", "b / rust-bundle-apps-macos", "06-lmm1ha/deliver", "mac-vm-build-plan",
            "02-lmm1ha/mac-vm-wake", "")))

    def test_stage_and_code_names_read_as_the_old_ones_did(self):
        jobs = {1: [{"name": "05-xxx1hx/merge", "conclusion": "success"},
                    {"name": "06-lmm1ha/deliver", "conclusion": "failure"}],
                2: [{"name": "05-xxx1hx/merge", "conclusion": "failure"}, {"name": "04-xxx1hx/gate", "conclusion": "failure"},
                    {"name": "06-vhl1hx/docker-publish-github-runner-image", "conclusion": "failure"},
                    {"name": "02-vhl1hx/rust-test", "conclusion": "failure"}, {"name": "mac-host-ship / deliver", "conclusion": "failure"},
                    {"name": "linux-light-ship / x", "conclusion": "failure"}, {"name": "07-lmm1ha/ts-publish-desktop-all", "conclusion": "failure"}]}
        rows = mtm_ci.summary([run(1, "land/07", conclusion="failure"), run(2, "land/03", conclusion="failure")],
                              lambda rid: jobs.get(rid, []), 0)
        self.assertEqual([(r["slot"], r["outcome"], r["task"]) for r in rows],
                         [("07", "landed", ""), ("03", "failed", "04-xxx1hx/gate, 02-vhl1hx/rust-test")])
        self.assertTrue(all(mtm_ci.is_ship(n) for n in ("ship / deliver", "08-lmm1ha/linux-host-ship-start", "x / publish-claude-plugins",
                                                         "06-lmm1ha/tmux-publish-hal9k")))
        self.assertFalse(mtm_ci.is_ship("06-xxx1hx/all-tag-versions"))
        self.assertEqual([mtm_ci.job_part(n) for n in ("merge", "a / merge", "05-xxx1hx/merge", "park")],
                         ["merge", "merge", "merge", "park"])

    def test_runner_alias_names_read_as_the_old_codes_did(self):
        self.assertEqual([mtm_ci.job_part(n) for n in ("05-x-host-x/merge", "02-hz01-host-a/bash-lint", "02-mac-host-0/monitor", "05-xxx1hx/merge")],
                         ["merge", "bash-lint", "monitor", "merge"])
        self.assertTrue(mtm_ci.is_ship("06-mac-host-a/deliver"))

    def test_the_position_in_the_lane_is_no_part_of_the_job(self):
        # Plan 0349 D40: `<stage>-<alias>/<NN>-<job>`; the older names stay as they were.
        self.assertEqual([mtm_ci.job_part(n) for n in ("03-hz01-host-b/01-merge", "02-hz01-host-b/03-rust-lint",
                                                       "03-hz01-host-a/01-stack-test", "04-xxx1hx/02-gate", "01-merge")],
                         ["merge", "rust-lint", "stack-test", "gate", "01-merge"])
        self.assertTrue(all(mtm_ci.is_ship(n) for n in ("04-mac-host-a/05-ci-cache-clean-mac-host",
                                                         "04-mac-host-a/01-git-pull-main", "04-mac-vm-a/02-agents-publish",
                                                         "04-mac-host-b/01-hub-deploy")))
        self.assertFalse(mtm_ci.is_ship("03-hz01-host-b/01-merge"))
        self.assertTrue(all(mtm_ci.is_build(n) for n in ("02-mac-vm-a/01-tmux-build-mac", "03-mac-host-a/02-mac-vm-build-plan")))
        self.assertFalse(mtm_ci.is_build("02-mac-vm-a/01-bash-test"))
        jobs = {1: [{"name": "03-hz01-host-b/01-merge", "conclusion": "success"},
                    {"name": "04-mac-host-a/05-ci-cache-clean-mac-host", "conclusion": "failure"},
                    {"name": "02-mac-vm-a/01-rust-build-mac", "conclusion": "failure"}]}
        self.assertTrue(mtm_ci.merged(jobs[1]))
        self.assertEqual(mtm_ci.red_jobs(jobs[1]), [], "a red delivery cleanup and a red build are no red of the landing")
        jobs[1].append({"name": "02-hz01-host-b/03-rust-lint", "conclusion": "failure"})
        self.assertEqual(mtm_ci.red_jobs(jobs[1]), ["02-hz01-host-b/03-rust-lint"])

    def test_the_matrix_alias_names_since_d101(self):
        # Plan 0349 D101: `<stage letter><matrix digit>-<NN>-<job>`, the merge as git-merge; the older names still parse.
        self.assertEqual([mtm_ci.job_part(n) for n in ("d2-01-git-merge", "c3-03-rust-lint", "d1-01-stack-test",
                                                       "a1-01-ci-route", "g1-02-ci-cache-clean-mac-host")],
                         ["git-merge", "rust-lint", "stack-test", "ci-route", "ci-cache-clean-mac-host"])
        self.assertTrue(all(mtm_ci.is_ship(n) for n in ("g1-02-ci-cache-clean-mac-host", "e2-01-git-pull-main",
                                                         "e3-01-agents-publish", "e4-01-hub-deploy")))
        self.assertFalse(mtm_ci.is_ship("d2-01-git-merge"))
        self.assertTrue(all(mtm_ci.is_build(n) for n in ("c1-01-tmux-build-mac", "c4-02-tmux-test-mac")))
        self.assertFalse(mtm_ci.is_build("c4-01-bash-test"))
        jobs = [{"name": "d2-01-git-merge", "conclusion": "success"},
                {"name": "g1-02-ci-cache-clean-mac-host", "conclusion": "failure"},
                {"name": "c1-02-rust-build-mac", "conclusion": "failure"}]
        self.assertTrue(mtm_ci.merged(jobs))
        self.assertEqual(mtm_ci.red_jobs(jobs), [])
        jobs[0]["conclusion"] = "failure"
        self.assertFalse(mtm_ci.merged(jobs))
        self.assertEqual(mtm_ci.red_jobs(jobs), [], "a red git-merge is main moved, as a red merge was")
        jobs.append({"name": "c3-03-rust-lint", "conclusion": "failure"})
        self.assertEqual(mtm_ci.red_jobs(jobs), ["c3-03-rust-lint"])

    def test_a_job_that_stops_its_run_fails_it_at_once_and_the_cancelled_jobs_only_stopped(self):
        # `gh run view --json jobs`, shaped after land run 38215106904 with the lanes' stop step; the job that stops
        # its run mostly ends `cancelled` itself (gate jobs 113753096365, 114169773542), its failed step `failure`.
        def job(name, conclusion, work, stop="skipped"):
            steps = [{"name": "Set up job", "conclusion": "success"}, {"name": "[07] gate", "conclusion": work}]
            steps += [{"name": "[19] fail fast: stop the run", "conclusion": stop}] if stop is not None else []
            return {"name": name, "conclusion": conclusion, "status": "completed" if conclusion else "in_progress",
                    "steps": steps}
        failing = job("02-vhl1ha/python-test", "", "failure", "success")  # its step failed, its stop step ran
        cut = lambda name, stop="skipped": job(name, "cancelled", "cancelled", stop)
        gate = lambda conclusion: {"name": "04-xxx1hx/gate", "conclusion": conclusion, "steps": []}
        merge = {"name": "05-xxx1hx/merge", "conclusion": "skipped", "steps": []}
        jobs = {1: [failing, job("02-vhl1hb/rust-test", "", "", "")],  # the others still run
                2: [job("02-vhl1ha/python-test", "cancelled", "failure", "success"), cut("02-lmm1ha/bash-test"),
                    cut("02-vzw1ha/rust-test-windows", None), gate("cancelled"), merge],  # the run it cancelled
                3: [job("02-vhl1ha/python-test", "success", "success"), job("02-vhl1hb/rust-test", "", "", ""),
                    job("02-vhl1h0/monitor", "failure", "failure", None)],  # a red job without the step: nothing
                4: [job("02-vhl1ha/python-test", "failure", "failure", None),
                    job("02-vhl1hb/rust-test", "", "", None)],  # a file without the step: as before
                5: [cut("02-vhl1ha/python-test"), cut("02-vhl1hb/rust-test"), gate("failure")],  # a pause's cancel
                6: [cut("02-lmm1ha/bash-test", "success"), cut("02-vhl1hb/rust-test"), gate("failure"), merge],
                7: [job("02-vhl1ha/python-test", "", "failure", ""),  # a failed step while its job goes on,
                    job("02-vhl1hb/rust-test", "success", "failure")]}  # and one its job survived: nothing
        rows = mtm_ci.summary([run(1, "land/01", status="in_progress", conclusion=""),
                               run(2, "land/02", conclusion="cancelled"),
                               run(3, "land/03", status="in_progress", conclusion=""),
                               run(4, "land/04", status="in_progress", conclusion=""),
                               run(5, "land/05", conclusion="cancelled"), run(6, "land/06", conclusion="cancelled"),
                               run(7, "land/07", status="in_progress", conclusion="")],
                              lambda rid: jobs.get(rid, []), 0)
        self.assertEqual([(r["slot"], r["outcome"], r["task"]) for r in rows],
                         [("01", "failed", "02-vhl1ha/python-test"),
                          ("02", "failed", "02-vhl1ha/python-test, 04-xxx1hx/gate"),
                          ("03", "running", ""), ("04", "running", ""),
                          ("05", "failed", "02-vhl1ha/python-test, 02-vhl1hb/rust-test, 04-xxx1hx/gate"),
                          ("06", "failed", "02-lmm1ha/bash-test, 04-xxx1hx/gate"),  # a time limit: no step failed
                          ("07", "running", "")])
        self.assertTrue(all(mtm_ci.needed({"steps": [{"name": n}]}) for n in
                            ("[08] fail fast: stop the run", " [19]  fail fast: stop the run ", "fail fast: stop the run")))
        self.assertFalse(any(mtm_ci.needed({"steps": [{"name": n}]}) for n in
                             ("[01] fail fast", "[08] fail fast: stop the run later", "[x] fail fast: stop the run")))
        self.assertFalse(mtm_ci.needed({"name": "04-xxx1hx/gate"}))
        self.assertFalse(mtm_ci.cause(cut("02-vhl1hb/rust-test", "cancelled")))  # a stop step cut short proves nothing
        stopped = job("02-vhl1ha/ts-lint", "failure", "skipped", "success")  # row 3's start step stopped it: no work
        stopped["steps"].insert(0, {"name": "[01] fail fast", "conclusion": "failure"})
        self.assertFalse(mtm_ci.cause(stopped))

    def test_a_step_that_failed_after_the_cancel_is_no_cause_and_a_refused_stop_step_is_one(self):
        def job(conclusion, *steps):
            return {"name": "02-vhl1ha/python-test", "conclusion": conclusion,
                    "status": "completed" if conclusion else "in_progress",
                    "steps": [{"name": name, "conclusion": c} for name, c in steps]}
        work, keep, stop = "[07] gate python-test", "[13] keep what the job left", "[19] fail fast: stop the run"
        # A pause's cancel cut the job's work; a later step then failed in the cancelled job: the cancel is no red.
        after = job("cancelled", (work, "cancelled"), (keep, "failure"), (stop, "skipped"))
        # A step failed, the run's cancel then cut a later one: the failure came first and stays the cause.
        before = job("cancelled", (work, "failure"), (keep, "cancelled"), (stop, "skipped"))
        # The time limit cut the work, a later step failed, the stop step ran: a cause by its stop step alone.
        limit = job("cancelled", (work, "cancelled"), (keep, "failure"), (stop, "success"))
        # The stop step ran and GitHub refused the request: the job is a cause, the run goes on.
        refused = job("", (work, "failure"), (keep, "success"), (stop, "failure"))
        alone = job("", (work, "cancelled"), (stop, "failure"))  # at its limit, the request refused
        self.assertEqual([mtm_ci.cause(j) for j in (after, before, limit, refused, alone)],
                         [False, True, True, True, True])
        gate = {"name": "04-xxx1hx/gate", "conclusion": "failure", "steps": []}
        going = {"name": "02-vhl1hb/rust-test", "conclusion": "", "status": "in_progress",
                 "steps": [{"name": "[07] gate rust-test", "conclusion": ""}, {"name": stop, "conclusion": ""}]}
        jobs = {1: [after, gate], 2: [refused, going], 3: [after, going]}
        rows = mtm_ci.summary([run(1, "land/01", conclusion="cancelled"),
                               run(2, "land/02", status="in_progress", conclusion=""),
                               run(3, "land/03", status="in_progress", conclusion="")],
                              lambda rid: jobs.get(rid, []), 0)
        self.assertEqual([(r["slot"], r["outcome"], r["task"]) for r in rows],
                         [("01", "failed", "02-vhl1ha/python-test, 04-xxx1hx/gate"),  # no cause: read as before
                          ("02", "failed", "02-vhl1ha/python-test"),  # red at once, by the refused stop step
                          ("03", "running", "")])

    def test_a_stop_step_still_in_progress_is_ending_and_never_a_cause(self):
        # The review of the fix round, 1: the step's request is going out in these seconds (about 1, 20 at most).
        def job(conclusion, *steps, name="02-vhl1ha/python-test"):
            return {"name": name, "conclusion": conclusion, "status": "completed" if conclusion else "in_progress",
                    "steps": [{"name": n, "conclusion": c, "status": s} for n, c, s in steps]}
        work, stop = "[07] gate python-test", " [20]  fail fast: stop the run "
        failed, done = (work, "failure", "completed"), (work, "success", "completed")
        asking = job("", failed, (stop, "", "in_progress"))
        self.assertTrue(mtm_ci.ending([asking]))
        self.assertFalse(mtm_ci.cause(asking))  # not yet: it is one once its stop step ended
        rows = mtm_ci.summary([run(1, "land/01", status="in_progress", conclusion="")], lambda rid: [asking], 0)
        self.assertEqual([(r["outcome"], r["task"]) for r in rows], [("running", "")])
        # Ending as mtm-fastlane's GITHUB_ENDING tells it: the stop step ended `success`, a gate job was cancelled.
        self.assertTrue(mtm_ci.ending([job("", failed, (stop, "success", "completed"))]))
        cut, skipped = (work, "cancelled", "completed"), (stop, "skipped", "completed")
        self.assertTrue(mtm_ci.ending([job("success", done, skipped), job("cancelled", cut, skipped)]))
        # Not ending: the stop step still to come or refused, a cancelled job without it, another step in progress.
        self.assertFalse(mtm_ci.ending([job("", failed, ("[19] fail fast: why this job ended", "", "in_progress"),
                                            (stop, "", "pending"))]))
        self.assertFalse(mtm_ci.ending([job("", failed, (stop, "failure", "completed"))]))
        self.assertFalse(mtm_ci.ending([job("cancelled", cut, name="02-vzw1ha/rust-test-windows"),
                                        job("", (work, "", "in_progress"), (stop, "", "pending"))]))
        self.assertFalse(mtm_ci.ending([job("", failed, ("[20] fail fast: stop the run later", "", "in_progress"))]))
        self.assertFalse(mtm_ci.ending([]))

    def test_a_failed_job_hands_off_and_its_stop_job_cancels_the_run(self):
        # Plan 0319: the run of the proof (`bash-lint` failure, its hand-off `success`, `fail-fast-a` cancel step
        # `success` and the job itself `cancelled`, the others `cancelled`), shaped after `gh run view --json jobs`.
        def job(name, conclusion, *steps):
            return {"name": name, "conclusion": conclusion, "status": "completed" if conclusion else "in_progress",
                    "steps": [{"name": n, "conclusion": c, "status": "in_progress" if c == "" else "completed"}
                              for n, c in steps]}
        why, hand = "[20] fail fast: why this job ended", "[21] fail fast: stop the run"
        lint = job("03-x-host-x/bash-lint", "failure", ("[07] gate bash-lint", "failure"), (why, "success"),
                   (hand, "success"))
        cut = job("03-x-host-x/bash-test", "cancelled", ("[07] gate bash-test", "cancelled"), (why, "skipped"),
                  (hand, "skipped"))
        gate = {"name": "05-x-host-x/gate", "conclusion": "cancelled", "steps": []}
        cancel = lambda conclusion, name="03-x-host-x/fail-fast-a", status=None: job(
            name, "cancelled" if conclusion == "success" else "", ("[01] checkout", "success"),
            ("[02] fail fast: cancel the run", conclusion))
        # The window after the hand-off, the stop job not started: ending, red at once, only the failed job named.
        window = [lint, cut]
        self.assertTrue(mtm_ci.ending(window))
        self.assertEqual(mtm_ci.stopped_by(window), ["03-x-host-x/bash-lint"])
        rows = mtm_ci.summary([run(1, "land/22", status="in_progress", conclusion="")], lambda rid: window, 0)
        self.assertEqual([(r["outcome"], r["task"]) for r in rows], [("failed", "03-x-host-x/bash-lint")])
        # The cancel step runs, then ended `success`: ending; the run ends cancelled.
        self.assertTrue(mtm_ci.ending([lint, cut, cancel("")]))
        done = [lint, cut, cancel("success"), gate]
        self.assertTrue(mtm_ci.ending(done))
        rows = mtm_ci.summary([run(1, "land/22", conclusion="cancelled")], lambda rid: done, 0)
        self.assertEqual([(r["outcome"], r["task"]) for r in rows],
                         [("failed", "03-x-host-x/bash-lint, 05-x-host-x/gate")])  # never fail-fast-a, nor a cut job
        # The stop job is no job of the gate: not needed, no cause, not red even when it ended `failure`.
        stopper = cancel("failure", status="completed")
        stopper["conclusion"] = "failure"
        self.assertFalse(mtm_ci.needed(stopper))
        self.assertFalse(mtm_ci.cause(stopper))
        self.assertTrue(mtm_ci.stop_job(stopper))
        self.assertFalse(mtm_ci.stop_job(lint))
        self.assertEqual(mtm_ci.red_jobs([lint, cut, stopper, gate]), ["03-x-host-x/bash-lint", "05-x-host-x/gate"])
        # The request was refused (`failure`) and none is out: the hand-off is no ending, a reader may cancel; the
        # failed job stays a cause. Another stop job's request out makes it ending again.
        refused = [lint, stopper]
        self.assertFalse(mtm_ci.ending(refused))
        self.assertTrue(mtm_ci.ending(refused + [cut]))  # a job cut (matrix fail-fast) concluded `cancelled`: as ever
        self.assertEqual(mtm_ci.stopped_by(refused), ["03-x-host-x/bash-lint"])
        self.assertTrue(mtm_ci.ending(refused + [cancel("success", "04-x-host-x/fail-fast-d")]))
        # A job at its limit asked from inside (stop step `success`, a step `cancelled`): out, so ending whatever a
        # stop job's refusal says.
        limit = job("03-x-host-x/bash-test", "cancelled", ("[07] gate bash-test", "cancelled"), (why, "success"),
                    (hand, "success"))
        self.assertTrue(mtm_ci.ending([limit, stopper]))
        self.assertTrue(mtm_ci.ending([job("03-x-host-x/bash-test", "", ("[07] gate bash-test", "cancelled"),
                                           (hand, "success")), stopper]))
        # A stop job whose cancel step was skipped and a failed job that has not handed off yet: not ending.
        waiting = job("03-x-host-x/bash-lint", "", ("[07] gate", "failure"), (hand, ""))
        waiting["steps"][1]["status"] = "pending"
        self.assertFalse(mtm_ci.ending([cancel("skipped"), waiting]))

    def test_old_runs_are_left_out(self):
        since = dt.datetime(2026, 10, 5, 7, tzinfo=dt.timezone.utc).timestamp()
        self.assertEqual(mtm_ci.summary([run(1, "land/07")], lambda rid: [], since), [])

    def test_ci_mode_asks_for_every_workflow_file_on_the_default_branch(self):
        seen = []
        self.assertFalse(mtm_ci.ci_mode(lambda argv, cwd: seen.append(argv) or "", "/m", "main"))  # none
        self.assertEqual([argv[-1] for argv in seen], ["origin/main:.github/workflows/dev-merge-to-main.yml",
                                                       "origin/main:.github/workflows/merge-to-main.yml"])
        self.assertEqual(seen[0][:3], ["git", "cat-file", "-t"])
        self.assertTrue(mtm_ci.ci_mode(lambda argv, cwd: "blob\n", "/m", "main"))  # both

    def test_ci_mode_accepts_either_workflow_file(self):
        only_new = lambda argv, cwd: "blob\n" if argv[-1].endswith("/merge-to-main.yml") else ""
        only_dev = lambda argv, cwd: "blob\n" if argv[-1].endswith("/dev-merge-to-main.yml") else ""
        other = lambda argv, cwd: "blob\n" if argv[-1].endswith("/ci.yml") else ""
        self.assertTrue(mtm_ci.ci_mode(only_new, "/m", "main"))
        self.assertTrue(mtm_ci.ci_mode(only_dev, "/m", "main"))
        self.assertFalse(mtm_ci.ci_mode(other, "/m", "main"))

    def test_runs_of_every_workflow_file_are_joined_newest_first(self):
        answers = {"dev-merge-to-main.yml": [run(5, "land/09", status="queued", conclusion="", at="2026-10-12T08:00:00Z")],
                   "merge-to-main.yml": [run(4, "land/08", status="queued", conclusion="", at="2026-10-12T07:00:00Z"),
                                         run(3, "land/05", at="2026-10-12T06:30:00Z"),
                                         run(2, "land/07", at="2026-10-12T06:00:00Z"),
                                         run(1, "land/03", status="in_progress", conclusion="",
                                             at="2026-10-11T06:00:00Z")]}
        asked = []
        both = lambda args, cwd: asked.append(args) or answers[args[args.index("--workflow") + 1]]
        self.assertEqual([r["databaseId"] for r in mtm_ci.runs_of(both, "/m")], [5, 4, 3, 2, 1])
        self.assertEqual([a[a.index("--workflow") + 1] for a in asked],
                         ["dev-merge-to-main.yml", "merge-to-main.yml"])
        self.assertEqual(asked[0][:3] + asked[0][5:7], ["gh", "run", "list", "--limit", "100"])
        self.assertEqual(mtm_ci.unfinished(both, "/m"), 3)  # the unfinished runs of both files
        rows = mtm_ci.landings(lambda args, cwd: answers[args[args.index("--workflow") + 1]]
                               if args[:3] == ["gh", "run", "list"] else {"jobs": []}, "/m", 0)
        self.assertEqual([(r["slot"], r["outcome"]) for r in rows],
                         [("09", "running"), ("08", "running"), ("05", "landed"), ("07", "landed"), ("03", "running")])

    def test_a_workflow_file_github_does_not_know_has_no_runs(self):
        old = [run(1, "land/03", status="in_progress", conclusion="", at="2026-10-11T06:00:00Z")]
        new = [run(2, "land/07", status="queued", conclusion="", at="2026-10-12T06:00:00Z"), run(3, "land/05")]
        before = lambda args, cwd: old if "merge-to-main.yml" in args and "dev-merge-to-main.yml" not in args else None
        renamed = lambda args, cwd: new if "dev-merge-to-main.yml" in args else None  # plan 0349 D52's name alone
        self.assertEqual((mtm_ci.unfinished(before, "/m"), [r["databaseId"] for r in mtm_ci.runs_of(before, "/m")]),
                         (1, [1]))
        self.assertEqual((mtm_ci.unfinished(renamed, "/m"), [r["databaseId"] for r in mtm_ci.runs_of(renamed, "/m")]),
                         (1, [2, 3]))
        self.assertEqual((mtm_ci.unfinished(lambda args, cwd: None, "/m"), mtm_ci.runs_of(lambda args, cwd: None, "/m")),
                         (0, []))

    def test_a_run_listed_under_both_names_counts_once(self):
        same = [run(1, "land/03", status="in_progress", conclusion="")]
        self.assertEqual(mtm_ci.unfinished(lambda args, cwd: same, "/m"), 1)
        self.assertEqual(len(mtm_ci.landings(lambda args, cwd: same if args[2] == "list" else {"jobs": []}, "/m", 0)), 1)


if __name__ == "__main__":
    unittest.main()
