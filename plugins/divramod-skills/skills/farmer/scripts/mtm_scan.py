#!/usr/bin/env python3
"""One snapshot of a repository's road to main, for the farmer skill's merge-to-main boss.

  scan.py scan [--repo <dir>] [--hours 24] [--json]
      the merge queue (holder, its process, its agent, attempts, why it failed),
      the waiters, the machine's load, every worktree with work not on main and
      no ticket, the failing tests of the recent landings (repeat offenders are
      flaky candidates), and findings: what the boss should act on, most urgent first
  scan.py record <kind> <slot> <what> [--note <text>]
      append what the boss did to log.jsonl (the next scans show it)
  scan.py pause|resume [--repo <dir>] [--note <why>]
      set or clear the boss's queue pause flag (sessions are told by the boss)
  scan.py summary [--repo <dir>] [--notes <text>]
      scan, then write the round's summary (queue, landings, worktrees, findings, the
      boss's actions and notes) to summaries/<day>/<HHMM>.md and latest.md in the farmer's state
      folder (roles/farmer/ of its slot, ignored by the role folder's .gitignore)
  scan.py priority <slot>... [--note <why>] | priority --clear | priority --done <slot>
      the slots the user wants landed first: hal2 orders the queue (`hal2-cli-git worktree
      queue order`: listed slots first, each place reserved, the holder never preempted);
      priority.json keeps the user's request and why (findings name them first); --done takes
      a landed slot off it (hal2 drops it from its order when its turn ends)
  scan.py status [--json]
      the priority, the pause flag, the last scan, the actions of the last 6 h

Reads hal2 (hal2-cli-git worktree queue, hal2-cli-agents list), git and the recent
landings: GitHub's land.yml runs (gh) where the default branch has land.yml (mtm_ci.py),
else `hal2-cli-git worktree landings`; writes only the farmer's state folder (roles/farmer/ of its slot). Exit 0 on success,
2 when a tool is missing.
"""

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import lead_marker
import roles

import mtm_ci

DATA = roles.OVERRIDE  # FARMER_DIR's root, else None: the farmer slot's roles/farmer/ (roles.state_dir)
TOOLS = ("hal2-cli-git", "hal2-cli-agents", "git")

MINUTE = 60
HELD_IDLE_AFTER = 15 * MINUTE  # a failed landing nobody reruns
ACTIVE_TOO_LONG = 60 * MINUTE  # a landing running this long is suspect
IDLE_WITH_WORK_AFTER = 30 * MINUTE  # finished work nobody queues
RESERVATION_WAITS_AFTER = 60 * MINUTE  # the queue waits at the front for a reserved slot without progress
LOAD_PER_CORE_HIGH = 2.0  # load average per core that breaks timing tests
BUSY = {"working", "starting"}
WORKING_TASKS = {"shell", "subagent", "workflow"}  # background tasks that mean a session still works

# Failing test names in a landing's message: Swift Testing, XCTest, cargo test, nextest.
TEST_PATTERNS = (
    re.compile(r"✘ Test (\w[\w.]*)\(.*?\) failed"),
    re.compile(r"Test Case '-\[\S+ (\w+)\]' failed"),
    re.compile(r"^\s*test ([\w:]+) \.\.\. FAILED", re.M),
    re.compile(r"FAIL \[\s*[\d.]+s\] (?:\(\d+/\d+\) )?(\S+ [\w:]+)"),
)
LOAD_HINTS = re.compile(r"busy machine|budget|watchdog|took \d|timed out|deadline|Elapsed|< .*limit", re.I)


def run(args: list[str], cwd: str | None = None) -> str:
    try:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def run_json(args: list[str], cwd: str | None = None):
    out = run(args, cwd)
    try:
        return json.loads(out) if out.strip() else None
    except json.JSONDecodeError:
        return None


def pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    return True


