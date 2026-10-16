"""Landings first on the runners (hal2 plan 0306, D4, D5): the wagon master's duty `checks`.

While a landing or a train runs or waits, a check run (`ci-check`, a `workflow_dispatch` of merge-to-main.yml titled
`[<slot>] ci-check ...`) is held back: `ci-check` asks `wagon_master.py checks busy` and writes its dispatch into the
store instead (`checks defer`); a check queued just before is cancelled while no job but `route` and `changes` has
started, and deferred again (a check running lane jobs is never cancelled). Once nothing lands, the duty dispatches
the deferral of the slot that waits longest, its newest one (the older ones of the slot are superseded), one at a
time: nothing while a check run it dispatched is unfinished (D4); it tells the session (checks_tell.py).

Bounds: a failed dispatch is tried again after RETRY and given up after TRIES attempts (the session is told to run
ci-check again); a deferral older than STALE is superseded, never dispatched; a `waiting` queue ticket holds the
runners only while younger than WAITING or while its session lives; a `gh run list` that failed reads as busy
("unknown: gh failed") and nothing is dispatched that round.

The store `checks.jsonl` in the wagon master's state folder is an event log (manifest.toml, schemas/checks.schema.json):

  deferred    id, `slot`, pane, title, argv (the whole command, `gh workflow run ...`), cwd; `again`: the run it
              was cancelled from (the duty's re-deferral; its session is told it waits)
  dispatched  id (the deferral's, or a new one for ci-check's own dispatch), `slot`, pane, title, argv, cwd, run,
              url; `by`: `checks` (the duty, its session is told it runs) or `ci-check`
  cancelled   id (the dispatched entry), run
  superseded  id (a deferral of the slot older than the one dispatched, or older than STALE); `by`: the newer
              entry's id or `stale`
  failed      id (the deferral), attempt (1, 2, ...), why, pane: a dispatch that failed; at TRIES it is given up

`plan` writes nothing and calls no gh that changes anything: a cancel or a dispatch is a `run` action calling
`wagon_master.py checks cancel|dispatch` (checks_cli.py), which re-checks, acts and records; the sessions are told
from the store in the next round, every message keyed per entry so nothing is sent twice.
"""

import datetime as dt
import json
import os
import re
import secrets
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import checks_tell
import deliver
import gh_runs
import mtm_ci
import mtm_scan
import train_state
from tick import act

ROLE = "wagon-master"
FILE = "checks.jsonl"
SCHEMA = 1
KINDS = ("deferred", "dispatched", "cancelled", "superseded", "failed")
WORKFLOW = "merge-to-main.yml"
CHECK = re.compile(r"^\[(?P<slot>[^\]]+)\] ci-check\b")
FIELDS = "databaseId,event,status,headBranch,displayTitle,url,createdAt"
FREE_JOBS = ("route", "changes")  # what may have run on a check that is still cancelled (D5)
CLI = Path(__file__).with_name("wagon_master.py")
RETRY = dt.timedelta(minutes=10)  # a failed cancel or dispatch is planned again after this
TRIES = 3  # failed dispatches of one deferral before it is given up
STALE = dt.timedelta(hours=24)  # a deferral older than this is superseded, not dispatched
WAITING = dt.timedelta(hours=2)  # a `waiting` ticket without a live session holds the runners this long
MATCH = dt.timedelta(hours=2)  # a dispatch recorded without its run is matched by title (or counts as running) this long
TELL = checks_tell.TELL
GH_FAILED = "unknown: gh failed"


def utc(now: dt.datetime | None = None) -> str:
    return train_state.utc(now)


def folder(main: str) -> Path:
    return mtm_scan.state_dir(main, ROLE)


def new_id(slot: str, now: dt.datetime | None = None) -> str:
    """`<slot>-<n>` (the event line's envelope): the time in seconds and three random digits."""
    stamp = int((now or dt.datetime.now(dt.timezone.utc)).timestamp())
    return f"{re.sub(r'[^A-Za-z0-9-]', '-', slot or '-')}-{stamp}{secrets.randbelow(1000):03d}"


