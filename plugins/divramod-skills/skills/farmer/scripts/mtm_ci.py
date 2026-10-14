"""Landings through GitHub Actions (hal2 plan 0131), for mtm_scan.py.

A repository whose default branch has `.github/workflows/merge-to-main.yml` (or
`land.yml`, its name before plan 0263) lands through CI: each landing is a run
of that workflow on `land/<slot>`, green ones
fast-forward the default branch, red ones keep the merge queue held for their
worktree until its fix lands. Runs are read under both names: one started
before the rename finishes under the old one, and the candidate that renames
the file already runs under the new one.
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
"""

import datetime as dt
import re

import gh_runs

# The landing workflow's file, the name to prefer first: the one place that names both.
LAND_NAMES = ["merge-to-main.yml", "land.yml"]
LAND_FILES = [f".github/workflows/{name}" for name in LAND_NAMES]
RED = {"failure", "timed_out", "startup_failure", "cancelled"}
GREEN = {"success", "skipped", "neutral"}
NOT_COUNTED = {"park", "merge"}  # park's state is no verdict; a red merge is "main moved"
# The workflow's ship jobs run after merge: a delivery never reddens or delays a landing. A fixed set of job parts since
# plan 0260 (a job's name is `<NN>-<code>/<job>`, before it `<lane> / <job>`, older `ship / <job>`).
SHIP_JOBS = {"deliver", "rust-publish-apps-all", "ts-publish-desktop-all", "linux-host-ship-start",
             "laptops-start", "publish-claude-plugins", "tmux-publish-hal9k",
             "docker-publish-github-runner-image"}
SHIP_LANES = ("ship", "mac-host-ship", "linux-light-ship")
# The macOS build jobs (the workflow's `mac-vm-build`, plan 0263 D64) build beside the checks what the delivery installs,
# and `mac-vm-build-plan` names them on the Mac host before (D128): `gate` needs none of them, so a red one is no red of
# a candidate (hal2-git's ci/job_name.rs BUILD_JOBS).
BUILD_JOBS = {"rust-bundle-apps-macos", "ts-bundle-desktop-macos", "mac-vm-build-plan"}
BUILD_NAME = re.compile(r"^\d\d-(?:[a-z0-9]{6}|[a-z0-9]+-[a-z]+-[a-z0-9])/(?P<job>.+)$")  # today's names only: no older run had these jobs
NAME = re.compile(r"^(?:\d\d-(?:[a-z0-9]{6}|[a-z0-9]+-[a-z]+-[a-z0-9])/|(?P<lane>\S+) / )?(?P<job>.+)$")
FIELDS = "databaseId,headBranch,headSha,status,conclusion,createdAt,url"
STOP_STEP = "fail fast: stop the run"  # the contract with the workflow, hal2-git's ci/fail_fast.rs STOP_STEP
STEP = re.compile(r"^\s*(?:\[\d+\]\s*)?(?P<task>.*?)\s*$")  # a step's task, without its `[NN] ` number


def ci_mode(run, main: str, default: str) -> bool:
    """`merge-to-main.yml` or `land.yml` is on origin's default branch."""
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
    """The job of a display name: `05-xxx1hx/merge` and `linux / merge` -> `merge`, `merge` -> `merge`."""
    return NAME.match(name or "")["job"]


def is_ship(name: str) -> bool:
    """A ship job: its job part in the fixed set (the new names), or an old lane `ship / `, `mac-host-ship / `."""
    m = NAME.match(name or "")
    return m["job"] in SHIP_JOBS or m["lane"] in SHIP_LANES


def is_build(name: str) -> bool:
    """A macOS build job, `04-mac-vm-x/rust-bundle-apps-macos`, or the build's plan: red or not, it fails no candidate."""
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


def ending(jobs: list[dict]) -> bool:
    """A run its own fail-fast is ending, which nobody asks to cancel (a second request seems to end the run's last
    jobs, the parks, unrun): the stop step of one of its jobs ended `success` or still runs (`in_progress`: it runs
    only in a job that failed or hit its time limit, its request is going out), or a job that carries the stop step
    concluded `cancelled`. Such a run can no longer merge. A stop step still to come, one that ended `failure` (no
    request arrived) and a cancelled job without the step are none: mtm-fastlane's GITHUB_ENDING, hal2-git's
    `Needs::ending`, the workflow's own look (gate/lib/stop-run.sh)."""
    def stops(job: dict) -> list[dict]:
        return [s for s in job.get("steps") or [] if STEP.match(s.get("name") or "")["task"] == STOP_STEP]
    return any(job.get("conclusion") == "cancelled" or s.get("status") == "in_progress"
               or s.get("conclusion") == "success" for job in jobs or [] for s in stops(job))


def stopped_by(jobs: list[dict]) -> list[str]:
    """The causes of a run its own job stopped (fail-fast)."""
    return [j["name"] for j in jobs if cause(j)]


def red_jobs(jobs: list[dict]) -> list[str]:
    """The red jobs that count. In a run with a cause: the causes and a `gate` that is not green; every other
    cancelled job only stopped and is left out. Never a ship job or a macOS build job: `gate` needs neither."""
    causes = stopped_by(jobs)

    def red(job: dict) -> bool:
        name, conclusion = job.get("name", ""), job.get("conclusion")
        if name in causes:
            return True
        if causes and conclusion == "cancelled" and job_part(name) != "gate":
            return False
        return conclusion in RED

    return [j["name"] for j in jobs if red(j) and job_part(j.get("name", "")) not in NOT_COUNTED
            and not is_ship(j.get("name", "")) and not is_build(j.get("name", ""))]


def merged(jobs: list[dict]) -> bool:
    """`merge` succeeded: the landing is decided whatever its ship jobs still do."""
    return any(job_part(j.get("name", "")) == "merge" and j.get("conclusion") == "success" for j in jobs)


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
    """The runs of both landing workflow files, newest first, each list read once per round (gh_runs). A file
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