def parse_time(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def landing_start(landing_id: str | None) -> float | None:
    """`2026-10-03T02-33-17.591Z-12` -> its start as a timestamp."""
    m = re.match(r"(\d{4}-\d\d-\d\dT)(\d\d)-(\d\d)-(\d\d(?:\.\d+)?)Z", landing_id or "")
    return parse_time(f"{m.group(1)}{m.group(2)}:{m.group(3)}:{m.group(4)}Z") if m else None


def failing_tests(message: str) -> list[str]:
    found: list[str] = []
    for pattern in TEST_PATTERNS:
        for name in pattern.findall(message or ""):
            if name not in found:
                found.append(name)
    # nextest names a test `crate::binary test_name`; cargo's own line names it bare.
    return [n for n in found if not any(o != n and o.endswith((" " + n, "::" + n)) for o in found)]


def failed_task(message: str) -> str:
    first = (message or "").splitlines()[0] if message else ""
    m = re.match(r"(\S+ [\w-]+) \(", first)
    return m.group(1) if m else first[:120]


def main_checkout(repo: str) -> str:
    common = run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], repo).strip()
    return str(Path(common).parent) if common else repo


def worktrees(main: str) -> list[dict]:
    out, items, cur = run(["git", "worktree", "list", "--porcelain"], main), [], {}
    for line in out.splitlines() + [""]:
        if not line:
            if cur.get("path") and cur.get("path") != main and not cur.get("prunable"):
                items.append(cur)
            cur = {}
        elif line.startswith("worktree "):
            cur["path"] = line[9:]
        elif line.startswith("branch "):
            cur["branch"] = line[7:].removeprefix("refs/heads/")
        elif line.startswith("prunable"):
            cur["prunable"] = True
    return items


def lead_of(path: str | Path) -> dict | None:
    """A parallel plan's subservant marker (skills plan 0013): <worktree>/plans/LEAD, one line `<lead-slot> <plan>
    <step>`, as {slot, plan, step}; a broken one as {bad: True, error, text} (still marked); None without one. A
    marked slot never lands."""
    return lead_marker.marker(path)


def subservant(lead: dict) -> str:
    return lead_marker.describe(lead)


def fetch_leads(main: str, paths: list[str]) -> None:
    """The lead branches of the marked worktrees, fresh: a subservant's work is measured against origin/<lead>."""
    leads = {lead["slot"] for p in paths if (lead := lead_of(p)) and not lead.get("bad")}
    for slot in sorted(leads):
        run(["git", "fetch", "--quiet", "origin", f"+refs/heads/{slot}:refs/remotes/origin/{slot}"], main)


def unmerged(path: str, default: str) -> int:
    out = run(["git", "rev-list", "--count", f"origin/{default}..HEAD"], path).strip()
    return int(out) if out.isdigit() else 0


def agents_by_checkout(agents: list[dict]) -> dict[str, dict]:
    by: dict[str, dict] = {}
    for a in agents:
        if a.get("kind") in (None, "claude", "codex", "opencode") and a.get("checkout"):
            prev = by.get(a["checkout"])
            if prev is None or a.get("state") in BUSY:
                by[a["checkout"]] = a
    return by


def landings_summary(landings: list[dict], since: float) -> tuple[list[dict], dict[str, dict]]:
    recent, tests = [], {}
    for x in landings:
        started = parse_time(x.get("started")) or 0
        if started < since:
            continue
        slot = Path(x.get("worktree") or "").name
        names = failing_tests(x.get("message") or "") if x.get("outcome") == "failed" else []
        recent.append({
            "id": x.get("id"), "slot": slot, "outcome": x.get("outcome"),
            "task": failed_task(x.get("message") or "") if x.get("outcome") != "landed" else "",
            "tests": names, "load_hint": bool(LOAD_HINTS.search(x.get("message") or "")),
        })
        for name in names:
            t = tests.setdefault(name, {"test": name, "failures": 0, "slots": []})
            t["failures"] += 1
            if slot not in t["slots"]:
                t["slots"].append(slot)
    return recent, tests


def reservation_waits(head: dict, w: dict, now: float) -> dict | None:
    """The queue waits at the front for a reserved slot that does not come: reserved over an hour ago, its slot
    without an agent or with one not busy for an hour. The boss tells the user; it never releases a reservation."""
    since = parse_time((head.get("reserved") or {}).get("since"))
    if since is None or now - since < RESERVATION_WAITS_AFTER:
        return None
    agent = w.get("agent_state")
    if agent in BUSY or (agent and w.get("agent_idle_seconds", 0) < RESERVATION_WAITS_AFTER):
        return None
    idle = f" for {w.get('agent_idle_seconds', 0) // MINUTE} min" if agent else ""
    return {"kind": "reservation-waits", "slot": head["slot"], "seq": head.get("seq"),
            "why": f"the queue waits at the front for slot {head['slot']}'s reservation since "
                   f"{int((now - since) // MINUTE)} min ({head['reserved'].get('by')}), its agent is "
                   f"{agent or 'none'}{idle}"}


