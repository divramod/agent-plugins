#!/usr/bin/env python3
"""CI/CD health, the tollman's duty (hal2 plan 0383 step 11, D12, D13): every pass of the 1-minute `watch` checks all
runners of `.github/hal2-runners.toml` (ci_fleet.py) and prints one line for each *new* problem; a healthy fleet prints
nothing, so a quiet minute costs no model call. The printed line wakes the tollman's session, which acts on it
(instructions/ci-health.md). One kind of problem, no rule the code cannot judge:

1. **A queued job nobody serves.** A queued job of an unfinished landing run (`self-hosted`) whose labels no online
   runner carries. A runner counts as online when GitHub lists it online and its machine is not parked or stopped
   by the supervisor's power journal (GitHub lists a parked server online for minutes: run 39162581704, whose
   `b1-01-ci-changes` queued 20:17:09 UTC while hz01 was parked and woke at 20:19:51). Then
   - a parked cloud machine (hz01, az01): *at once* `wake` (the line, and the wake request the supervisor reads,
     ci_fleet.request: the tollman never wakes a machine); the machine already waking: nothing
   - the Mac VM runner (`vm`), none online `VM_GRACE` (300 s, the supervisor's `wake_grace`) after the job queued:
     `vm`, the line carries the fix-tart doctor's findings
   - an on-demand host runner the supervisor parked (its journal's `runner <code>: stopped`, plan 0721, L268): left
     to the supervisor, which starts it for the job by itself (no wake request: those name cloud machines); one it
     started under `HOST_GRACE` ago is on its way; still parked `PARK_GRACE` (300 s, five of its runner looks)
     after the job queued: `parked` (the supervisor did not start it), never `offline`
   - any other runner offline `HOST_GRACE` (180 s, the supervisor's restart grace) after the job queued: `offline`
   - no runner of hal2-runners.toml has the labels: `unserved` after `HOST_GRACE`

An idle host runner offline with no queued job that needs it is no problem and wakes nobody (plan 0695 row 26, D40 T4:
the supervisor restarts or parks it); only the queued job that waits for it (1.) is.

A problem prints once while it lasts (`ci-health.json` in the tollman's state folder: first seen and told, each told
key with its time); A queued job's is told once for its run's life
(RUN_LIFE, keyed by the job's id in its run): one that flaps clear and back between passes never wakes again (L72). The runners GitHub lists are asked once a pass and only when a check needs them
(plan 0480 D2); GitHub not answering judges nothing. `check(..., dry=True)` writes nothing.
"""

import datetime as dt
import json
import sys

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import ci_fleet
import leavers
import mtm_scan
import roletime
import tick
from skillpath import sibling
from tick import act

FILE = "ci-health.json"
SCHEMA = 1
DUTY = "ci-health"  # the actions' duty: a wake that reads instructions/ci-health.md; minute.py prints its text
VM_GRACE = 300
HOST_GRACE = 180
PARK_GRACE = 300  # a parked host runner's start for a queued job: the supervisor's runners look runs every 60 s
HOURS = "2"  # the window of the doctor
RUN_LIFE = dt.timedelta(hours=6)  # a land run's longest life (next_train.MAX_WAIT): a job's problem is told once in it


VM_KINDS = ("vm", "tart")  # the Mac VM's code: `mac-vm-a`, since plan 0755 D57 `mac-tart-hal2-a`

def clock(t: str) -> str:
    return t[11:16] + "Z" if len(t or "") >= 16 else "?"


def asleep(fleet: dict, r: dict) -> bool:
    return fleet.get(r["machine"], {}).get("state") in ci_fleet.ASLEEP


def waking(fleet: dict, r: dict) -> bool:
    m = fleet.get(r["machine"], {})
    return bool(m.get("waking")) and m.get("state") in ci_fleet.ASLEEP


class Unanswered(Exception):
    """GitHub did not list the runners: nothing is judged this pass."""


