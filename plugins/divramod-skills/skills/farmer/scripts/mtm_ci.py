"""Landings through GitHub Actions (hal2 plan 0131), for mtm_scan.py.

A repository whose default branch has `.github/workflows/dev-merge-to-main.yml`
(or `merge-to-main.yml`, its name before plan 0349 D52, or `land.yml`, before
plan 0263) lands through CI: each landing is a run of that workflow on
`land/<slot>`, green ones fast-forward the default branch, red ones keep the
merge queue held for their worktree until its fix lands. Runs are read under
every name: one started before a rename finishes under the old one, and the
candidate that renames the file already runs under the new one.
Here they become the same recent-landings rows the local landings' records
give mtm_scan.py.

Fail-fast (plan 0263 rows 19 and 73, as hal2-git's ci/fail_fast.rs reads it): a job the workflow's `gate` job needs
ends with the step `[NN] fail fast: stop the run`, which runs only in a job that failed or hit its time limit and
cancels the run. A cause is told by a job's steps, never by its conclusion (GitHub concludes the job that stopped its
run `cancelled` like the ones cancelled with it): its stop step ran (it ended `success`, or `failure` when GitHub
refused the request), or it ended not green with a step that failed before a cancel reached the job. A run
with a cause is failed at once, also while its other jobs still end, and its red jobs are the causes and `gate`: a
cancelled job only stopped. A run without the step, or without a cause (a pause's cancel), is read as before.
A stop step still `in_progress` is no cause yet (it has not ended), but its run is `ending` like one whose stop step
ended `success` or one with a job of the gate concluded `cancelled`: nobody asks such a run to cancel (ci_scan.py).

Plan 0319 (hal2-git's ci/fail_fast.rs, the same rule): a job that failed no longer cancels the run from inside (a
cancel that reaches a running job would turn it `cancelled`, grey): its stop step is a hand-off (`success`, no request)
and the lane's stop job (`fail-fast-<lane>`) sends the one request in its step `[NN] fail fast: cancel the run`. That
job is no job of the gate (it holds no stop step): never a `needed` job, never a cause, never a red job of the
candidate. The run is `ending` from the hand-off on and while a cancel step runs or ended `success`; the hand-off
stops counting once a cancel step ended `failure` and no request is out (nobody has asked: a reader may). A job at
its time limit still asks from inside (stop step `success` in a job with a `cancelled` step): that request is out.
"""

import datetime as dt
import re

import gh_runs

# The landing workflow's file, the name to prefer first: the one place that names them all.
LAND_NAMES = ["dev-merge-to-main.yml", "merge-to-main.yml", "land.yml"]
LAND_FILES = [f".github/workflows/{name}" for name in LAND_NAMES]
RED = {"failure", "timed_out", "startup_failure", "cancelled"}
GREEN = {"success", "skipped", "neutral"}
NOT_COUNTED = {"park", "merge", "git-merge"}  # park's state is no verdict; a red merge is "main moved"
MERGE_JOBS = {"merge", "git-merge"}  # the merge job's part: `git-merge` since plan 0349 D101, `merge` before
# The workflow's ship jobs run after merge: a delivery never reddens or delays a landing. A fixed set of job parts since
# plan 0260 (a job's name is `<NN>-<code>/<job>`, before it `<lane> / <job>`, older `ship / <job>`).
SHIP_JOBS = {"deliver", "rust-publish-apps-all", "ts-publish-desktop-all", "linux-host-ship-start",
             "laptops-start", "publish-claude-plugins", "tmux-publish-hal9k",
             "docker-publish-github-runner-image",
             # Plan 0349's jobs after the merge (its graph's column 04).
             "git-pull-main", "rust-install-apps-mac", "ts-install-desktop-mac", "git-deliver-record",
             "agents-publish", "tmux-publish-mac", "tmux-publish-linux", "nvim-publish",
             "ci-cache-clean-mac-host", "ci-cache-clean-mac-vm", "ci-cache-clean-hz-host",
             "hub-deploy"}  # the hub's deploy on mac-host-b (plan 0349 step 35)
SHIP_LANES = ("ship", "mac-host-ship", "linux-light-ship")
# The macOS build jobs (the workflow's `mac-vm-build`, plan 0263 D64) build beside the checks what the delivery installs,
# and `mac-vm-build-plan` names them on the Mac host before (D128): `gate` needs none of them, so a red one is no red of
# a candidate (hal2-git's ci/job_name.rs BUILD_JOBS).
BUILD_JOBS = {"rust-bundle-apps-macos", "ts-bundle-desktop-macos", "mac-vm-build-plan",
              # Plan 0349: the one VM lane's jobs after bash-test (D17-D20).
              "tmux-build-mac", "tmux-test-mac", "rust-build-mac", "ts-bundle-desktop-mac"}