def append(main: str, kind: str, slot: str, now: dt.datetime | None = None, **keys) -> dict:
    """One line, one write under O_APPEND (sessions defer while the duty records); a key without a value is left out."""
    if kind not in KINDS:
        raise ValueError(f"no checks kind {kind!r}")
    line = {"schema": SCHEMA, "at": utc(now), "kind": kind, "slot": slot or "-",
            **{k: v for k, v in keys.items() if v is not None}}
    fd = os.open(folder(main) / FILE, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps(line) + "\n").encode())
    finally:
        os.close(fd)
    return line


def lines(main: str) -> list[dict]:
    """The store's lines; one that does not parse (a torn last line) is skipped."""
    f, out = folder(main) / FILE, []
    for text in f.read_text().splitlines() if f.exists() else []:
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("kind") in KINDS and row.get("id"):
            out.append(row)
    return out


def at(row: dict) -> dt.datetime:
    return checks_tell.at(row)


def attempts(rows: list[dict], entry_id: str) -> list[dict]:
    """The failed dispatches of a deferral, oldest first."""
    return [r for r in rows if r["kind"] == "failed" and r["id"] == entry_id]


def pending(rows: list[dict]) -> list[dict]:
    """The deferrals not dispatched, superseded or given up (TRIES failures) yet, oldest first."""
    closed = {r["id"] for r in rows if r["kind"] in ("dispatched", "superseded")
              or (r["kind"] == "failed" and (r.get("attempt") or 0) >= TRIES)}
    return [r for r in rows if r["kind"] == "deferred" and r["id"] not in closed]


def stale(entry: dict, now: dt.datetime) -> bool:
    return at(entry) < now.astimezone(dt.timezone.utc) - STALE


def next_dispatch(rows: list[dict], now: dt.datetime) -> dict | None:
    """The slot that waits longest (its oldest pending deferral is the oldest), its newest deferral; a slot whose
    newest deferral failed within RETRY is skipped this round, so it blocks no other slot."""
    waiting, cutoff = pending(rows), now.astimezone(dt.timezone.utc) - RETRY
    for slot in dict.fromkeys(r["slot"] for r in waiting):
        newest = [r for r in waiting if r["slot"] == slot][-1]
        if not any(at(f) > cutoff for f in attempts(rows, newest["id"])):
            return newest
    return None


def supersede_older(main: str, rows: list[dict], slot: str, by: str, now: dt.datetime | None = None) -> list[str]:
    """Supersede the worktree's pending deferrals but `by` (a dispatch was recorded for the worktree); their ids."""
    gone = [e["id"] for e in pending(rows) if e["slot"] == slot and e["id"] != by]
    for entry_id in gone:
        append(main, "superseded", slot, now, id=entry_id, by=by)
    return gone


def recorded(rows: list[dict], run: dict, now: dt.datetime) -> dict | None:
    """The dispatched entry of a check run: by its run id, else by its title (a dispatch recorded without its run
    in the last two hours); None: the run is no dispatch the store can send again."""
    rid, title = run.get("databaseId"), run.get("displayTitle")
    done = [r for r in rows if r["kind"] == "dispatched" and r.get("argv")]
    hit = next((r for r in reversed(done) if r.get("run") == rid), None)
    if hit or not title:
        return hit
    cutoff = now.astimezone(dt.timezone.utc) - MATCH
    return next((r for r in reversed(done) if r.get("run") is None and r.get("title") == title
                 and at(r) >= cutoff), None)


def list_args(limit: int = 50) -> list[str]:
    return ["gh", "run", "list", "--workflow", WORKFLOW, "--limit", str(limit), "--json", FIELDS]


def runs(run_json, main: str) -> list[dict] | None:
    """merge-to-main.yml's runs, newest first, once per round (gh_runs); None: `gh run list` failed."""
    got = gh_runs.listed(run_json, list_args(), main)
    return got if isinstance(got, list) else None


