#!/usr/bin/env python3
"""Find the agent sessions of a project that stopped abnormally, for the sanity-watch skill.

  scan.py scan [--project <dir>] [--hours 24] [--all] [--json]
      the incidents since the last scan (--all: also the handled ones): stopped sessions
      classified F1-F14 (research 0015 in hal2; F13: plan 0139; F14: skills plan 0016) with
      evidence and an action (resume|restore|judge|wait|escalate|handover|count); writes the heartbeat
  scan.py record <incident-id> <action> [--session <id>] [--note <text>]
      mark an incident handled: appended to log.jsonl; a `resume` counts against the
      session's resume budget (2 per 6 h)
  scan.py status [--json]
      heartbeat age, handled incidents, resumes of the last 6 h, open cases

Reads hal2's state (hal2-cli-agents list --json with each session's `background_tasks`, the
day chronicle, the hook records, terminal orphans), Claude Code's transcripts (a subagent's:
<session>/subagents/agent-<id>.jsonl) and the plan skill's plan.py; writes only its own state
under ~/skills/sanity-watch/. A session that rests while a background task of its own lives (a
shell, a monitor, a subagent whose transcript moved in the last 20 min) waits, it has not
stopped (a plan's coordinator waiting on its step's subagent); one whose subagents are all dead
is F14. Exit 0 on success, 2 when a tool is missing.
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

HOME = Path.home()
STATE_ROOT = Path(os.environ.get("HAL2_STATE_DIR", HOME / ".local/state/hal2"))
CHRONICLE = STATE_ROOT / "agents-chronicle"
RECORDS = STATE_ROOT / "agents"
PROJECTS = Path(os.environ.get("CLAUDE_PROJECTS_DIR", HOME / ".claude/projects"))
DATA = Path(os.environ.get("SANITY_WATCH_DIR", HOME / "skills/sanity-watch"))
PLAN_PY = Path(__file__).resolve().parents[2] / "plan" / "scripts" / "plan.py"

MINUTE = 60_000
RESUME_BUDGET = 2  # resumes per session ...
RESUME_WINDOW = 6 * 60 * MINUTE  # ... per 6 hours
EARLY_END_AFTER = 10 * MINUTE
HANG_AFTER = 20 * MINUTE
HANG_AFTER_IN_TOOL = 60 * MINUTE
BLOCKED_TOO_LONG = 30 * MINUTE
CONTINUE_BLOCKED_AFTER = 3 * MINUTE  # hal2's draft_alert
SUBAGENT_DEAD_AFTER = 20 * MINUTE  # a background subagent whose transcript is this quiet is dead
RESTING = ("done", "sleeping", "idle")
AGENT_TOOLS = ("Agent", "Task")  # the tool that runs a subagent (Task: its older name)
AUTOCLEAR_BUSY = {"interrupting", "waiting", "requesting", "clearing", "continuing"}

# What the watcher does per class (research 0015, "Failure taxonomy").
ACTIONS = {
    "F1": "resume", "F2": "resume", "F3": "resume", "F4": "wait", "F5": "escalate",
    "F6": "judge", "F7": "judge", "F8": "restore", "F9": "escalate", "F10": "escalate",
    "F11": "handover", "F12": "judge", "F13": "judge", "F14": "judge",
}
NAMES = {
    "F1": "transient API error", "F2": "network down", "F3": "Mac slept mid-response",
    "F4": "rate or usage limit", "F5": "billing or auth", "F6": "turn ended early in a plan",
    "F7": "hang", "F8": "process gone", "F9": "waiting for the user too long",
    "F10": "tool failure loop", "F11": "autoclear failure", "F12": "unknown stop",
    "F13": "continue blocked", "F14": "subagent dead under an idle parent",
}


def now_ms() -> int:
    return int(time.time() * 1000)


def classify_api_error(error: str, text: str) -> str:
    """The failure class of a transcript's API error entry (`error` field and message text)."""
    error, low = (error or "").lower(), (text or "").lower()
    if "sleep" in low:
        return "F3"
    if any(k in low for k in ("enotfound", "can't reach", "cannot reach", "econnrefused", "offline", "dns")):
        return "F2"
    if any(k in error for k in ("billing", "authentication", "permission")) or any(
            k in low for k in ("credit balance", "authentication", "account", "invalid api key")):
        return "F5"
    if "rate_limit" in error or any(k in low for k in ("usage limit", "session limit", "rate limit", "resets")):
        return "F4"
    if any(k in error for k in ("server_error", "overloaded", "api_error", "timeout")) or any(
            k in low for k in ("connection lost", "connection closed", "overloaded", "529", "500", "502",
                               "503", "timed out", "timeout")):
        return "F1"
    return "F12"


