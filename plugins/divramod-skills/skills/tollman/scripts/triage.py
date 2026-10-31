#!/usr/bin/env python3
"""Triage of a train's red land run, as code first (hal2 plan 0360 step 5, D5, D31): which kind of red it is, and the
evidence the session judges with. `classify` is the rule over data, `gather` reads the data (gh through the farmer's
readers, shared per round: gh_runs; git in the main checkout), `of` does both for a run's address.

- `runner`: the run's failed log (`gh run view <id> --log-failed`, its last LOG chars) matches the TRANSIENT
  patterns (transient.py, the farmer's until step 8): a network, registry or runner fault. Nobody is woken; when the
  landing has ended, trains.settle lands the same cars again on a fresh run (train_red.py)
  Also a red job no runner served (gh gives it no step: L64) and a red only of a latency budget or a test's time
  limit (run_triage_read.budget_only, L13: load on the shared host): one fresh run, a repeat counts as runner retries
- `main`: the barn is red, not a car: the same job (stack_red.bare: the job without its matrix alias and position)
  is red in the newest completed land run of another worktree that started before the train was formed (the landing
  workflow's first, a `skipped` run never: watch.of_setting, L134), and that run's
  candidate held the barn's head: one of its commit's parents (`gh api repos/{owner}/{repo}/commits/<sha>`) is
  the barn's head now. The toll gate keeps the barn still while the train lands, so the barn's head now is the one
  the train's candidate held (simpler than reading the run title's base, which names no commit)
- `car`: else. The evidence per car: its files against the train's base (`git diff --name-only <base>...<head>`),
  the red jobs with their first failed step (ci_scan.failed_jobs), the failing tests (mtm_scan.failing_tests) and
  the log's last TAIL chars
- `smuggled`: before `main` and `car` (D61): the candidate covers smuggled ranges (the carrier ticket's `covers`) and
  the red names a covered smuggle's files (smuggled.touched): train_red orders that smuggle's field, no wake
- `none`: a run a pause cancelled is no red (D59): cancelled (every counted red job `cancelled`) and named by a
  `pause` line of the train state (pause.py: the run watched when the pause came)
"""

import subprocess
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import ci_scan
import gh_runs
import job_error
import mtm_ci
import mtm_scan
import run_triage_read
import smuggled
import stack_red
import transient
import trial as trial_merge
from tick import default_ref

LOG = 20000  # the failed log's chars read, as the farmer's duty `ci` does
TAIL = 4000  # the log's chars shown
FILES = 20  # a car's files shown
QUEUE = ["hal2-cli-git", "worktree", "queue", "--json"]


def paused_by(run: dict, pauses=()) -> str | None:
    """The smuggle whose pause cancelled the run (D59): such a run is no red. `pauses`: the train's pause lines."""
    rid = str(run.get("id") or stack_red.run_id(run.get("url")) or "")
    if not run.get("cancelled") or not rid:
        return None
    return next((p.get("field") for p in pauses if stack_red.run_id(p.get("run")) == rid), None)


def classify(run: dict, red: list[dict], logs: str, history: dict) -> dict:
    """{kind: runner | main | car | none, evidence}: `run` {id, url}, `red` its red jobs (gh's job objects, or
    {name} only), `logs` its failed log, `history` {main: the barn's head, other: {slot, url, red: [names],
    parents: [shas]} of the other slot's run or None, cars: [{field, files}]}."""
    if who := paused_by(run, history.get("pauses") or ()):
        return {"kind": "none", "evidence": {"run": run.get("url"), "id": run.get("id"), "paused_by": who}}
    tail, names = (logs or "")[-LOG:], [j.get("name", "") for j in red]
    base = {"run": run.get("url") or run.get("id"), "id": run.get("id"), "red": names}
    if match := transient.TRANSIENT.search(tail):
        return {"kind": "runner", "evidence": {**base, "match": match.group(0)}}
    if red and all(run_triage_read.unserved(j) for j in red):  # L64: no runner ever took them
        return {"kind": "runner", "evidence": {**base, "match": "no runner served " + ", ".join(names)}}
    lines = [job_error.clean(t) for t in tail.splitlines()]  # without the log's job, step and time columns
    if not run_triage_read.TIMEOUT.search(tail) and run_triage_read.budget_only(lines):  # L13: a load flake
        hit = next(t for t in lines if run_triage_read.BUDGET.search(t))
        return {"kind": "runner", "evidence": {**base, "match": "budget: " + hit.strip()[:200], "budget": True}}
    tests = mtm_scan.failing_tests(tail)
    if hit := smuggled.touched(history.get("smuggles"), tail, tests):
        return {"kind": "smuggled", "evidence": {**base, "slot": hit["slot"], "files": hit["hits"], "tests": tests,
                                                 "jobs": ci_scan.failed_jobs(red) or names, "tail": tail[-TAIL:]}}
    other, head = history.get("other") or {}, history.get("main") or ""
    same = sorted({stack_red.bare(n) for n in names} & {stack_red.bare(n) for n in other.get("red", [])})
    if same and head and head in other.get("parents", []):
        return {"kind": "main", "evidence": {**base, "jobs": same, "slot": other.get("slot"), "other": other.get("url"),
                                             "main": head}}
    return {"kind": "car", "evidence": {**base, "jobs": ci_scan.failed_jobs(red) or names,
                                        "tests": tests, "cars": history.get("cars", []),
                                        "tail": tail[-TAIL:]}}


