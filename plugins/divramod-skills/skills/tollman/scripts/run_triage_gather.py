"""The reading of a finished land run for its triage (hal2 plan 0490 step 1, D3): gh through the farmer's readers
(the round's shared run list and jobs, gh_runs: a completed run's jobs come from the cache), the run's one
`--log-failed` and, only when a red unit may repeat, the failed log of each previous land run that was red (at most
PREVIOUS; the wiring hands in the signatures it kept, `kept`, so a run it triaged is not read again); git in the main
checkout for the workflow's `needs` at the run's commit, the content (tree) of the other runs, the failing specs'
newest commits, the cars' files (triage.car_files) and, when a car changed a workflow, the cars that moved a job's
lane (proof_lanes.moved_by, L83, L87). The runs are the landing workflow's first (watch.of_setting), never a
`skipped` one (L134). `of` gathers and triages. No gate job runs here, ever (D12)."""

from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import gh_runs
import mtm_ci
import mtm_scan
import proof_lanes
import run_triage
import run_triage_read as read
import stack_red
import triage

PREVIOUS = 2  # earlier finished land runs compared for a repeat (L131)
OTHERS = 10  # newest finished runs whose content is compared for a flake
LOG = ["--format=%H%x1f%(trailers:key=Worktree,valueonly,separator=%x2C)%x1f"
       "%(trailers:key=Plan,valueonly,separator=%x2C)%x1f%s"]


def workflow_graph(main: str, sha: str, names: list[str]) -> dict:
    """The `needs` graph of the landing workflow at `sha` whose jobs cover the run's job names."""
    wanted = {read.prefix(n) for n in names} - {""}
    for path in mtm_ci.LAND_FILES:
        code, text = triage.git(main, "show", f"{sha}:{path}")
        graph = read.needs_graph(text) if code == 0 else {}
        if graph and wanted <= set(graph):
            return graph
    return {}


def tree(main: str, sha: str | None) -> str:
    code, out = triage.git(main, "rev-parse", "--verify", "-q", f"{sha}^{{tree}}") if sha else (1, "")
    return out if code == 0 else ""


def finished(runs: list[dict], me: dict) -> list[dict]:
    """The other finished (not cancelled) land runs, newest first."""
    return [r for r in runs if str(r.get("databaseId")) != str(me.get("databaseId")) and r.get("status") == "completed"
            and r.get("conclusion") in ("success", "failure")]


def previous(main: str, runs: list[dict], me: dict, fetch, kept: dict | None = None) -> list[dict]:
    """[{id, units}] of the PREVIOUS finished land runs before `me` (their red units' signatures); `kept`: {run id:
    units} the caller recorded, read from there instead of gh."""
    since = mtm_ci.started(me)
    earlier = [r for r in finished(runs, me) if mtm_ci.started(r) < since][:PREVIOUS]
    out = []
    for r in earlier:
        rid = str(r["databaseId"])
        if rid in (kept or {}):
            out.append({"id": rid, "units": kept[rid]})
            continue
        jobs = gh_runs.jobs([rid], {rid}, fetch).get(rid) or []
        log = mtm_scan.run(["gh", "run", "view", rid, "--log-failed"], main) if read.counted(jobs) else ""
        out.append({"id": rid, "units": read.signatures(jobs, log or "")})
    return out


def others(main: str, runs: list[dict], me: dict, fetch) -> list[dict]:
    """[{id, green}] of the newest finished runs on the same content (tree) as `me`: a flake's proof."""
    mine = tree(main, me.get("headSha"))
    same = [r for r in finished(runs, me)[:OTHERS] if mine and tree(main, r.get("headSha")) == mine]
    ids = [str(r["databaseId"]) for r in same]
    got = gh_runs.jobs(ids, set(ids), fetch) if ids else {}
    return [{"id": rid, "green": sorted(read.green_units(got.get(rid) or []))} for rid in ids]


def owners(main: str, sha: str, units: list[dict]) -> tuple[list[str], dict]:
    """(the repository paths of the failing specs, {path: the newest commit touching it at `sha`})."""
    names = [s for u in units for s in read.facts(u["lines"])["specs"]]
    if not names:
        return [], {}
    code, listed = triage.git(main, "ls-files")
    paths = sorted({p for s in names if (p := run_triage.resolve(s, listed.splitlines() if code == 0 else []))})
    out = {}
    for p in paths:
        code, line = triage.git(main, "log", "-1", *LOG, sha or "HEAD", "--", p)
        if code == 0 and line:
            h, w, plan, subject = (line.split("\x1f") + ["", "", ""])[:4]
            out[p] = {"sha": h, "worktree": w.strip(), "plan": plan.strip(), "subject": subject}
    return paths, out