def holder_works(w: dict, snap: dict) -> bool:
    """The reserved queue's holder is not idle (hal2 plan 0169, the incident of 2026-10-06: `reserved-idle` made
    slot 05 land in the middle of its measurement turn): its agent is busy or was within HELD_IDLE_AFTER, runs a
    background shell, subagent or workflow, or a land.yml run (a dispatch of it, a landing that ships) is unfinished."""
    agent = w.get("agent_state")
    return bool(agent in BUSY or (agent and w.get("agent_idle_seconds", 0) < HELD_IDLE_AFTER)
                or w.get("agent_tasks") or snap.get("runs_unfinished"))


def orphaned_subservant(w: dict) -> dict:
    """A marked slot without a session whose work its lead's branch lacks: restarted only with /handoff c, never
    /mtm (boss.orphan); a slot whose work is all in origin/<lead> is done (prune removes it), never restarted."""
    return {"kind": "work-without-agent", "slot": w["slot"], "lead": w["lead"],
            "why": f"{subservant(w['lead'])}: {'; '.join(w['missing'])}, no agent session"}


def findings(snap: dict) -> list[dict]:
    """What the boss acts on, most urgent first."""
    out, now = [], snap["now"]
    queue, by_slot = snap["queue"], {w["slot"]: w for w in snap["worktrees"]}
    # A subservant never lands (plans/LEAD): its ticket wakes the farmer, the landing findings skip it.
    marked = {s: w["lead"] for s, w in by_slot.items() if w.get("lead")}
    head = queue[0] if queue and queue[0]["slot"] not in marked else None
    for slot in (snap.get("priority") or {}).get("slots", []):
        w, t = by_slot.get(slot, {}), next((t for t in queue if t["slot"] == slot), None)
        state = "reserved, waits for its landing" if t and t.get("awaiting_slot") else (t or {}).get("state")
        place = f"#{queue.index(t)} in the queue, {state}" if t else "not in the queue"
        out.append({"kind": "priority", "slot": slot,
                    "why": f"the user wants it landed first ({(snap['priority'].get('note') or '')}): {place}, "
                           f"{w.get('ahead', '?')} commits not on main, agent {w.get('agent_state') or 'none'}"})
    if snap.get("paused"):
        out.append({"kind": "paused", "slot": "", "why": f"the boss paused the queue: {snap['paused'].get('note', '')}"})
    for i, t in enumerate(queue):
        if lead := marked.get(t["slot"]):
            out.append({"kind": "subservant-holds", "slot": t["slot"], "seq": t.get("seq"), "lead": lead,
                        "why": f"{subservant(lead)} has a merge-queue ticket (#{i}, {t['state']}): a subservant "
                               f"never lands, its lead{'' if lead.get('bad') else ' in slot ' + lead['slot']} "
                               f"merges it"})
    if head and head.get("awaiting_slot"):
        if f := reservation_waits(head, by_slot.get(head["slot"], {}), now):
            out.append(f)
    if head and head["state"] == "held":
        age = now - (parse_time(head.get("enqueued")) or now)
        agent = by_slot.get(head["slot"], {}).get("agent_state")
        hold = head.get("hold") or {}
        # A CI landing holds the queue as its reservation while its run is tested: its process lives.
        if hold.get("reason") == "reserved" and not head.get("process_alive") and age > HELD_IDLE_AFTER \
                and not holder_works(by_slot.get(head["slot"], {}), snap):
            out.append({"kind": "reserved-idle", "slot": head["slot"],
                        "why": f"reserved the queue, its agent is {agent}, nothing lands"})
        elif hold.get("reason") != "reserved" and not head.get("process_alive") and agent not in BUSY:
            out.append({"kind": "held-idle", "slot": head["slot"],
                        "why": f"failed landing holds the queue ({hold.get('step')}, attempt "
                               f"{hold.get('attempts')}), no landing runs, its agent is {agent}",
                        "failure": failed_task(hold.get("message") or ""),
                        "tests": failing_tests(hold.get("message") or "")})
    if head and head["state"] == "active":
        if head.get("active_seconds", 0) > ACTIVE_TOO_LONG:
            f = {"kind": "active-long", "slot": head["slot"],
                 "why": f"landing {head.get('landing')} runs for {head['active_seconds'] // 60} min"}
            if snap.get("ci") and (r := mtm_ci.running_run(snap["landings"], head["slot"])):
                f["run"] = r["url"]
            out.append(f)
    if snap["load"]["per_core"] >= LOAD_PER_CORE_HIGH and head and head["state"] == "active":
        out.append({"kind": "load-high", "slot": head["slot"],
                    "why": f"load {snap['load']['load1']:.0f} on {snap['load']['cores']} cores during a landing",
                    "busy_slots": [w["slot"] for w in snap["worktrees"]
                                   if w.get("agent_state") in BUSY and w["slot"] != head["slot"]]})
    waiting = [t for t in queue if t["state"] == "waiting" and t["slot"] not in marked]
    for t in waiting:
        if not t.get("process_alive") and not t.get("parked") and not t.get("reserved"):
            out.append({"kind": "waiter-gone", "slot": t["slot"], "why": "ticket without a live reserve process"})
    for name, t in sorted(snap["tests"].items(), key=lambda kv: -kv[1]["failures"]):
        if t["failures"] >= 2 or len(t["slots"]) >= 2:
            out.append({"kind": "flaky-candidate", "slot": ",".join(t["slots"]),
                        "why": f"{name} failed {t['failures']}x in {len(t['slots'])} slot(s)", "test": name})
    queued = {t["slot"] for t in queue}
    for w in snap["worktrees"]:
        if w.get("lead"):  # a subservant: measured against its lead's branch, never main
            if w.get("missing") and w["slot"] not in queued and w.get("agent_state") is None:
                out.append(orphaned_subservant(w))
            continue
        if w["ahead"] and w["slot"] not in queued and w.get("agent_state") is None:
            out.append({"kind": "work-without-agent", "slot": w["slot"],
                        "why": f"{w['ahead']} commits not on main, plan {w.get('plan') or '-'}, no agent session"})
            continue
        if w["ahead"] and w["slot"] not in queued and w.get("agent_state") not in BUSY \
                and w.get("agent_idle_seconds", 0) > IDLE_WITH_WORK_AFTER:
            out.append({"kind": "work-not-queued", "slot": w["slot"],
                        "why": f"{w['ahead']} commits not on main, plan {w.get('plan') or '-'}, "
                               f"agent {w.get('agent_state') or 'none'} for {w['agent_idle_seconds'] // 60} min"})
    if len(waiting) >= 3:
        out.append({"kind": "long-queue", "slot": ",".join(t["slot"] for t in waiting),
                    "why": f"{len(waiting)} waiting: consider a merge train (see SKILL.md)"})
    return out