# Since plan 0349 (D40) the job part of the names starts with the job's position in its lane (`02-hz01-host-b/03-rust-lint`):
# the job is the bare one, as in the names without it. Since D101 a name is `<matrix alias>-<NN>-<job>` (`c3-03-rust-lint`:
# the stage's letter, the matrix's place in it, the job's position): the old forms stay for the runs before it.
NEW = r"[a-z][1-9]-\d\d-"
OLD = r"\d\d-(?:[a-z0-9]{6}|[a-z0-9]+-[a-z]+-[a-z0-9])/(?:\d\d-)?"
BUILD_NAME = re.compile(rf"^(?:{NEW}|{OLD})(?P<job>.+)$")  # these names only: no older run had these jobs
NAME = re.compile(rf"^(?:{NEW}|{OLD}|(?P<lane>\S+) / )?(?P<job>.+)$")
FIELDS = "databaseId,headBranch,headSha,status,conclusion,createdAt,url"
STOP_STEP = "fail fast: stop the run"  # the contract with the workflow, hal2-git's ci/fail_fast.rs STOP_STEP
CANCEL_STEP = "fail fast: cancel the run"  # the stop job's step (plan 0319 D9), hal2-git's CANCEL_STEP
STEP = re.compile(r"^\s*(?:\[\d+\]\s*)?(?P<task>.*?)\s*$")  # a step's task, without its `[NN] ` number


def ci_mode(run, main: str, default: str) -> bool:
    """`dev-merge-to-main.yml`, `merge-to-main.yml` or `land.yml` is on origin's default branch."""
    return any(run(["git", "cat-file", "-t", f"origin/{default}:{f}"], main).strip() for f in LAND_FILES)


def slot_of(branch: str) -> str:
    """`land/07` -> `07`; probes (`land/12-probe`) and other branches -> ``."""
    m = re.fullmatch(r"land/([^/]+)", branch or "")
    return m.group(1) if m and "-probe" not in m.group(1) else ""