def unfinished_checks(all_runs: list[dict] | None) -> list[dict]:
    return [r for r in all_runs or [] if r.get("event") == "workflow_dispatch" and r.get("status") != "completed"
            and CHECK.match(r.get("displayTitle") or "")]


def lane_started(jobs: list[dict]) -> bool:
    """Has a job but `route` and `changes` taken a runner (in progress or done, not skipped)?"""
    return any(j.get("status") in ("in_progress", "completed") and j.get("conclusion") != "skipped"
               and mtm_ci.job_part(j.get("name") or "") not in FREE_JOBS for j in jobs)


def waits(t: dict, now: dt.datetime | None, sessions: set | None) -> bool:
    """A `waiting` ticket that holds the runners: its session lives, or it is younger than WAITING (or of no
    known age)."""
    if t.get("state") != "waiting":
        return False
    since = (t.get("ready") or {}).get("at") or t.get("enqueued")
    if now is None or not since or t.get("slot") in (sessions or set()):
        return True
    return at({"at": since}) >= now.astimezone(dt.timezone.utc) - WAITING


def busy(tickets: list[dict], train: dict | None, all_runs: list[dict] | None, now: dt.datetime | None = None,
         sessions: set | None = None) -> dict | None:
    """Why the runners are the landings' now ({reason, slot}), or None: an active landing, a hold reserved for a
    landing, a standing train, a land run of a `push` not finished (runs None: gh failed, busy for safety), a
    landing that waits in the queue (`waits`; unless a red landing holds the queue: nothing moves, checks may run)."""
    def of(t: dict, why: str) -> dict:
        return {"reason": why.format(slot=t.get("slot")), "slot": t.get("slot")}

    for t in tickets:
        if t.get("state") == "active":
            return of(t, "the landing of {slot} runs")
    if train and train.get("state") in ("formed", "landing", "retry"):
        return {"reason": f"the train {train.get('train')} stands", "slot": train.get("carrier")}
    for t in tickets:
        if (t.get("hold") or {}).get("reason") == "reserved":
            return of(t, "{slot} holds the merge queue for its landing")
    if all_runs is None:
        return {"reason": GH_FAILED, "slot": ""}
    for r in all_runs:
        branch = r.get("headBranch") or ""
        if r.get("event") == "push" and branch.startswith("land/") and r.get("status") != "completed":
            return {"reason": f"the land run {r.get('databaseId')} on {branch} runs", "slot": branch[len("land/"):]}
    stuck = any(t.get("state") == "held" for t in tickets)
    for t in tickets if not stuck else []:
        if waits(t, now, sessions):
            return of(t, "the landing of {slot} waits in the merge queue")
    return None


def sessions_of(main: str) -> set:
    """The worktrees of this repository with an agent session (hal2-cli-agents list), as tick.context finds them."""
    try:
        data = json.loads(deliver.cli("list", "--json")[1])
    except json.JSONDecodeError:
        data = []
    rows = data.get("list", []) if isinstance(data, dict) else data
    home = Path.home() / ".hal/git/worktree" / Path(main).name
    return {a["slot"] for a in rows if a.get("slot") and a.get("checkout") and Path(a["checkout"]).parent == home}


def state(main: str, run_json, tickets: list[dict] | None = None, sessions: set | None = None,
          now: dt.datetime | None = None) -> dict:
    """What the duty and `checks busy` read: the queue (or the round's), the train state, the runs, the store."""
    if tickets is None:
        tickets = (run_json(["hal2-cli-git", "worktree", "queue", "--json"], main) or {}).get("queue", [])
    all_runs, now = runs(run_json, main), now or dt.datetime.now(dt.timezone.utc)
    train = train_state.standing(train_state.lines(main))
    held = busy(tickets, train, all_runs, now, sessions_of(main) if sessions is None else sessions)
    return {"tickets": tickets, "runs": all_runs, "busy": held, "rows": lines(main)}


def cli(*args: str) -> list[str]:
    return [sys.executable, str(CLI), "checks", *args]