def worktree_entry(w: dict, a: dict, default: str, now: float) -> dict:
    """One worktree of the snapshot: its work not on main, its plan, its agent; a marked slot (plans/LEAD) also
    `missing`, what its lead's branch lacks (lead_marker.missing), which alone decides whether it has work left."""
    path, slot = w["path"], Path(w["path"]).name
    plan_file = Path(path) / "plans/CURRENT_PLAN"
    since = (a.get("since") or 0) / 1000
    lead = lead_of(path)
    return {
        "slot": slot, "path": path, "branch": w.get("branch"), "ahead": unmerged(path, default),
        "plan": plan_file.read_text().strip() if plan_file.exists() else "", "lead": lead,
        **({"missing": lead_marker.missing(path, slot, lead, f"origin/{default}")} if lead else {}),
        "agent_state": a.get("state"), "pane": a.get("pane_id"),
        "agent_idle_seconds": int(now - since) if since and a.get("state") not in BUSY else 0,
        "context_percent": a.get("context_percent"),
        "agent_tasks": sum(1 for t in a.get("background_tasks") or [] if t.get("type") in WORKING_TASKS),
    }


def snapshot(repo: str, hours: float, fetch: bool = True) -> dict:
    now = time.time()
    main = main_checkout(repo)
    default = (run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], main).strip()
               .removeprefix("origin/") or "main")
    if fetch:
        run(["git", "fetch", "--quiet", "origin", default], main)
    q_raw = run_json(["hal2-cli-git", "worktree", "queue", "--json"], main) or {}
    q = q_raw.get("queue", [])
    agents_raw = run_json(["hal2-cli-agents", "list", "--json"]) or {}
    agents = agents_raw.get("list", []) if isinstance(agents_raw, dict) else agents_raw
    by_checkout = agents_by_checkout(agents)
    unfinished = 0
    ci = mtm_ci.ci_mode(run, main, default)
    if ci:
        recent, tests = mtm_ci.landings(run_json, main, now - hours * 3600), {}
        unfinished = mtm_ci.unfinished(run_json, main)
    else:
        l_raw = run_json(["hal2-cli-git", "worktree", "landings", "--limit", "100", "--json"], main) or {}
        recent, tests = landings_summary(l_raw.get("landings", []), now - hours * 3600)
    queue = []
    for t in q:
        queue.append({
            "slot": t.get("slot"), "state": t.get("state"), "seq": t.get("seq"),
            "enqueued": t.get("enqueued"), "landing": t.get("landing"), "hold": t.get("hold"),
            "process_alive": pid_alive(t.get("pid")), "parked": bool(t.get("parked_until")),
            "reserved": t.get("reserved"), "awaiting_slot": bool(t.get("reserved")) and not t.get("pid"),
            "active_seconds": int(now - (landing_start(t.get("landing")) or now)),
        })
    own = run(["git", "rev-parse", "--show-toplevel"], repo).strip()
    # hal2's own checkouts (.deliver, .bench) and the farmer's slot are left out
    listed = [w for w in worktrees(main) if not Path(w["path"]).name.startswith(".") and w["path"] != own]
    if fetch:
        fetch_leads(main, [w["path"] for w in listed])
    wts = [worktree_entry(w, by_checkout.get(w["path"], {}), default, now) for w in listed]
    load1 = os.getloadavg()[0]
    cores = os.cpu_count() or 1
    pause_file = state_dir(main) / "paused.json"
    snap = {
        "now": now, "repo": main, "default": default, "ci": ci, "runs_unfinished": unfinished, "queue": queue, "worktrees": wts,
        "landings": recent, "tests": tests,
        "load": {"load1": load1, "cores": cores, "per_core": round(load1 / cores, 2)},
        "paused": json.loads(pause_file.read_text()) if pause_file.exists() else None,
        "priority": json.loads(prio.read_text()) if (prio := state_dir(main) / "priority.json").exists() else None,
        "queue_order": q_raw.get("priority"),
    }
    snap["findings"] = findings(snap)
    return snap


