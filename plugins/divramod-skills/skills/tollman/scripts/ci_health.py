#!/usr/bin/env python3
"""CI/CD health, the tollman's duty (hal2 plan 0383 step 11, D12, D13): every pass of the 1-minute `watch` checks all
runners of `.github/hal2-runners.toml` (ci_fleet.py) and prints one line for each *new* problem; a healthy fleet prints
nothing, so a quiet minute costs no model call. The printed line wakes the tollman's session, which acts on it
(instructions/ci-health.md). Two kinds of problem, none of them a rule the code cannot judge:

1. **A queued job nobody serves.** A queued job of an unfinished landing run (`self-hosted`) whose labels no online
   runner carries. A runner counts as online when GitHub lists it online and its machine is not parked or stopped
   by the supervisor's power journal (GitHub lists a parked server online for minutes: run 39162581704, whose
   `b1-01-ci-changes` queued 20:17:09 UTC while hz01 was parked and woke at 20:19:51). Then
   - a parked cloud machine (hz01, az01): *at once* `wake` (the line, and the wake request the supervisor reads,
     ci_fleet.request: the tollman never wakes a machine); the machine already waking: nothing
   - the Mac VM runner (`vm`), none online `VM_GRACE` (300 s, the supervisor's `wake_grace`) after the job queued:
     `vm`, the line carries the fix-tart doctor's findings
   - any other runner offline `HOST_GRACE` (180 s, the supervisor's restart grace) after the job queued: `offline`
   - no runner of hal2-runners.toml has the labels: `unserved` after `HOST_GRACE`
2. **A pipeline host runner offline** `HOST_GRACE` seconds (kind `host`, carrying a label of PIPELINE: `hal2`,
   `hal2-gate`, `hal2-stack`, `mac-host-hal2`, `hal2-mac-host`), its machine not parked or waking, no job waiting for it (that is 1.);
   the hand-started runners (the Mac's VM and Docker runners, `hal2-linux-host`, `hal2-windows-host`) are no problem
   while idle.

A problem prints once while it lasts (`ci-health.json` in the tollman's state folder: first seen and told); when it
clears and comes back it is new. GitHub not answering judges nothing. `check(..., dry=True)` writes nothing.
"""

import datetime as dt
import json
import sys

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import ci_fleet
import leavers
import mtm_scan
import tick
from skillpath import sibling
from tick import act

FILE = "ci-health.json"
SCHEMA = 1
DUTY = "ci-health"  # the actions' duty: a wake that reads instructions/ci-health.md; minute.py prints its text
VM_GRACE = 300
HOST_GRACE = 180
PIPELINE = {"hal2", "hal2-gate", "hal2-stack", "mac-host-hal2", "hal2-mac-host"}
HOURS = "2"  # the window of the doctor


def clock(t: str) -> str:
    return t[11:16] + "Z" if len(t or "") >= 16 else "?"


def asleep(fleet: dict, r: dict) -> bool:
    return fleet.get(r["machine"], {}).get("state") in ci_fleet.ASLEEP


def waking(fleet: dict, r: dict) -> bool:
    m = fleet.get(r["machine"], {})
    return bool(m.get("waking")) and m.get("state") in ci_fleet.ASLEEP


def online(gh: dict, fleet: dict, r: dict) -> bool:
    return gh.get(r["name"], {}).get("status") == "online" and not asleep(fleet, r)


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


def job_problem(job: dict, cands: list[dict], gh: dict, fleet: dict, age: float) -> dict | None:
    """The problem of one queued job (None: served, on its way, or not yet old enough to say)."""
    if any(online(gh, fleet, r) for r in cands) or any(waking(fleet, r) for r in cands):
        return None
    sleeping = sorted({r["machine"] for r in cands if asleep(fleet, r)})
    base = {"job": job, "codes": [r["code"] for r in cands]}
    if sleeping:
        return {**base, "kind": "wake", "key": f"wake:{job['job']}", "machines": sleeping}
    if not cands:
        return {**base, "kind": "unserved", "key": f"unserved:{job['job']}"} if age >= HOST_GRACE else None
    if any(r["kind"] == "vm" for r in cands):
        return {**base, "kind": "vm", "key": f"vm:{job['job']}"} if age >= VM_GRACE else None
    return {**base, "kind": "offline", "key": f"queued-offline:{job['job']}"} if age >= HOST_GRACE else None


def problems(main: str, now: dt.datetime) -> list[dict] | None:
    """Every problem of this pass, [{kind, key, ...}]; None when GitHub did not answer."""
    gh = ci_fleet.github_runners(mtm_scan.run_json, main)
    if gh is None:
        return None
    runners, fleet, out, served = ci_fleet.catalog(main), ci_fleet.power(), [], set()
    for job in ci_fleet.queued_jobs(mtm_scan.run_json, main):
        if "self-hosted" not in job["labels"]:
            continue  # GitHub's own runners
        cands = [r for r in runners if job["labels"] <= r["labels"]]
        created = ci_fleet.parse_time(job["created"])
        p = job_problem(job, cands, gh, fleet, (now - created).total_seconds() if created else 0)
        served |= {r["code"] for r in cands}
        if p:
            out.append({**p, "age": (now - created).total_seconds() if created else 0})
    for r in runners:
        if r["kind"] == "host" and r["labels"] & PIPELINE and r["code"] not in served and r["labels"]:
            if not online(gh, fleet, r) and not asleep(fleet, r):
                out.append({"kind": "host-offline", "key": f"offline:{r['code']}", "code": r["code"]})
    return out


def line(p: dict, main: str) -> str:
    """The one line of a new problem."""
    if p["kind"] == "host-offline":
        return f"runners: host runner {p['code']} is offline for {int(p['age'] // 60)} min (the supervisor restarts it)"
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
    now = now or dt.datetime.now(dt.timezone.utc)
    now = now.astimezone(dt.timezone.utc) if now.tzinfo is None else now
    found = problems(main, now)
    if found is None:
        return []
    state = leavers.read(main, FILE, {})
    old, told = state.get("first") or {}, set(state.get("told") or [])
    first = {p["key"]: old.get(p["key"], now.strftime("%Y-%m-%dT%H:%M:%SZ")) for p in found}
    for p in found:
        if p["kind"] == "host-offline":
            p["age"] = (now - ci_fleet.parse_time(first[p["key"]])).total_seconds()
    ripe = [p for p in found if p["kind"] != "host-offline" or p["age"] >= HOST_GRACE]
    wake = [p for p in ripe if p["kind"] == "wake"]
    if not dry:
        for p in wake:
            for m in p["machines"]:
                ci_fleet.request(m, p["job"], "a queued job waits for a parked machine", now)
        ci_fleet.withdraw({m for p in wake for m in p["machines"]})
    out = [act(DUTY, "runner", "wake", "-", key=f"ci-health:{p['key']}:{first[p['key']]}", text=line(p, main),
               evidence=evidence(p)) for p in ripe if p["key"] not in told]
    if not dry:
        leavers.write(main, FILE, {"schema": SCHEMA, "first": first, "told": sorted(p["key"] for p in ripe)})
    return out