def plans(main: str) -> dict:
    """{field: its current plan} of the repository's fields (worktrees `00`-`99`, plans/CURRENT_PLAN)."""
    out = {}
    for w in mtm_scan.worktrees(main):
        if not Path(w["path"]).name.isdigit():
            continue
        f = Path(w["path"]) / "plans" / "CURRENT_PLAN"
        text = f.read_text().strip() if f.is_file() else ""
        if text:
            out[Path(w["path"]).name] = text.splitlines()[0].strip()
    return out


def land_runs(main: str) -> list[dict]:
    """The landing workflows' runs, newest first, the workflow `.hal/landing.toml` names first, never `skipped`
    (watch.of_setting, L134: a skipped companion run is no land run)."""
    import watch  # its import reaches post_merge and triage: loaded only by a triage
    runs = [r for r in mtm_ci.runs_of(mtm_scan.run_json, main) if r.get("conclusion") != "skipped"]
    return watch.of_setting(main, runs)


def git_run(argv: list[str], cwd: str) -> tuple[int, str]:
    """proof_lanes' `run(argv, cwd)` for its git reads."""
    return triage.git(cwd, *argv[1:])


def moved(main: str, train: dict, cars: list[dict]) -> dict:
    """{car: its lane moves} when a car changed a workflow file, else {} (no git read)."""
    if not any(proof_lanes.WORKFLOW.match(f) for c in cars for f in c.get("files") or []):
        return {}
    return proof_lanes.moved_by(main, train.get("base"), [c for c in train.get("cars", []) if c.get("head")], git_run)


def gather(main: str, train: dict, url: str, panes: dict | None = None, pipeline_field: str | None = None,
           dedup: dict | None = None, earlier: list[dict] | None = None, kept: dict | None = None) -> tuple | None:
    """run_triage.triage's arguments for the finished run at `url`, or None without a run. `panes`: the round's
    {field: pane} (the live fields); `dedup`: open orders, hitched wagons (carried); `earlier`: the previous runs'
    signatures when the caller has them all (else read here, `kept` first)."""
    rid = stack_red.run_id(url)
    if not rid:
        return None
    fetch = gh_runs.view_jobs(mtm_scan.run_json, main)
    jobs = gh_runs.jobs([rid], {rid}, fetch).get(rid) or []
    runs = land_runs(main)
    me = next((r for r in runs if str(r.get("databaseId")) == rid), {"databaseId": rid})
    units = read.units(jobs, "")  # the units without lines: a repeat or a spec is possible only with a red unit
    log = mtm_scan.run(["gh", "run", "view", rid, "--log-failed"], main) if units else ""
    units, sha = read.units(jobs, log or ""), me.get("headSha")
    paths, commits = owners(main, sha, units)
    running = plans(main)
    cars = triage.car_files(main, train)
    ctx = {"graph": workflow_graph(main, sha, [j.get("name", "") for j in jobs]), "paths": paths, "owners": commits,
           "cars": cars, "moved": moved(main, train, cars), "yard": train.get("yard") or [], "live": set(panes or {}),
           "plans": running, "pipeline_field": pipeline_field, "gate_jobs": gate_jobs(main),
           "previous": earlier if earlier is not None else (previous(main, runs, me, fetch, kept) if units else []),
           "others": others(main, runs, me, fetch) if units else [],
           "dedup": {**(dedup or {}), "plans": running}}
    run = {"id": rid, "url": url, "sha": sha, "branch": me.get("headBranch"), "base": train.get("base"),
           "at": me.get("createdAt")}
    return run, jobs, log or "", ctx


def gate_jobs(main: str) -> set[str]:
    """The gate's jobs (`code/bash/scripts/gate/jobs/<job>.sh`) and its stack-test."""
    return {p.stem for p in (Path(main) / "code/bash/scripts/gate/jobs").glob("*.sh")} | {"stack-test"}


def of(top: str, train: dict, url: str, panes: dict | None = None, **kw) -> dict | None:
    """The triage of the finished run at `url` from the tollman's field `top`, or None without a run."""
    data = gather(mtm_scan.main_checkout(top), train, url, panes, **kw)
    return run_triage.triage(*data) if data else None