class Runners:
    """The runners GitHub lists ({name: {status, busy}}), asked once a pass and only when a check needs them (plan
    0480 D2): a queued self-hosted job with candidates not waking, or a pipeline host runner not asleep."""

    def __init__(self, main: str):
        self.main, self.rows, self.asked = main, None, False

    def __call__(self) -> dict:
        if not self.asked:
            self.rows, self.asked = ci_fleet.github_runners(mtm_scan.run_json, self.main), True
        if self.rows is None:
            raise Unanswered
        return self.rows


def online(gh, fleet: dict, r: dict) -> bool:
    """GitHub lists the runner online and its machine is not asleep; `gh()` gives the runners (asked only for a
    runner whose machine is awake)."""
    return not asleep(fleet, r) and gh().get(r["name"], {}).get("status") == "online"


def doctor(main: str) -> str:
    """The fix-tart doctor's findings of the last hours as one phrase: `slug (n), ...`, else "no case"."""
    try:
        script = sibling("fix-tart") / "scripts" / "evidence.py"
    except FileNotFoundError:
        return "the fix-tart skill was not found"
    code, out = tick.sh([sys.executable, str(script), "doctor", "--hours", HOURS, "--json"], main, 120)
    try:
        found = json.loads(out[out.index("{"):])["findings"]
    except (ValueError, KeyError):
        return f"it failed (exit {code})"
    count: dict[str, int] = {}
    for f in found:
        count[f["slug"]] = count.get(f["slug"], 0) + 1
    return ", ".join(f"{s} ({n})" for s, n in count.items()) or "no case"


def since(at: str | None, now: dt.datetime) -> float:
    """Seconds from `at` to `now`; 0 without a time."""
    t = ci_fleet.parse_time(at)
    return (now - t).total_seconds() if t else 0


def job_problem(job: dict, cands: list[dict], gh, fleet: dict, age: float, hosts: dict | None = None,
                now: dt.datetime | None = None) -> dict | None:
    """The problem of one queued job (None: served, on its way, or not yet old enough to say); `gh()` the runners,
    `hosts` the host runners' last word in the supervisor's journal (ci_fleet.host_runners)."""
    if any(waking(fleet, r) for r in cands) or any(online(gh, fleet, r) for r in cands):
        return None
    sleeping = sorted({r["machine"] for r in cands if asleep(fleet, r)})
    base = {"job": job, "codes": [r["code"] for r in cands]}
    if sleeping:
        return {**base, "kind": "wake", "key": f"wake:{job['job']}", "machines": sleeping}
    if not cands:
        return {**base, "kind": "unserved", "key": f"unserved:{job['job']}"} if age >= HOST_GRACE else None
    if any(r["kind"] in VM_KINDS for r in cands):
        return {**base, "kind": "vm", "key": f"vm:{job['job']}"} if age >= VM_GRACE else None
    word = [((hosts or {}).get(r["code"]) or {}, r["code"]) for r in cands]
    if now and any(w.get("state") == "starting" and since(w["at"], now) < HOST_GRACE for w, _ in word):
        return None  # the supervisor started it for a job: on its way
    if parked := [code for w, code in word if w.get("state") == "parked"]:  # left to the supervisor (D3)
        told = {**base, "kind": "parked", "key": f"parked:{job['job']}", "parked": parked}
        return told if age >= PARK_GRACE else None
    return {**base, "kind": "offline", "key": f"queued-offline:{job['job']}"} if age >= HOST_GRACE else None


def problems(main: str, now: dt.datetime) -> list[dict] | None:
    """Every problem of this pass, [{kind, key, ...}]; None when GitHub did not list the runners a check needed."""
    try:
        return look(main, now, Runners(main))
    except Unanswered:
        return None