def _text(message) -> str:
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _ms(timestamp: str) -> int:
    try:
        return int(dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp() * 1000)
    except (AttributeError, ValueError):
        return 0


def transcript_tail(lines) -> dict:
    """What the end of a transcript says: the last API error, the last real user prompt,
    the last assistant text and whether a question is pending. `lines` are JSONL strings."""
    tail = {"api_error": None, "last_prompt_ms": 0, "last_prompt": "", "last_assistant": "",
            "question_pending": False}
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("isSidechain"):
            continue
        message, ts = row.get("message"), _ms(row.get("timestamp", ""))
        if row.get("type") == "assistant" and isinstance(message, dict):
            if row.get("isApiErrorMessage") is True:
                tail["api_error"] = {"error": row.get("error") or "", "status": row.get("apiErrorStatus"),
                                     "text": _text(message)[:300], "ms": ts}
                continue
            text = _text(message)
            if text.strip():
                tail["last_assistant"] = text.strip()[-600:]
            uses = [b for b in message.get("content") or [] if isinstance(b, dict) and b.get("type") == "tool_use"]
            tail["question_pending"] = any(b.get("name") == "AskUserQuestion" for b in uses)
        elif row.get("type") == "user" and isinstance(message, dict) and not row.get("isMeta"):
            content = message.get("content")
            # a typed prompt or a slash command (`<command-name>/handoff</command-name>`); not the
            # caveats, command output and reminders Claude Code records as user rows
            if isinstance(content, str) and content.strip() and (
                    not content.startswith("<") or "<command-name>" in content):
                tail["last_prompt_ms"], tail["last_prompt"] = ts, content.strip()[:200]
                tail["question_pending"] = False
    return tail


def transcript_path(session: str) -> Path | None:
    found = sorted(PROJECTS.glob(f"*/{session}.jsonl"))
    return found[0] if found else None


def read_tail(session: str, lines: int = 400) -> dict:
    path = transcript_path(session)
    if not path:
        return transcript_tail([])
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - 2_000_000))
        rows = f.read().decode("utf-8", "replace").splitlines()[-lines:]
    result = transcript_tail(rows)
    result["transcript"] = str(path)
    return result


def subagent_moved(session: str, task: str | None = None) -> int | None:
    """When the transcript of the session's subagent `task` (any subagent's when None) last changed, in ms;
    None when there is none."""
    name = f"agent-{task}.jsonl" if task else "agent-*.jsonl"
    times = [p.stat().st_mtime for p in PROJECTS.glob(f"*/{session}/subagents/{name}") if p.is_file()]
    return int(max(times) * 1000) if times else None


