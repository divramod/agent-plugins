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
"""

import datetime as dt
import re

import gh_runs

# The landing workflow's file, the name to prefer first: the one place that names both.
LAND_NAMES = ["merge-to-main.yml", "land.yml"]
LAND_FILES = [f".github/workflows/{name}" for name in LAND_NAMES]
RED = {"failure", "timed_out", "startup_failure", "cancelled"}
NOT_COUNTED = {"park", "merge"}  # park's state is no verdict; a red merge is "main moved"
# The workflow's ship jobs run after merge: a delivery never reddens or delays a landing. A fixed set of job parts since
# plan 0260 (a job's name is `<NN>-<code>/<job>`, before it `<lane> / <job>`, older `ship / <job>`).
SHIP_JOBS = {"deliver", "rust-publish-apps-all", "ts-publish-desktop-all", "linux-host-ship-start",
             "publish-claude-plugins", "docker-publish-github-runner-image"}
SHIP_LANES = ("ship", "mac-host-ship", "linux-light-ship")
NAME = re.compile(r"^(?:\d\d-[a-z0-9]{6}/|(?P<lane>\S+) / )?(?P<job>.+)$")
FIELDS = "databaseId,headBranch,headSha,status,conclusion,createdAt,url"


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


def red_jobs(jobs: list[dict]) -> list[str]:
    return [j["name"] for j in jobs if j.get("conclusion") in RED and job_part(j.get("name", "")) not in NOT_COUNTED
            and not is_ship(j.get("name", ""))]


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
    """The slot's candidate under test, newest first."""
    return next((l for l in recent if l["slot"] == slot and l["outcome"] == "running"), None)