def git(main: str, *args: str) -> tuple[int, str]:
    if not Path(main).is_dir():
        return 1, ""
    try:
        return trial_merge.git(main, *args)
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def main_head(main: str) -> str:
    """The barn's head as the main checkout knows it (`origin/<default>`), or ''."""
    code, out = git(main, "rev-parse", default_ref(main))
    return out if code == 0 else ""


def car_files(main: str, train: dict) -> list[dict]:
    """[{field, files}]: each car's files against the train's base."""
    out = []
    for c in train.get("cars", []):
        code, text = git(main, "diff", "--name-only", f"{train.get('base')}...{c.get('head')}")
        out.append({"field": c.get("field"), "files": text.splitlines() if code == 0 and text else []})
    return out


def other_run(main: str, train: dict, fetch) -> dict | None:
    """The newest completed land run of another worktree that started before the train was formed, with its red jobs
    (a train's own branch `land/train-...` names no worktree: mtm_ci leaves it out, as the carrier's was)."""
    since, carrier = mtm_ci.started({"createdAt": train.get("at")}), train.get("carrier")
    import watch  # its import reaches post_merge, which imports this module
    runs = watch.of_setting(main, [r for r in mtm_ci.runs_of(mtm_scan.run_json, main)  # the landing workflow's first
                                   if mtm_ci.slot_of(r.get("headBranch") or "") not in ("", carrier)
                                   and r.get("status") == "completed" and r.get("conclusion") != "skipped"  # L134
                                   and mtm_ci.started(r) < since])
    if not runs:
        return None
    r, rid = runs[0], str(runs[0].get("databaseId"))
    jobs = gh_runs.jobs([rid], {rid}, fetch).get(rid) or []
    return {"slot": mtm_ci.slot_of(r["headBranch"]), "url": r.get("url"), "sha": r.get("headSha"),
            "red": mtm_ci.red_jobs(jobs)}


def parents(main: str, sha: str | None) -> list[str]:
    data = mtm_scan.run_json(["gh", "api", f"repos/{{owner}}/{{repo}}/commits/{sha}"], main) if sha else None
    return [p.get("sha") for p in (data or {}).get("parents") or []]


def gather(main: str, train: dict, url: str | None, names=(), jobs: list[dict] | None = None,
           tickets=None) -> tuple | None:
    """classify's arguments for the run at `url`, or None without a run. `names`: the red jobs the landing named
    (its result), used when gh gives no jobs; `jobs`: the run's jobs read already (watch.py); `tickets`: the queue's
    (read when None), for the smuggles the candidate covers."""
    rid = stack_red.run_id(url)
    if not rid:
        return None
    fetch = gh_runs.view_jobs(mtm_scan.run_json, main)
    jobs = jobs if jobs is not None else gh_runs.jobs([rid], set(), fetch).get(rid) or []
    counted = mtm_ci.red_jobs(jobs)
    red = [j for j in jobs if j.get("name") in counted] or [{"name": n} for n in names]
    logs = (mtm_scan.run(["gh", "run", "view", rid, "--log-failed"], main) or "")[-LOG:] if counted else ""
    other = other_run(main, train, fetch)
    if other and {stack_red.bare(j["name"]) for j in red} & {stack_red.bare(n) for n in other["red"]}:
        other["parents"] = parents(main, other["sha"])
    if tickets is None:
        tickets = (mtm_scan.run_json(QUEUE, main) or {}).get("queue", [])
    cancelled = bool(counted) and all(j.get("conclusion") == "cancelled" for j in red)
    return {"id": rid, "url": url, "cancelled": cancelled}, red, logs, {
        "main": main_head(main), "other": other, "cars": car_files(main, train), "pauses": train.get("pauses") or [],
        "smuggles": smuggled.smuggles(main, tickets, train.get("carrier"))}


def of(top: str, train: dict, url: str | None, names=(), tickets=None) -> dict | None:
    """The verdict on the train's run at `url` from the tollman's field `top`, or None without a run."""
    data = gather(mtm_scan.main_checkout(top), train, url, names, None, tickets)
    return classify(*data) if data else None


def words(verdict: dict) -> dict:
    """The verdict's evidence as the texts' fields (train_red.TEXT)."""
    e = verdict["evidence"]
    files = "\n".join(f"- {c['field']}: " + (", ".join(c["files"][:FILES]) + (" ..." if len(c["files"]) > FILES else "")
                                            if c["files"] else "no file") for c in e.get("cars", []))
    return {"jobs": ", ".join(e.get("jobs") or e.get("red") or []) or "a job", "rid": e.get("id") or "",
            "tests": ", ".join(e.get("tests") or []) or "none named (read the log)", "files": files or "- no car",
            "slot": e.get("slot") or "?", "other": e.get("other") or "?", "main": (e.get("main") or "")[:12],
            "match": e.get("match") or ""}
