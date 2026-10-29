"""Prune's plan (hal2 plan 0377 step 4): the pure decision, no IO. It takes step 3's `facts.collect` result and returns
the planned actions per job, in the brief's order (contract: design/prune-run/sequence/v1/contract.md; D5, D6, D15-D17).

Jobs, in order: `stale-pointers` (a CURRENT_PLAN naming a finished or missing plan, cleared; the caller then re-collects
those fields, so a cleared field is planned again, never in a phase on its old proof), `phase-1` (the free fields:
10-99 removed, 00-09 mucked out, never removed; a servant whose commits are not in its foreman's branch is an `ask`),
`phase-2` (session-less fields not free, and free 00-09 ones after their muck out, D24: trimmed) and `phase-3` (idle
live fields, trimmed), the last two only while the disk is short (D15) and then until the goal: the executor reads the disk before each action and stops at the goal.
`responses` follows them on the same terms (short disk, no train building): `tart prune --entries caches` and the
caches `.hal/prune.toml` lists (responses.py), each with its measured size, run only while the disk is still above the goal.
In a job the last train's cars come first, then the biggest field; an unknown size counts by its lower bound.
An action is `{field, action, why, bytes, lower_bound, ...}`; `left` holds the fields no job acts on, with why.
"""

import facts as farm_facts  # the threshold and goal rules have one home (step 3)
import prune_proof
import sizes

STALE, PHASE1, PHASE2, PHASE3 = "stale-pointers", "phase-1", "phase-2", "phase-3"
RESPONSES = "responses"  # after the trims, still above the goal: Tart's OCI cache, the listed caches (plan 0472 D2)
JOBS = (STALE, PHASE1, PHASE2, PHASE3, RESPONSES)
FINISHED_STATES = ("finished", "missing")


def lower(f: dict) -> int:
    """The field's size in bytes, a lower bound counting as it is; unknown counts 0."""
    return (f.get("size") or {}).get("bytes", 0)


def action(f: dict, kind: str, why: str, **more) -> dict:
    size = f.get("size") or {}
    return {"field": f["slot"], "action": kind, "why": why, "bytes": lower(f), "lower_bound": bool(size.get("lower_bound")),
            **more}


def ordered(fs: list[dict], cars: list[str]) -> list[dict]:
    """The last train's cars first, then the biggest, then by slot (PR16)."""
    return sorted(fs, key=lambda f: (f["slot"] not in cars, -lower(f), f["slot"]))


def stale(f: dict) -> bool:
    """D5: CURRENT_PLAN names a finished or missing plan, nothing off main, nothing uncommitted, no live session."""
    ptr = f.get("pointer")
    return bool(ptr and ptr["state"] in FINISHED_STATES and f.get("unsaved") == [] and not f["sessions"])


def idle(f: dict, now_ms: float) -> bool:
    """D17: a live field with no busy agent, no session active in the last 30 minutes (00-09 too), no build, no queue
    ticket, landing, boss pause or open question."""
    if not f["sessions"] or f.get("building") or f.get("hold"):
        return False
    return all(s.get("state") not in prune_proof.BUSY and now_ms - (s.get("since") or 0) >= prune_proof.QUIET * 1000
               for s in f["sessions"])


def asks(f: dict, now_ms: float) -> str | None:
    """D6: the foreman to ask about a servant whose work is not in `origin/<foreman>`: a servant nobody uses (no session,
    no ticket, plans/LEAD older than the foreman's reuse window) holding commits its foreman's branch lacks."""
    lead = f.get("lead")
    if f["kind"] != "servant" or not lead or lead.get("bad") or not lead.get("missing"):
        return None
    if f["sessions"] or f.get("hold") or now_ms - lead["at"] * 1000 < prune_proof.SUBSERVANT_QUIET * 1000:
        return None
    return lead["slot"]


def phase1(fs: list[dict], cars: list[str], now_ms: float, wait: str | None = None) -> list[dict]:
    out = []
    for f in ordered(fs, cars):
        if f["free"]:
            if f["kind"] == "keeper":
                if wait:
                    continue  # a muck out is a mass delete: it waits for the gap between trains (plan 0472 D1)
                out.append(action(f, "muck-out", "free by the proof; 00-09 are never removed"))
            else:
                stop = [s["pane_id"] for s in f["sessions"]]
                out.append(action(f, "remove", "free by the proof" + (", its idle session stopped first" if stop else ""),
                                  stop_sessions=stop, servant_of=(f.get("lead") or {}).get("slot")))
        elif (foreman := asks(f, now_ms)):
            out.append(action(f, "ask", f"{'; '.join(f['lead']['missing'])}", foreman=foreman))
    return out


def trims(fs: list[dict], cfg: dict, why: str) -> list[dict]:
    return [action(f, "trim", why, paths=cfg["phases"]["trim"]) for f in fs]


def skipped(on: bool, short: bool, disk: dict, flag: str) -> str | None:
    if not short:
        return f"disk fine ({disk['free_gb']:g} GB free)"
    return None if on else f"switched off in .hal/prune.toml ({flag})"


