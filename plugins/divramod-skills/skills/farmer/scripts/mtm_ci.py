"""Landings through GitHub Actions (hal2 plan 0131), for mtm_scan.py.

A repository whose default branch has `.github/workflows/land.yml` lands
through CI: each landing is a `land.yml` run on `land/<slot>`, green ones
fast-forward the default branch, red ones keep the merge queue held for their
worktree until its fix lands.
Here they become the same recent-landings rows the local landings' records
give mtm_scan.py.
"""

import datetime as dt
import re

import gh_runs

LAND_FILE = ".github/workflows/land.yml"
RED = {"failure", "timed_out", "startup_failure", "cancelled"}
NOT_COUNTED = {"park", "merge"}  # park's state is no verdict; a red merge is "main moved"
SHIP = "ship / "  # land.yml's ship jobs run after merge: a delivery never reddens or delays a landing
FIELDS = "databaseId,headBranch,headSha,status,conclusion,createdAt,url"


def ci_mode(run, main: str, default: str) -> bool:
    """`land.yml` is on origin's default branch."""
    return bool(run(["git", "cat-file", "-t", f"origin/{default}:{LAND_FILE}"], main).strip())


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


def red_jobs(jobs: list[dict]) -> list[str]:
    return [j["name"] for j in jobs if j.get("conclusion") in RED and j.get("name") not in NOT_COUNTED
            and not j.get("name", "").startswith(SHIP)]


def merged(jobs: list[dict]) -> bool:
    """`merge` succeeded: the landing is decided whatever its ship jobs still do."""
    return any(j.get("name") == "merge" and j.get("conclusion") == "success" for j in jobs)


def summary(runs: list[dict], jobs_of, since: float) -> list[dict]:
    """Recent landing rows from `gh run list --workflow land.yml` (newest first);
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


LIST = ["gh", "run", "list", "--workflow", "land.yml", "--limit", "100", "--json", FIELDS]


def unfinished(run_json, main: str) -> int:
    """How many land.yml runs are not completed, on any branch: landings under test or shipping and dispatched
    runs (`gh workflow run land.yml`), queued ones included. The same list as `landings`, once per round."""
    return sum(1 for r in gh_runs.listed(run_json, LIST, main) or [] if r.get("status") != "completed")


def landings(run_json, main: str, since: float) -> list[dict]:
    """The recent landing rows; the not-landed runs' jobs fetched together, once per round (gh_runs)."""
    runs = gh_runs.listed(run_json, LIST, main) or []
    need = [r for r in runs if slot_of(r.get("headBranch") or "") and started(r) >= since and outcome(r) != "landed"]
    jobs = gh_runs.jobs([r["databaseId"] for r in need],
                        {r["databaseId"] for r in need if r.get("status") == "completed"},
                        gh_runs.view_jobs(run_json, main))
    return summary(runs, lambda rid: jobs.get(rid, []), since)


def running_run(recent: list[dict], slot: str) -> dict | None:
    """The slot's candidate under test, newest first."""
    return next((l for l in recent if l["slot"] == slot and l["outcome"] == "running"), None)