def started(run: dict) -> float:
    try:
        return dt.datetime.fromisoformat((run.get("createdAt") or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def outcome(run: dict) -> str:
    if run.get("status") != "completed":
        return "running"
    return "landed" if run.get("conclusion") == "success" else "failed"


def job_part(name: str) -> str:
    """The job of a display name: `05-xxx1hx/merge`, `03-hz01-host-b/01-merge` and `linux / merge` -> `merge`, `merge` -> `merge`,
    `d2-01-git-merge` -> `git-merge`."""
    return NAME.match(name or "")["job"]


def is_ship(name: str) -> bool:
    """A ship job: its job part in the fixed set (the new names), or an old lane `ship / `, `mac-host-ship / `."""
    m = NAME.match(name or "")
    return m["job"] in SHIP_JOBS or m["lane"] in SHIP_LANES


def is_build(name: str) -> bool:
    """A macOS build job, `c1-02-rust-build-mac` or `04-mac-vm-x/rust-bundle-apps-macos`, or the build's plan: red or not, it fails no candidate."""
    m = BUILD_NAME.match(name or "")
    return bool(m) and m["job"] in BUILD_JOBS


def needed(job: dict) -> bool:
    """A job the `gate` job needs: one of its steps (`gh run view --json jobs`) is the workflow's stop step."""
    return any(STEP.match(s.get("name") or "")["task"] == STOP_STEP for s in job.get("steps") or [])


def cause(job: dict) -> bool:
    """A job of the gate that makes its candidate red: its stop step ran to its end (`success`, or `failure`: it ran
    and GitHub refused the request; not skipped, not cut short), or it ended not green with a step that ended
    `failure` before any step of it ended `cancelled`: a step that fails after the cut failed because a cancel had
    reached the job. Never told by the job's own conclusion; a green job is none, nor is one the workflow's start
    step stopped (`[01] fail fast` its first failed step, plan 0263 row 3)."""
    steps = [(STEP.match(s.get("name") or "")["task"], s.get("conclusion") or "") for s in job.get("steps") or []]
    stop = next((c for task, c in steps if task == STOP_STEP), None)
    cut = next((at for at, (_, c) in enumerate(steps) if c == "cancelled"), len(steps))
    failed = [task for task, c in steps[:cut] if c == "failure" and task != STOP_STEP]
    if not needed(job) or job.get("conclusion") in GREEN or failed[:1] == ["fail fast"]:
        return False
    return stop in ("success", "failure") or bool(failed and job.get("conclusion"))


def steps_named(job: dict, task: str) -> list[dict]:
    return [s for s in job.get("steps") or [] if STEP.match(s.get("name") or "")["task"] == task]


def stop_job(job: dict) -> bool:
    """A lane's stop job (`fail-fast-a`, plan 0319): it holds the step that sends the cancel, never a job of the gate."""
    return bool(steps_named(job, CANCEL_STEP))


def ending(jobs: list[dict]) -> bool:
    """A run its own fail-fast is ending, which nobody asks to cancel (a second request seems to end the run's last
    jobs, the parks, unrun): a stop job's cancel step runs (`in_progress`: its request is going out) or ended
    `success`; or a job of the gate stopped: its stop step runs, or ended `success` (a failed job's hand-off, the stop
    job's request follows; or a job at its limit's own request), or the job concluded `cancelled`. A hand-off stops
    counting once a cancel step ended `failure` while no request is out (a stop step `success` in a job with no
    `cancelled` step is a hand-off, no request): nobody has cancelled the run, a reader may. Such a run can no longer
    merge. A stop step still to come and a cancelled job without the step are none: mtm-fastlane's GITHUB_ENDING,
    hal2-git's `Needs::ending`, the workflow's own look (gate/lib/stop-run.sh)."""
    cancels = [s for job in jobs or [] for s in steps_named(job, CANCEL_STEP)]
    if any(s.get("status") == "in_progress" or s.get("conclusion") == "success" for s in cancels):
        return True
    refused = any(s.get("conclusion") == "failure" for s in cancels)

    def stopping(job: dict) -> bool:
        stops = steps_named(job, STOP_STEP)
        if stops and job.get("conclusion") == "cancelled":
            return True
        limit = any(s.get("conclusion") == "cancelled" for s in job.get("steps") or [])
        asked = any(s.get("status") == "in_progress" or s.get("conclusion") == "success" for s in stops)
        return asked and (limit or not refused)

    return any(stopping(job) for job in jobs or [])


def stopped_by(jobs: list[dict]) -> list[str]:
    """The causes of a run its own job stopped (fail-fast)."""
    return [j["name"] for j in jobs if cause(j)]


def red_jobs(jobs: list[dict]) -> list[str]:
    """The red jobs that count. In a run with a cause: the causes and a `gate` that is not green; every other
    cancelled job only stopped and is left out. Never a ship job, a macOS build job or a stop job: `gate` needs
    none of them (a stop job that failed to send its request is not the candidate's red)."""
    causes = stopped_by(jobs)

    def red(job: dict) -> bool:
        name, conclusion = job.get("name", ""), job.get("conclusion")
        if name in causes:
            return True
        if causes and conclusion == "cancelled" and job_part(name) != "gate":
            return False
        return conclusion in RED

    return [j["name"] for j in jobs if red(j) and job_part(j.get("name", "")) not in NOT_COUNTED
            and not is_ship(j.get("name", "")) and not is_build(j.get("name", "")) and not stop_job(j)]


def merged(jobs: list[dict]) -> bool:
    """`git-merge` (`merge` before D101) succeeded: the landing is decided whatever its ship jobs still do."""
    return any(job_part(j.get("name", "")) in MERGE_JOBS and j.get("conclusion") == "success" for j in jobs)


def summary(runs: list[dict], jobs_of, since: float) -> list[dict]:
    """Recent landing rows from the landing workflow's runs (`runs_of`, newest first);
    `jobs_of(run id)` gives a failed run's jobs (`gh run view --json jobs`)."""
    out = []
    for r in runs:
        slot = slot_of(r.get("headBranch") or "")
        if not slot or started(r) < since:
            continue
        o = outcome(r)
        jobs = jobs_of(r["databaseId"]) if o != "landed" else []
        if o != "landed" and merged(jobs):
            o = "landed"
        elif o == "running" and stopped_by(jobs):
            o = "failed"  # decided at its first cause, whatever still ends (hal2-git returns then)
        red = red_jobs(jobs) if o == "failed" else []
        out.append({"id": str(r.get("databaseId")), "slot": slot, "outcome": o,
                    "task": ", ".join(red) if o == "failed" else "", "tests": [], "load_hint": False,
                    "url": r.get("url"), "sha": (r.get("headSha") or "")[:8], "started": started(r)})
    return out


def list_args(workflow: str) -> list[str]:
    return ["gh", "run", "list", "--workflow", workflow, "--limit", "100", "--json", FIELDS]


def runs_of(run_json, main: str) -> list[dict]:
    """The runs of every landing workflow file, newest first, each list read once per round (gh_runs). A file
    GitHub does not know (not renamed yet, or renamed away) gives no list: no runs."""
    runs = {}
    for name in LAND_NAMES:
        for r in gh_runs.listed(run_json, list_args(name), main) or []:
            runs.setdefault(r.get("databaseId"), r)
    return sorted(runs.values(), key=lambda r: r.get("createdAt") or "", reverse=True)


def unfinished(run_json, main: str) -> int:
    """How many landing-workflow runs are not completed, on any branch: landings under test or shipping and
    dispatched runs (`gh workflow run <file>`), queued ones included. The same lists as `landings`, once per round."""
    return sum(1 for r in runs_of(run_json, main) if r.get("status") != "completed")


def landings(run_json, main: str, since: float) -> list[dict]:
    """The recent landing rows; the not-landed runs' jobs fetched together, once per round (gh_runs)."""
    runs = runs_of(run_json, main)
    need = [r for r in runs if slot_of(r.get("headBranch") or "") and started(r) >= since and outcome(r) != "landed"]
    jobs = gh_runs.jobs([r["databaseId"] for r in need],
                        {r["databaseId"] for r in need if r.get("status") == "completed"},
                        gh_runs.view_jobs(run_json, main))
    return summary(runs, lambda rid: jobs.get(rid, []), since)


def running_run(recent: list[dict], slot: str) -> dict | None:
    """The worktree's candidate under test, newest first."""
    return next((l for l in recent if l["slot"] == slot and l["outcome"] == "running"), None)