def state_dir(main: str) -> Path:
    """The farmer's state folder: roles/farmer/ of its slot, or FARMER_DIR's (roles.state_dir)."""
    return roles.state_dir(main, DATA)


LOG_FIELDS = ("kind", "slot", "what", "note")


def entries(path: Path) -> list[dict]:
    """The log's entries, tolerant of old or hand-written ones: an unreadable line or one without `at` is skipped,
    a missing kind, slot, what or note reads as "" (plan 0137: one entry without `note` crashed every tick)."""
    out = []
    for line in path.read_text().splitlines() if path.exists() else []:
        try:
            e = json.loads(line)
            dt.datetime.fromisoformat(e["at"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
        out.append({**{k: "" for k in LOG_FIELDS}, **{k: v for k, v in e.items() if v is not None}})
    return out


def log(main: str, entry: dict) -> None:
    entry = {"at": dt.datetime.now().isoformat(timespec="seconds"), **{k: "" for k in LOG_FIELDS}, **entry}
    with (state_dir(main) / "log.jsonl").open("a") as f:
        f.write(json.dumps(entry) + "\n")


def priority(main: str, slots: list[str], note: str = "", clear: bool = False, done: str = "") -> int:
    """The user's landing order: hal2 orders the queue (`worktree queue order`), priority.json keeps the request.

    `done` only takes a landed slot off priority.json: hal2 drops it from its own order when its turn ends."""
    f = state_dir(main) / "priority.json"
    if done:
        kept = json.loads(f.read_text()) if f.exists() else {"slots": [], "note": ""}
        kept["slots"] = [s for s in kept["slots"] if s != done]
        if kept["slots"]:
            f.write_text(json.dumps(kept))
        else:
            f.unlink(missing_ok=True)
        log(main, {"kind": "priority", "slot": done, "what": "done", "note": ""})
    else:
        args = ["hal2-cli-git", "worktree", "queue", "order", *(["--clear"] if clear else slots), "--json"]
        try:
            r = subprocess.run(args, cwd=main, capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            print(f"scan.py: {' '.join(args)}: {e}", file=sys.stderr)
            return 1
        if r.returncode != 0:
            print((r.stderr or r.stdout).strip() or f"{' '.join(args)} failed", file=sys.stderr)
            return 1
        order = (json.loads(r.stdout).get("priority") or {}).get("slots", []) if r.stdout.strip() else []
        if clear or not order:
            f.unlink(missing_ok=True)
        else:
            f.write_text(json.dumps({"slots": order, "note": note}))
        log(main, {"kind": "priority", "slot": ",".join(order or slots), "what": "cleared" if clear else "set",
                   "note": note})
    print(f.read_text() if f.exists() else "no priority")
    return 0


def summary_dir(main: str) -> Path:
    """The round summaries: summaries/ in the state folder (ignored with the rest of roles/farmer/)."""
    d = state_dir(main) / "summaries"
    d.mkdir(parents=True, exist_ok=True)
    return d


def actions_since(main: str, since: float) -> list[dict]:
    return [e for e in entries(state_dir(main) / "log.jsonl") if dt.datetime.fromisoformat(e["at"]).timestamp() >= since]


def render_summary(snap: dict, actions: list[dict], landings: list[dict], notes: str, lead: str = "") -> str:
    at = dt.datetime.fromtimestamp(snap["now"]).strftime("%Y-%m-%d %H:%M")
    head = snap["queue"][0] if snap["queue"] else None
    lines = [f"# farmer {at}", ""]
    lines.append(f"Load {snap['load']['load1']:.1f} on {snap['load']['cores']} cores. "
                 + (f"Queue head: {head['slot']} {head['state']}." if head else "Queue empty.")
                 + (f" Paused: {snap['paused'].get('note', '')}." if snap.get("paused") else ""))
    if notes:
        lines += ["", notes.strip()]
    if lead:
        lines += ["", "## Development lead", "", lead.strip()]
    lines += ["", "## Landings since the last summary", ""]
    lines += [f"- {l['slot']} {l['outcome']}" + (f": {l['task']}" if l["task"] else "")
              + (f" ({', '.join(l['tests'])})" if l["tests"] else "")
              + (f" {l['url']}" if l.get("url") else "") for l in landings] or ["- none"]
    lines += ["", "## Queue", ""]
    lines += [f"{i}. {t['slot']} {t['state']}" + (f" ({(t.get('hold') or {}).get('reason')}, attempt "
              f"{(t.get('hold') or {}).get('attempts')})" if t.get("hold") else "")
              for i, t in enumerate(snap["queue"])] or ["empty"]
    lines += ["", "## Findings", ""]
    lines += [f"- {f['kind']} {f['slot']}: {f['why']}" for f in snap["findings"]] or ["- none"]
    lines += ["", "## Actions", ""]
    lines += [f"- {e['at'][11:16]} {e['kind']} {e['slot']}: {e['what']}" + (f" ({e['note']})" if e.get("note") else "")
              for e in ({**{k: "" for k in LOG_FIELDS}, **a} for a in actions)] or ["- none"]
    lines += ["", "## Worktrees", "", "| slot | not on main | agent | plan |", "|---|---|---|---|"]
    lines += [f"| {w['slot']} | {w['ahead']} | {w.get('agent_state') or '-'} | {w.get('plan') or '-'} |"
              for w in snap["worktrees"] if w["ahead"] or w.get("plan")]
    return "\n".join(lines) + "\n"


def write_summary(main: str, snap: dict, notes: str, lead: str = "") -> Path:
    d = summary_dir(main)
    latest = d / "latest.md"
    since = latest.stat().st_mtime if latest.exists() else snap["now"] - 3600
    landings = [l for l in snap["landings"] if (l.get("started") or landing_start(l["id"]) or 0) >= since]
    text = render_summary(snap, actions_since(main, since), landings, notes, lead)
    stamp = dt.datetime.fromtimestamp(snap["now"])
    day = d / stamp.strftime("%Y-%m-%d")
    day.mkdir(exist_ok=True)
    path = day / f"{stamp.strftime('%H%M')}.md"
    path.write_text(text)
    latest.write_text(text)
    return path


def print_text(snap: dict) -> None:
    head = snap["queue"][0] if snap["queue"] else None
    print(f"repo {snap['repo']}  load {snap['load']['load1']:.1f}/{snap['load']['cores']} cores"
          f"  queue {len(snap['queue'])}" + (f"  head {head['slot']} {head['state']}" if head else ""))
    for f in snap["findings"]:
        print(f"- {f['kind']:16} {f['slot']:10} {f['why']}")
    if not snap["findings"]:
        print("no findings")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--repo", default=os.getcwd())
    s.add_argument("--hours", type=float, default=24)
    s.add_argument("--json", action="store_true")
    r = sub.add_parser("record")
    r.add_argument("kind")
    r.add_argument("slot")
    r.add_argument("what")
    r.add_argument("--note", default="")
    r.add_argument("--repo", default=os.getcwd())
    for name in ("pause", "resume"):
        x = sub.add_parser(name)
        x.add_argument("--repo", default=os.getcwd())
        x.add_argument("--note", default="")
    pr = sub.add_parser("priority")
    pr.add_argument("slots", nargs="*")
    pr.add_argument("--note", default="")
    pr.add_argument("--clear", action="store_true")
    pr.add_argument("--done", default="", metavar="SLOT", help="take a landed slot off priority.json")
    pr.add_argument("--repo", default=os.getcwd())
    sm = sub.add_parser("summary")
    sm.add_argument("--repo", default=os.getcwd())
    sm.add_argument("--hours", type=float, default=24)
    sm.add_argument("--notes", default="")
    sm.add_argument("--lead", default="", help="the development lead's part of the round")
    st = sub.add_parser("status")
    st.add_argument("--repo", default=os.getcwd())
    st.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    missing = [t for t in TOOLS if not shutil.which(t)]
    if missing:
        print(f"scan.py: missing {', '.join(missing)}; run install-prerequisites.sh", file=sys.stderr)
        return 2
    main_dir = main_checkout(args.repo)
    if args.cmd == "scan":
        snap = snapshot(args.repo, args.hours)
        (state_dir(main_dir) / "last-scan.json").write_text(json.dumps(snap, indent=1))
        print(json.dumps(snap, indent=1) if args.json else "", end="\n" if args.json else "")
        if not args.json:
            print_text(snap)
    elif args.cmd == "priority":
        if not (args.slots or args.clear or args.done) or (args.clear and args.slots):
            p.error("priority takes slots, --clear or --done <slot>")
        return priority(main_dir, args.slots, args.note, args.clear, args.done)
    elif args.cmd == "summary":
        snap = snapshot(args.repo, args.hours)
        (state_dir(main_dir) / "last-scan.json").write_text(json.dumps(snap, indent=1))
        print(write_summary(main_dir, snap, args.notes, args.lead))
    elif args.cmd == "record":
        log(main_dir, {"kind": args.kind, "slot": args.slot, "what": args.what, "note": args.note})
    elif args.cmd == "pause":
        (state_dir(main_dir) / "paused.json").write_text(
            json.dumps({"since": dt.datetime.now().isoformat(timespec="seconds"), "note": args.note}))
        log(main_dir, {"kind": "pause", "slot": "", "what": "paused", "note": args.note})
    elif args.cmd == "resume":
        (state_dir(main_dir) / "paused.json").unlink(missing_ok=True)
        log(main_dir, {"kind": "pause", "slot": "", "what": "resumed", "note": args.note})
    elif args.cmd == "status":
        d = state_dir(main_dir)
        cutoff = dt.datetime.now() - dt.timedelta(hours=6)
        recent = [e for e in entries(d / "log.jsonl") if dt.datetime.fromisoformat(e["at"]) >= cutoff]
        last = d / "last-scan.json"
        status = {
            "priority": json.loads((d / "priority.json").read_text()) if (d / "priority.json").exists() else None,
            "paused": json.loads((d / "paused.json").read_text()) if (d / "paused.json").exists() else None,
            "last_scan_age_s": int(time.time() - last.stat().st_mtime) if last.exists() else None,
            "actions_6h": recent,
        }
        print(json.dumps(status, indent=1) if args.json else
              f"paused: {status['paused']}\nlast scan: {status['last_scan_age_s']} s ago\n"
              + "\n".join(f"{e['at']} {e['kind']} {e['slot']} {e['what']} {e['note']}" for e in recent))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