def holds(main: str, s: dict, jobs_of, now: dt.datetime) -> list[dict]:
    """While busy: cancel each queued check that only ran route and changes and that the store can send again;
    tell the sessions whose check was deferred again."""
    out, held = [], s["busy"]
    for r in unfinished_checks(s["runs"]):
        rid, title = r.get("databaseId"), r.get("displayTitle")
        if lane_started(jobs_of(rid)):
            continue
        entry = recorded(s["rows"], r, now)
        if entry is None:
            out.append(act("checks", "check-unknown", "record", CHECK.match(title)["slot"], key=f"checks-unknown:{rid}",
                           text=f"check run {rid} ({title}) is not in checks.jsonl: left alone, nothing could "
                                f"dispatch it again"))
            continue
        out.append(act("checks", "check-cancel", "run", entry["slot"], key=f"checks-cancel:{rid}",
                       window=RETRY.total_seconds(), argv=cli("cancel", "--run", str(rid), "--repo", main),
                       text=f"cancelled check run {rid} ({title}): {held['reason']}"))
    return out + checks_tell.waits(s, pending(s["rows"]), held["reason"])


def in_flight(rows: list[dict], all_runs: list[dict], now: dt.datetime) -> bool:
    """Is a check run the duty dispatched unfinished (D4: one at a time)? A duty dispatch recorded without its run
    counts as unfinished for MATCH while no run of its title since then is listed."""
    for r in unfinished_checks(all_runs):
        hit = recorded(rows, r, now)
        if hit and hit.get("by") == "checks":
            return True
    cutoff = now.astimezone(dt.timezone.utc) - MATCH

    def listed(d: dict) -> bool:  # its run is in the list (then the loop above judged it)
        return any(x.get("displayTitle") == d.get("title") and mtm_ci.started(x) >= at(d).timestamp() - 60
                   for x in all_runs)
    return any(r["kind"] == "dispatched" and r.get("by") == "checks" and r.get("run") is None and at(r) >= cutoff
               and not listed(r) for r in rows)


def plan(main: str, s: dict, jobs_of, now: dt.datetime) -> list[dict]:
    """The round's actions from `state(...)` (+ `panes`, `log`); `jobs_of(run id)` gives a run's jobs."""
    told = checks_tell.told(s, now, TRIES)
    if s["runs"] is None:  # gh failed: nothing is cancelled or dispatched on a blind round
        return told
    if s["busy"]:
        return holds(main, s, jobs_of, now) + told
    if in_flight(s["rows"], s["runs"], now):
        return told
    nxt, out = next_dispatch(s["rows"], now), []
    if nxt:
        out.append(act("checks", "check-dispatch", "run", nxt["slot"], key=f"checks-dispatch:{nxt['id']}",
                       window=RETRY.total_seconds(), argv=cli("dispatch", "--id", nxt["id"], "--repo", main),
                       text=f"dispatched the deferred check {nxt.get('title')}"))
    return out + told


def jobs_fetch(run_json, main: str, all_runs: list[dict]):
    """`jobs_of` for `plan`: the unfinished checks' jobs, fetched together once per round (gh_runs)."""
    ids = [r["databaseId"] for r in unfinished_checks(all_runs)]
    got = gh_runs.jobs(ids, set(), gh_runs.view_jobs(run_json, main)) if ids else {}
    return lambda rid: got.get(rid, [])


def handler(item: dict, ctx: dict, run_json=None) -> list[dict]:
    """duty:checks: the queue, the train state, the runs and the store, then the round's actions."""
    run_json = run_json or mtm_scan.run_json
    now = ctx["now"] if ctx["now"].tzinfo else ctx["now"].astimezone()
    panes = ctx.get("panes", {})
    s = {**state(ctx["main"], run_json, sessions=set(panes), now=now), "panes": panes, "log": ctx.get("log", [])}
    return plan(ctx["main"], s, jobs_fetch(run_json, ctx["main"], s["runs"]), now)