def background(agent: dict, at: int, moved=subagent_moved) -> tuple[list[dict], list[dict]]:
    """The session's background tasks split into live and dead ones. hal2 lists a shell or monitor while it
    runs; a subagent stays listed after it died, so it counts as dead once its transcript has been quiet
    `SUBAGENT_DEAD_AFTER` (a subagent without a transcript counts as live)."""
    live, dead = [], []
    for task in agent.get("background_tasks") or []:
        if not isinstance(task, dict):
            continue
        last = moved(agent.get("session_id") or "", task.get("id")) if task.get("type") == "subagent" else None
        if last is not None and at - last >= SUBAGENT_DEAD_AFTER:
            dead.append({**task, "quiet_minutes": (at - last) // MINUTE})
        else:
            live.append(task)
    return live, dead


def run_json(*argv, default=None):
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return default
    if out.returncode != 0:
        return default
    try:
        return json.loads(out.stdout)
    except ValueError:
        return default


_projects: dict[str, str] = {}


def project_of(cwd: str) -> str:
    """The main checkout of the repository `cwd` is in ('' when none)."""
    if cwd not in _projects:
        common = subprocess.run(["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True).stdout.strip() if Path(cwd).is_dir() else ""
        _projects[cwd] = str(Path(common).parent) if common else ""
    return _projects[cwd]


def chronicle_events(since_ms: int) -> list[dict]:
    events = []
    day = dt.date.fromtimestamp(since_ms / 1000)
    while day <= dt.date.today():
        path = CHRONICLE / f"{day.isoformat()}.jsonl"
        if path.is_file():
            for line in path.read_text().splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("ts", 0) >= since_ms:
                    events.append(event)
        day += dt.timedelta(days=1)
    return events


def record_of(session: str) -> dict:
    try:
        return json.loads((RECORDS / f"{session}.json").read_text())
    except (OSError, ValueError):
        return {}


def load_state() -> dict:
    try:
        return json.loads((DATA / "state.json").read_text())
    except (OSError, ValueError):
        return {"handled": {}, "resumes": {}, "last_scan": 0}


def save_state(state: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = DATA / "state.json.tmp"
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(DATA / "state.json")


def resumes_left(state: dict, session: str, at: int) -> int:
    recent = [t for t in state.get("resumes", {}).get(session, []) if at - t < RESUME_WINDOW]
    return RESUME_BUDGET - len(recent)


def incident(cls: str, session: str, at: int, agent: dict | None, evidence: dict, action: str = "",
             reason: str = "") -> dict:
    agent = agent or {}
    return {
        "id": f"{cls}:{session}:{at}", "class": cls, "name": NAMES[cls], "session": session, "at": at,
        "pane": agent.get("pane_id"), "slot": agent.get("slot"), "checkout": agent.get("checkout"),
        "plan": agent.get("plan"), "state": agent.get("state"), "action": action or ACTIONS[cls],
        "reason": reason, "evidence": evidence,
    }


def find_incidents(project: str, agents: list[dict], events: list[dict], orphans: list[dict], state: dict,
                   at: int, tails=read_tail, plan_of=None, moved=subagent_moved) -> list[dict]:
    """Every incident of `project`. Pure apart from `tails`, `plan_of` and `moved` (injected for tests)."""
    plan_of = plan_of or current_plan
    mine = [a for a in agents if a.get("project") == project]
    by_session = {a.get("session_id"): a for a in agents if a.get("session_id")}
    found: list[dict] = []

    # F1-F5, F12: turns that ended in an API error (the chronicle's `failed` lines).
    failed: dict[str, dict] = {}
    for event in events:
        if event.get("state") == "failed":
            failed[event["session"]] = event
    for session, event in failed.items():
        agent = by_session.get(session)
        if (agent or {}).get("project", project_of(event.get("cwd", ""))) != project:
            continue
        tail = tails(session)
        error = tail.get("api_error") or {}
        cls = classify_api_error(error.get("error", ""), error.get("text", "")) if error else "F12"
        evidence = {"chronicle": event, "api_error": error, "transcript": tail.get("transcript")}
        later = [e for e in events if e["session"] == session and e["ts"] > event["ts"] and e["state"] != "failed"]
        if later or not agent or agent.get("state") != "failed":
            who = "user" if tail.get("last_prompt_ms", 0) > event["ts"] else "someone"
            found.append(incident(cls, session, event["ts"], agent, evidence, "count",
                                  f"resolved by {who}: the session went on" if agent or later else
                                  "the session is gone"))
            continue
        action, reason = ACTIONS[cls], ""
        if action == "resume" and resumes_left(state, session, at) <= 0:
            action, reason = "escalate", "resume budget spent (2 per 6 h)"
        found.append(incident(cls, session, event["ts"], agent, evidence, action, reason))

    for agent in mine:
        session, since = agent.get("session_id") or "", agent.get("since") or at
        auto = (agent.get("autoclear") or {}).get("state")
        # F11: a failed clear-and-continue job belongs to fix-autoclear.
        if auto == "failed":
            found.append(incident("F11", session, (agent["autoclear"].get("updated_at") or since), agent,
                                  {"autoclear": agent["autoclear"]}))
            continue
        if auto in AUTOCLEAR_BUSY:
            # F13: a clear-and-continue job waits on a draft in the input box too long (hal2 plan 0139).
            job = agent["autoclear"]
            blocked = job.get("waiting_since")
            if auto == "waiting" and job.get("waiting_on") and blocked and at - blocked >= CONTINUE_BLOCKED_AFTER:
                found.append(incident("F13", session, blocked, agent, {
                    "autoclear": job, "waiting_on": job["waiting_on"], "waiting_minutes": (at - blocked) // MINUTE}))
            continue
        state_ = agent.get("state") or ""
        live, dead = background(agent, at, moved) if state_ in RESTING else ([], [])
        if live:
            continue  # it waits on its own background work, e.g. a coordinator on its step's subagent (D14)
        # F14: resting while every background subagent it waits on is dead: nothing will wake it.
        if dead and at - since >= EARLY_END_AFTER:
            tail = tails(session)
            found.append(incident("F14", session, since, agent, {
                "subagents": dead, "last_assistant": tail.get("last_assistant"),
                "transcript": tail.get("transcript")}))
        # F6: the turn ended while the checkout's plan still has a step to run before its landing.
        elif state_ in RESTING and at - since >= EARLY_END_AFTER and agent.get("checkout"):
            plan = plan_of(agent["checkout"])
            if plan and plan.get("next") and plan.get("land") == "wait":
                tail = tails(session)
                if not tail.get("question_pending") and tail.get("last_prompt_ms", 0) < since:
                    step = plan["next"]
                    found.append(incident("F6", session, since, agent, {
                        "plan": plan.get("slug"), "next_step": f"{step.get('number')}: {step.get('step')}",
                        "last_assistant": tail.get("last_assistant"), "transcript": tail.get("transcript")}))
        # F7: working, but the hook record has not moved for too long.
        elif state_ == "working" and agent.get("source") == "hook":
            record = record_of(session)
            last = record.get("ts") or at
            in_tool = record.get("event") == "PreToolUse"
            if in_tool and record.get("detail") in AGENT_TOOLS:
                last = max(last, moved(session, None) or 0)  # a subagent at work: its transcript moves
            quiet = at - last
            if quiet >= (HANG_AFTER_IN_TOOL if in_tool else HANG_AFTER):
                found.append(incident("F7", session, record.get("ts") or since, agent, {
                    "record": record, "quiet_minutes": quiet // MINUTE}))
        # F9: a dialog waiting for the user for too long.
        elif state_.startswith("blocked") and at - since >= BLOCKED_TOO_LONG:
            found.append(incident("F9", session, since, agent, {"waiting_minutes": (at - since) // MINUTE}))

    # F8: terminal hosts lost with their agent (reboot, crash).
    for orphan in orphans:
        where = orphan.get("worktree") or orphan.get("cwd") or ""
        if where and project_of(where) == project and not orphan.get("gone"):
            found.append(incident("F8", orphan.get("id", "?"), orphan.get("created") or at, None,
                                  {"orphan": orphan}))
    return found


def current_plan(checkout: str) -> dict | None:
    if not PLAN_PY.is_file():
        return None
    return run_json(sys.executable, str(PLAN_PY), "--root", checkout, "current")


def default_project() -> str:
    return project_of(os.getcwd()) or os.getcwd()


def cmd_scan(args) -> int:
    if not shutil.which("hal2-cli-agents"):
        print("hal2-cli-agents is missing: install hal2 (cargo install --path apps/hal2-cli-agents)",
              file=sys.stderr)
        return 2
    project = str(Path(args.project).expanduser().resolve()) if args.project else default_project()
    state, at = load_state(), now_ms()
    since = at - int(args.hours * 60 * MINUTE)
    agents = run_json("hal2-cli-agents", "list", "--json", default=[]) or []
    orphans = run_json("hal2-cli-agents", "terminal", "orphans", "--json", default=[]) or []
    me = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    agents = [a for a in agents if not me or a.get("session_id") != me]  # never the watcher itself
    events = [e for e in chronicle_events(since) if not me or e.get("session") != me]
    found = find_incidents(project, agents, events, orphans, state, at)
    if not args.all:
        found = [i for i in found if i["id"] not in state.get("handled", {})]
    state["last_scan"] = at
    save_state(state)
    (DATA / "heartbeat").write_text(f"{at}\n")
    result = {"project": project, "at": at, "hours": args.hours, "agents": len(
        [a for a in agents if a.get("project") == project]), "incidents": found}
    if args.json:
        print(json.dumps(result, indent=1))
    else:
        print(f"{project}: {result['agents']} agents, {len(found)} incident(s)")
        for i in found:
            print(f"  {i['class']:<3} {i['action']:<9} slot {i['slot'] or '-':<4} {i['pane'] or '-':<16} "
                  f"{i['name']}{' — ' + i['reason'] if i['reason'] else ''}  [{i['id']}]")
    return 0


def cmd_record(args) -> int:
    state, at = load_state(), now_ms()
    session = args.session or (args.incident.split(":")[1] if args.incident.count(":") >= 2 else "")
    state.setdefault("handled", {})[args.incident] = {"action": args.action, "at": at, "note": args.note}
    if args.action == "resume" and session:
        state.setdefault("resumes", {}).setdefault(session, []).append(at)
    save_state(state)
    with (DATA / "log.jsonl").open("a") as log:
        log.write(json.dumps({"ts": at, "incident": args.incident, "action": args.action, "session": session,
                              "note": args.note}) + "\n")
    print(json.dumps({"recorded": args.incident, "action": args.action,
                      "resumes_left": resumes_left(state, session, at) if session else None}))
    return 0


def cmd_status(args) -> int:
    state, at = load_state(), now_ms()
    try:
        beat = int((DATA / "heartbeat").read_text().strip())
    except (OSError, ValueError):
        beat = 0
    cases = Path(__file__).resolve().parents[1] / "cases.md"
    result = {
        "heartbeat_minutes": (at - beat) // MINUTE if beat else None,
        "handled": len(state.get("handled", {})),
        "resumes_6h": {s: len([t for t in ts if at - t < RESUME_WINDOW]) for s, ts in state.get("resumes", {}).items()
                       if any(at - t < RESUME_WINDOW for t in ts)},
        "cases": len(re.findall(r"^## ", cases.read_text(), re.M)) if cases.is_file() else None,
    }
    print(json.dumps(result, indent=1) if args.json else
          f"heartbeat {result['heartbeat_minutes']} min ago, {result['handled']} handled, "
          f"resumes in 6 h: {result['resumes_6h'] or 'none'}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan")
    scan.add_argument("--project")
    scan.add_argument("--hours", type=float, default=24)
    scan.add_argument("--all", action="store_true")
    scan.add_argument("--json", action="store_true")
    record = sub.add_parser("record")
    record.add_argument("incident")
    record.add_argument("action")
    record.add_argument("--session")
    record.add_argument("--note", default="")
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    return {"scan": cmd_scan, "record": cmd_record, "status": cmd_status}[args.command](args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