def look(main: str, now: dt.datetime, gh) -> list[dict]:
    """`problems` with the runners `gh()` (it raises Unanswered)."""
    runners, text, out = ci_fleet.catalog(main), ci_fleet.journal(), []
    fleet, hosts = ci_fleet.machines(text), ci_fleet.host_runners(text)
    train: list[list[dict]] = []  # the standing train's own runners, read for the first job the barn's cannot serve
    for job in ci_fleet.queued_jobs(mtm_scan.run_json, main):
        if "self-hosted" not in job["labels"]:
            continue  # GitHub's own runners
        cands = [r for r in runners if job["labels"] <= r["labels"]]
        if not cands:  # L91: a car of the train renamed the runners
            train = train or [ci_fleet.train_catalog(main, {r["code"] for r in runners})]
            cands = [r for r in train[0] if job["labels"] <= r["labels"]]
        created = ci_fleet.parse_time(job["created"])
        p = job_problem(job, cands, gh, fleet, (now - created).total_seconds() if created else 0, hosts, now)
        if p:
            out.append({**p, "age": (now - created).total_seconds() if created else 0})
    # D40 T4 (plan 0695 row 26): an idle host runner offline with no queued job that needs it is no problem and wakes
    # nobody (the supervisor restarts or parks it); only a queued job that waits for it is (job_problem, above).
    return out


def line(p: dict, main: str) -> str:
    """The one line of a new problem."""
    j = p["job"]
    what = f"job {j['name']} (run {j['run']}, queued {clock(j['created'])})"
    need = ",".join(sorted(j["labels"] - {"self-hosted"}))
    if p["kind"] == "wake":
        asked = ", ".join(str(ci_fleet.request_path(m)) for m in p["machines"])
        return (f"runners: {what} waits for [{need}]: {', '.join(p['machines'])} is parked; asked the CI supervisor to "
                f"wake it ({asked})")
    if p["kind"] == "vm":
        return (f"runners: {what} waits {int(p['age'] // 60)} min for the Mac VM runner, none online; fix-tart doctor: "
                f"{doctor(main)}")
    if p["kind"] == "parked":
        return (f"runners: {what} waits {int(p['age'] // 60)} min for [{need}]: {', '.join(p['parked'])} parked by the "
                f"CI supervisor and not started for it ({ci_fleet.supervisor_dir() / 'power.log'})")
    if p["kind"] == "unserved":
        return f"runners: {what} waits for [{need}]: no runner of hal2-runners.toml has these labels"
    return f"runners: {what} waits {int(p['age'] // 60)} min for [{need}]: {', '.join(p['codes'])} offline"


def evidence(p: dict) -> dict:
    """What the woken session reads besides the line (JSON): the problem without its sets."""
    job = p.get("job")
    return {**{k: v for k, v in p.items() if k != "job"},
            **({"job": {**job, "labels": sorted(job["labels"])}} if job else {})}


def check(top: str, main: str, now: dt.datetime | None = None, dry: bool = False) -> list[dict]:
    """The wake actions for this pass: one for each problem not told yet (the line is the action's text; it prints); the wake
    requests written and the state kept unless `dry`."""
    now = roletime.aware(now)
    found = problems(main, now)
    if found is None:
        return []
    state, stamp = leavers.read(main, FILE, {}), roletime.stamp(now)
    old, told = state.get("first") or {}, kept(state.get("told"), now, stamp)
    first = {p["key"]: old.get(p["key"], stamp) for p in found}
    ripe = found
    wake = [p for p in ripe if p["kind"] == "wake"]
    if not dry:
        for p in wake:
            for m in p["machines"]:
                ci_fleet.request(m, p["job"], "a queued job waits for a parked machine", now)
        ci_fleet.withdraw({m for p in wake for m in p["machines"]})
    out = [act(DUTY, "runner", "wake", "-", key=f"ci-health:{p['key']}:{first[p['key']]}", text=line(p, main),
               evidence=evidence(p)) for p in ripe if p["key"] not in told]
    if not dry:
        now_told = {p["key"]: told.get(p["key"], stamp) for p in ripe}
        leavers.write(main, FILE, {"schema": SCHEMA, "first": first, "told": {
            **{k: at for k, at in told.items() if not k.startswith("offline:")}, **now_told}})
    return out


def kept(told, now: dt.datetime, stamp: str) -> dict:
    """The told keys still in force, {key: told at}: a job's for RUN_LIFE (L72), a host runner's while it lasts (the
    last pass's; the write drops one this pass did not find); an older file's list counts as told now."""
    told = told if isinstance(told, dict) else {k: stamp for k in told or []}
    return {k: at for k, at in told.items() if k.startswith("offline:")
            or ((t := ci_fleet.parse_time(at)) and now - t < RUN_LIFE)}