def plan(facts: dict, only: set[str] | None = None, now_ms: float | None = None) -> dict:
    """The jobs and actions for `facts` (`only`: just those fields, the barn's cars, D12). Pure: the same facts give the
    same plan; `facts["now_ms"]` is the clock the proof used."""
    now_ms = now_ms if now_ms is not None else facts.get("now_ms", 0)
    fs = [f for f in facts["fields"] if only is None or f["slot"] in only]
    cfg, disk, cars = facts["config"], facts["disk"], facts.get("cars", [])
    short = farm_facts.short_of_space(disk, cfg)
    wait = facts.get("busy")  # a train builds (busy.py): no trim, no muck out
    cleared = [f for f in fs if stale(f)]
    rest = [f for f in fs if f not in cleared]
    jobs = {STALE: {"skipped": None if cleared else "no stale pointer", "actions": [
        action(f, "clear-pointer", f"CURRENT_PLAN {f['pointer']['plan']} cleared: {f['pointer']['state']}",
               plan=f["pointer"]["plan"], recheck=True) for f in ordered(cleared, cars)]}}
    one = phase1(rest, cars, now_ms, wait)
    jobs[PHASE1] = {"skipped": None if one else "no free field", "actions": one}
    done = {a["field"] for a in one if a["action"] == "remove"}
    p2 = [f for f in rest if f["slot"] not in done and (not f["free"] or f["kind"] == "keeper") and not f["sessions"]
          and not f.get("hold") and not f.get("building")]  # D24: a free 00-09's trim paths outlive its muck out
    p3 = [f for f in rest if f["slot"] not in done and idle(f, now_ms)]
    for name, cands, flag, why in ((PHASE2, p2, "trim_session_less", "session-less, not free"),
                                   (PHASE3, p3, "trim_idle_live", "idle live field")):
        off = skipped(cfg["phases"][flag], short, disk, flag)
        off = wait if wait and off is None else off
        acts = [] if off else trims(ordered(cands, cars), cfg, why)
        jobs[name] = {"skipped": off or (None if acts else "no candidate"), "actions": acts, "until_goal": True}
    jobs[RESPONSES] = responses_job(facts.get("responses", []), short, disk, wait)
    acted = {a["field"] for j in jobs.values() for a in j["actions"]} | {f["slot"] for f in cleared}
    left = [{"field": f["slot"], "why": f.get("proof") or (wait if wait and f["free"] else "nothing to do")}
            for f in fs if f["slot"] not in acted]
    return {"short": short, "goal_met": farm_facts.goal_met(disk, cfg), "disk": disk, "goal": cfg["goal"], "busy": wait, "jobs": jobs, "left": left}


def responses_job(found: list[dict], short: bool, disk: dict, wait: str | None) -> dict:
    """The watermark's responses (plan 0472 D2): the biggest first; a tool or folder that is not there is said."""
    notes = [c["why"] for c in found if c["action"] == "missing"]
    off = skipped(True, short, disk, "responses")
    off = wait if wait and off is None else off
    acts = [] if off else sorted((c for c in found if c["action"] != "missing"), key=lambda c: (-c["bytes"], c["field"]))
    return {"skipped": off or (None if acts else "; ".join(notes) or "no candidate"), "actions": acts,
            "until_goal": True, "notes": notes}


def field_line(f: dict) -> str:
    """A field of the facts in one line: kind, sessions, the proof, the size."""
    who = ", ".join(f"{s['pane_id']} {s['state']}" for s in f["sessions"]) or "no session"
    return f"{f['slot']} {f['kind']}: {who}; {'free' if f['free'] else f['proof']}; {sizes.human(f['size'])}"


def describe(a: dict, dry: bool = True) -> str:
    """One line for an action: "would remove 23: ..." in a dry run, the past tense otherwise (the executor prefixes real
    numbers itself); an `ask` reads the same either way."""
    field, why = a["field"], a["why"]
    size = f" ({sizes.human({'bytes': a['bytes'], 'lower_bound': a['lower_bound']})})" if a["bytes"] else ""
    if a["action"] == "ask":
        return f"ask the foreman of field {a['foreman']} about field {field}: {why}"
    if a["action"] == "clear-pointer":
        return f"{'would clear' if dry else 'cleared'} {field}: {why}, then the proof runs again"
    if a["action"] == "muck-out":
        return f"{'would muck out' if dry else 'mucked out'} {field}{size}: {why}"
    if a["action"] == "remove":
        stop = f"stop session {', '.join(a['stop_sessions'])}, " if a.get("stop_sessions") and dry else ""
        return f"{'would ' + stop + 'remove' if dry else 'removed'} {field}{size}: {why}"
    if a["action"] == "tart-prune":
        return f"{'would run' if dry else 'ran'} tart prune --entries caches --older-than={a['older_than_days']}{size}: {why}"
    if a["action"] == "cache-clear":
        return f"{'would clear' if dry else 'cleared'} {a['target']}{size}: {why}"
    paths = ", ".join(a["paths"]) if a.get("paths") else "cleanup's own set"
    return f"{'would trim' if dry else 'trimmed'} {field} {paths}{size}: {why}"


def lines(p: dict) -> list[str]:
    """The plan as text: the disk, per job its skip reason or one line per action, the fields left."""
    d, g = p["disk"], p["goal"]
    out = [f"disk: {d['free_gb']:g} GB free, {d['used_pct']:g}% used ({'short' if p['short'] else 'fine'}); "
           f"goal {g['free_gb']:g} GB free, at most {g['used_pct']:g}% used"]
    for name in JOBS:
        job = p["jobs"][name]
        out.append(f"{name}: skipped: {job['skipped']}" if job["skipped"] else f"{name}:")
        out += [f"  {describe(a)}" for a in job["actions"]]
        out += [f"  note: {n}" for n in job.get("notes", [])]
    out += [f"left {x['field']}: {x['why']}" for x in p["left"]]
    return out
