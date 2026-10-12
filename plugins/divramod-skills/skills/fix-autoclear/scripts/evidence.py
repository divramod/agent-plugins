#!/usr/bin/env python3
"""Collect what hal2's autoclear left behind, for the fix-autoclear skill.

  evidence.py show [--worktree <NN> [--repo <name>]] [--pane %46] [--session <id>] [--hours 3]
      one incident, named `<repo> wt <NN>`: the pane's screen (captured here,
      read-only: no screenshot needed), its job record and log, the guard
      markers of its sessions, each session's transcript tail (tools, hook
      denials, the typed requests), the sweep's lines, the settings and binary
  evidence.py capture --worktree <NN> [--repo <name>] --out <dir> [--hours 3]
      the same incident as files, to turn into hal2 test fixtures: screen.txt,
      agent.json, job.json, job.log, marker-<session>.json, transcript-<session>.txt,
      guard.log, sweep.log (the pane's lines), README.md (what each file is)
  evidence.py doctor [--hours 24] [--json]
      every pane's failed or stuck autoclear of the last hours (nobody reported), and
      every job blocked over 3 min by text in the input box hal2 did not type (`blocked`);
      jobs that failed for a reason hal2 itself does not report (the session or agent ended:
      `QUIET`) are listed apart, never as problems
  evidence.py selfcheck [--repo <hal2 checkout>]
      whether the insider facts in SKILL.md still match hal2's code

Exit 0 on success, 1 when selfcheck finds drift, 2 when a tool is missing.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
STATE = Path(os.environ.get("HAL2_STATE_ROOT", HOME / ".local/state/hal2"))
JOBS = STATE / "agents" / "autoclear"
API_LOG = HOME / "Library/Logs/hal2-api.log"
PROJECTS = HOME / ".claude/projects"
SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"
SRC = "code/rust/libs/hal2-agents/src"
BLOCKED_AFTER = 3 * 60  # hal2's draft_alert (plan 0139), seconds
# hal2's sweep.rs MAX_ATTEMPTS: its give-up always writes `attempts >= MAX_ATTEMPTS` with `gave_up` (selfcheck compares)
MAX_ATTEMPTS = 3
OFF_REARM = 100  # a rearm_percent no context reaches: hal2's cancel_marker writes at most max(percent, threshold) + 5
# The fail reasons hal2's report.rs keeps out of the skill-fix-autoclear shotfile: the session or its agent ended on its
# own, or the request never became a job. No autoclear failure (selfcheck compares with report.rs).
QUIET = {"agent-gone", "session-ended", "already-running", "invalid-request"}


def need(tool):
    if shutil.which(tool) is None:
        print(f"evidence.py: missing {tool}; run scripts/install-prerequisites.sh", file=sys.stderr)
        sys.exit(2)


def stamp(ms):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ms / 1000)) if ms else "-"


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def agents():
    need("hal2-cli-agents")
    out = subprocess.run(["hal2-cli-agents", "list", "--json"], capture_output=True, text=True)
    try:
        data = json.loads(out.stdout)
    except ValueError:
        return []
    return data if isinstance(data, list) else data.get("agents", [])


def markers():
    """Every guard marker, newest first."""
    found = [(p, read_json(p)) for p in JOBS.glob("*.guard")]
    found = [(p, m) for p, m in found if m]
    return sorted(found, key=lambda pm: pm[0].stat().st_mtime, reverse=True)


def pane_stem(pane):
    return pane.lstrip("%").removeprefix("t:")


def transcript(session):
    hits = list(PROJECTS.glob(f"*/{session}.jsonl"))
    return hits[0] if hits else None


def transcript_tail(path, entries=30):
    """The last tool calls, results, hook denials and typed prompts."""
    lines = []
    for raw in path.read_text(errors="replace").splitlines():
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        ts = (d.get("timestamp") or "")[11:19]
        att = d.get("attachment") or {}
        if att.get("type") == "hook_stopped_continuation":
            lines.append(f"{ts} HOOK-STOP {att.get('message', '')[:200]}")
        msg = d.get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            lines.append(f"{ts} {msg.get('role')} {content[:300]}")
            continue
        for block in content if isinstance(content, list) else []:
            kind = block.get("type")
            if kind == "tool_use":
                lines.append(f"{ts} TOOL {block['name']} {json.dumps(block.get('input'))[:500]}")
            elif kind == "tool_result":
                text = str(block.get("content"))
                if "hook" in text.lower() or block.get("is_error"):
                    lines.append(f"{ts} RESULT {text[:300]}")
            elif kind == "text" and msg.get("role") == "assistant":
                lines.append(f"{ts} SAID {block['text'][:200]}")
    return lines[-entries:]


def sweep_lines(pane, hours):
    if not API_LOG.exists():
        return [f"(no {API_LOG})"]
    since = time.time() - hours * 3600
    keep = []
    for line in API_LOG.read_text(errors="replace").splitlines():
        if "sweep" not in line:
            continue
        if pane and pane not in line and "acted on" not in line:
            continue
        m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)", line)
        if m and time.mktime(time.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S")) - time.timezone < since:
            continue
        keep.append(line)
    acted = [l for l in keep if "acted on" not in l or " 0 acted on" not in l]
    return acted[-15:] or keep[-3:]


def own_log(name, needles, hours, keep=40):
    """The lines of `<jobs>/<name>` (and its rotated `.1`) of the last hours
    that contain one of `needles` (all lines when `needles` is empty)."""
    since = time.time() - hours * 3600
    lines = []
    for path in (JOBS / f"{name}.1", JOBS / name):
        if not path.exists():
            continue
        for line in path.read_text(errors="replace").splitlines():
            m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", line)
            if m and time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")) < since:
                continue
            if not needles or any(n and n in line for n in needles):
                lines.append(line)
    return lines[-keep:] or [f"(nothing in {JOBS / name} for {', '.join(filter(None, needles)) or 'the period'})"]


def label(project, slot):
    """An agent's name: `<repo> wt <NN>`, `<repo> main` (never a pane id)."""
    repo = Path(project).name if project else "?"
    return f"{repo} main" if slot == "main" else f"{repo} wt {slot}"


def agent_label(agent):
    if agent and agent.get("slot"):
        return label(agent.get("project"), agent["slot"])
    return f"the agent in pane {agent.get('pane_id')}" if agent else "an unknown agent"


def place(cwd):
    """(project, slot) of the checkout containing `cwd`, as hal2 derives it."""
    out = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--show-toplevel", "--git-common-dir"],
        cwd=cwd, capture_output=True, text=True,
    )
    lines = [l.strip() for l in out.stdout.splitlines() if l.strip()]
    if out.returncode != 0 or len(lines) < 2 or Path(lines[1]).name != ".git":
        return None
    checkout, project = Path(lines[0]), Path(lines[1]).parent
    return str(project), "main" if checkout == project else checkout.name


def session_label(session):
    """The label of `session` from its hook record's folder, else None."""
    record = read_json(STATE / "agents" / f"{session}.json") or {}
    where = place(record["cwd"]) if record.get("cwd") and Path(record["cwd"]).is_dir() else None
    return label(*where) if where else None


def current_repo():
    where = place(os.getcwd())
    return Path(where[0]).name if where else None


def find_agent(all_agents, worktree, repo=None):
    """The Claude agent of worktree slot `worktree` (`02`, `main`) of `repo`
    (a name; any repository when None). Several matches: None and the labels."""
    hits = [a for a in all_agents if a.get("kind") == "claude" and a.get("slot") == worktree
            and (repo is None or Path(a.get("project") or "").name == repo)]
    if len(hits) == 1:
        return hits[0], []
    return None, [agent_label(a) for a in hits]


def resolve_pane(args):
    """(pane, agent, problem) for show's arguments."""
    all_agents = agents()
    if args.pane:
        return args.pane, next((a for a in all_agents if a.get("pane_id") == args.pane), None), None
    if args.session:
        for a in all_agents:
            if a.get("session_id") == args.session:
                return a.get("pane_id"), a, None
        for _, m in markers():
            if m.get("session_id") == args.session and m.get("pane"):
                return m["pane"], None, None
    if args.worktree:
        repo = args.repo or current_repo()
        agent, many = find_agent(all_agents, args.worktree, repo)
        if agent is None and not many and args.repo is None:
            agent, many = find_agent(all_agents, args.worktree)
        if agent:
            return agent.get("pane_id"), agent, None
        if many:
            return None, None, f"several agents in worktree {args.worktree}: {', '.join(many)}; pass --repo"
        return None, None, f"no Claude agent in worktree {args.worktree}{' of ' + repo if repo else ''}"
    return None, None, "pass --worktree <NN> (or --pane, --session)"


def screen(pane):
    """The pane's screen as text, read-only (`hal2-cli-agents capture`: a
    tmux pane or a terminal host)."""
    out = subprocess.run(["hal2-cli-agents", "capture", pane], capture_output=True, text=True)
    return out.stdout.rstrip() if out.returncode == 0 else f"(no screen: {out.stderr.strip()})"


def show(args):
    need("hal2-cli-agents")
    pane, agent, problem = resolve_pane(args)
    name = agent_label(agent) if agent else "?"
    print(f"# autoclear evidence: {name} ({time.strftime('%Y-%m-%d %H:%M:%S')})\n")
    settings = subprocess.run(["hal2-cli-agents", "settings"], capture_output=True, text=True).stdout
    binary = shutil.which("hal2-cli-agents") or "hal2-cli-agents"
    print(f"## settings\n{settings.strip()}\nbinary {binary}, built {stamp(os.path.getmtime(binary) * 1000)}\n")
    if not pane:
        print(f"no agent found: {problem}")
        return
    if agent:
        keys = ["checkout", "slot", "plan", "state", "context_percent", "session_id", "autoclear"]
        print("## agent now\n" + json.dumps({k: agent.get(k) for k in keys}, indent=1) + "\n")
    print(f"## screen now (captured, read-only)\n```\n{screen(pane)}\n```\n")
    stem = pane_stem(pane)
    print(f"## job {JOBS / (stem + '.json')}\n{json.dumps(read_json(JOBS / (stem + '.json')), indent=1)}\n")
    log = JOBS / f"{stem}.log"
    if log.exists():
        print(f"## job log (last 40 lines)\n" + "\n".join(log.read_text().splitlines()[-40:]) + "\n")
    since = time.time() - args.hours * 3600
    sessions = []
    for path, m in markers():
        if m.get("pane") == pane and path.stat().st_mtime >= since:
            print(f"## marker {path.name}\n{json.dumps(m)}  (soft {stamp(m.get('soft_at'))}, hard {stamp(m.get('hard_at'))})\n")
            sessions.append(m["session_id"])
    if args.session and args.session not in sessions:
        sessions.insert(0, args.session)
    for session in sessions[:3]:
        path = transcript(session)
        if path:
            print(f"## transcript {path}\n" + "\n".join(transcript_tail(path)) + "\n")
    print("## guard decisions (guard.log)\n" + "\n".join(own_log("guard.log", [pane] + sessions, args.hours)) + "\n")
    print("## sweep rounds for the pane (sweep.log)\n" + "\n".join(own_log("sweep.log", [f" {pane} "], args.hours, 20)) + "\n")
    print("## sweep (hal2-api.log)\n" + "\n".join(sweep_lines(pane, args.hours)))


def capture(args):
    """Save one incident's evidence as files in `args.out` (see the docstring)."""
    need("hal2-cli-agents")
    pane, agent, problem = resolve_pane(args)
    if not pane:
        print(f"no agent found: {problem}", file=sys.stderr)
        return 1
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    name = agent_label(agent) if agent else f"the agent in pane {pane}"
    files = {}

    def save(file, text, what):
        (out / file).write_text(text if text.endswith("\n") else text + "\n")
        files[file] = what

    save("screen.txt", screen(pane), "the pane's screen as text (`hal2-cli-agents capture`): a scrape fixture")
    if agent:
        save("agent.json", json.dumps(agent, indent=1), "the agent as `hal2-cli-agents list --json` shows it")
    stem = pane_stem(pane)
    job = JOBS / f"{stem}.json"
    if job.exists():
        save("job.json", job.read_text(), "the job record: state, reason, message, sessions, times")
    log = JOBS / f"{stem}.log"
    if log.exists():
        save("job.log", "\n".join(log.read_text(errors="replace").splitlines()[-200:]), "the job log (last 200 lines)")
    since = time.time() - args.hours * 3600
    sessions = [agent["session_id"]] if agent and agent.get("session_id") else []
    record = read_json(job) or {}
    for key in ("old_session", "new_session"):
        if record.get(key) and record[key] not in sessions:
            sessions.append(record[key])
    for path, m in markers():
        if m.get("pane") == pane and path.stat().st_mtime >= since:
            save(f"marker-{m['session_id']}.json", json.dumps(m, indent=1), "a guard marker of the pane's sessions")
            if m["session_id"] not in sessions:
                sessions.append(m["session_id"])
    for session in sessions[:4]:
        path = transcript(session)
        if path:
            save(f"transcript-{session}.txt", "\n".join(transcript_tail(path, 60)),
                 "the session's transcript tail: tools, hook denials, typed prompts")
    save("guard.log", "\n".join(own_log("guard.log", [pane] + sessions, args.hours, 200)), "the guard's decisions")
    save("sweep.log", "\n".join(own_log("sweep.log", [f" {pane} "], args.hours, 100)), "the sweep's lines for the pane")
    readme = [f"# autoclear incident: {name}", "",
              f"Captured {time.strftime('%Y-%m-%d %H:%M:%S')} by `evidence.py capture` (pane {pane}).", ""]
    readme += [f"- `{file}`: {what}" for file, what in files.items()]
    readme += ["", "Turn `screen.txt` into `code/rust/libs/hal2-agents/src/fixtures/screens/<case>.txt` (or a test "
               "input) and replay the job's record and log in a regression test."]
    save("README.md", "\n".join(readme), "this file")
    print(f"{name}: {len(files)} files in {out}")
    return 0


def autoclear_off(marker=None, agent=None):
    """The user switched autoclear off for the session (skills plan 0011): never a failure, never acted on.
    hal2 has no explicit per-session switch yet (shot plugin-agents #31), so a marker counts as off when only a hand
    can have written it: `gave_up` without the sweep's attempts, or a `rearm_percent` no context reaches. An agent
    row with `autoclear_off: true` (what #31 adds to `hal2-cli-agents list --json`) is off too."""
    if (agent or {}).get("autoclear_off"):
        return True
    m = marker or {}
    return bool(m.get("gave_up") and m.get("attempts", 0) < MAX_ATTEMPTS) or (m.get("rearm_percent") or 0) >= OFF_REARM


def off_sessions(hours=None):
    """The sessions whose autoclear the user switched off (their markers, newest first; all when `hours` is None)."""
    since = 0 if hours is None else time.time() - hours * 3600
    return {m["session_id"]: m for p, m in markers() if p.stat().st_mtime >= since and autoclear_off(m)}


def doctor_items(hours, off=None, quiet=None):
    """Every pane's failed or stuck autoclear of the last `hours` (nobody reported), as dicts:
    {what: job|blocked|marker, pane, session, who, state, reason, message, attempts, gave_up, at}. A `blocked`
    job waits on a person's draft (hal2 plan 0139): no autoclear bug, sanity-watch's F13 owns it. A session whose
    autoclear the user switched off (`autoclear_off`) is left out; `off`, when a list, collects those sessions.
    A job failed for a `QUIET` reason is left out too (hal2 does not report it either); `quiet`, when a list,
    collects those jobs."""
    since = time.time() - hours * 3600
    by_pane = {a.get("pane_id"): a for a in agents()}
    switched = set(off_sessions()) | {a.get("session_id") for a in by_pane.values() if autoclear_off(agent=a)}
    out = []

    def who(pane, session):
        # The session's own folder first: the pane may host another agent now.
        agent = by_pane.get(pane)
        return (session and session_label(session)) or (
            agent_label(agent) if agent else f"the agent in pane {pane}")

    for record in sorted(JOBS.glob("*.json")):
        job = read_json(record)
        if not job or record.stat().st_mtime < since:
            continue
        if job.get("old_session") in switched:
            continue
        blocked = job.get("waiting_since")
        if job.get("state") == "waiting" and job.get("waiting_on") and blocked \
                and time.time() - blocked / 1000 >= BLOCKED_AFTER:
            out.append({"what": "blocked", "pane": job.get("pane"), "session": job.get("old_session"),
                        "who": who(job.get("pane"), job.get("old_session")), "state": "waiting",
                        "reason": "continue-blocked",
                        "message": f"a {job['waiting_on']} in the input box since {stamp(blocked)}",
                        "at": stamp(blocked)})
            continue
        if job.get("state") in ("failed",) or (
            job.get("state") in ("waiting", "requesting") and time.time() - record.stat().st_mtime > 1800
        ):
            item = {"what": "job", "pane": job.get("pane"), "session": job.get("old_session"),
                    "who": who(job.get("pane"), job.get("old_session")), "state": job.get("state"),
                    "reason": job.get("reason") or "", "message": job.get("message") or "",
                    "at": stamp(job.get("updated_at"))}
            if job.get("state") == "failed" and item["reason"] in QUIET:
                if quiet is not None:
                    quiet.append(item)
                continue
            out.append(item)
    for path, m in markers():
        if path.stat().st_mtime < since:
            continue
        if m["session_id"] in switched:
            if off is not None:
                off.append({"session": m["session_id"], "pane": m.get("pane"),
                            "who": who(m.get("pane"), m["session_id"])})
            continue
        if m.get("gave_up") or m.get("attempts", 0) >= 2:
            out.append({"what": "marker", "pane": m.get("pane"), "session": m["session_id"],
                        "who": who(m.get("pane"), m["session_id"]), "attempts": m.get("attempts", 0),
                        "gave_up": bool(m.get("gave_up"))})
    return out


def doctor(args):
    off, quiet = [], []
    items = doctor_items(args.hours, off, quiet)
    if args.json:
        print(json.dumps({"hours": args.hours, "problems": items, "off": off, "quiet": quiet}, indent=1))
        return
    for i in items:
        if i["what"] in ("job", "blocked"):
            print(f"{i['who']}: {i['state']} {i['reason']} {i['message']} ({i['at']})")
        else:
            print(f"{i['who']}: session {i['session']} attempts {i['attempts']}{' gave up' if i['gave_up'] else ''}")
    print(f"{len(items)} problem(s) in the last {args.hours} h"
          + (f"; autoclear off (skipped): {', '.join(o['who'] for o in off)}" if off else "")
          + ("; ended on their own (not reported by hal2): "
             + ", ".join(f"{q['who']} {q['reason']}" for q in quiet) if quiet else ""))


def selfcheck(args):
    """Every `path` and every `name` in SKILL.md's insider table must still exist."""
    repo = Path(args.repo).expanduser()
    skill = SKILL_MD.read_text()
    drift = []
    for rel in sorted(set(re.findall(r"`((?:code|\.hal|docs|research|plans)/[^`\s]+?)`", skill))):
        # plans/CURRENT_PLAN is per-checkout runtime state: absent while no plan runs.
        if rel == "plans/CURRENT_PLAN":
            continue
        if "<" not in rel and "*" not in rel and not (repo / rel).exists():
            drift.append(f"missing path {rel}")
    source = "\n".join(p.read_text() for p in (repo / SRC).glob("*.rs")) if (repo / SRC).exists() else ""
    block = skill.split("<!-- names -->")[1].split("<!-- /names -->")[0] if "<!-- names -->" in skill else ""
    for name in re.findall(r"`([a-z][a-z-]+)`", block):
        if f'"{name}"' not in source:
            drift.append(f"name `{name}` no longer in {SRC}")
    attempts = re.search(r"MAX_ATTEMPTS: u32 = (\d+)", source)
    if attempts and int(attempts.group(1)) != MAX_ATTEMPTS:
        drift.append(f"MAX_ATTEMPTS is {attempts.group(1)} in {SRC}/sweep.rs, evidence.py assumes {MAX_ATTEMPTS}")
    report = repo / SRC / "report.rs"
    reported = report.read_text() if report.exists() else ""
    for name in sorted(QUIET):
        variant = "".join(part.capitalize() for part in name.split("-"))
        if f"FailReason::{variant}" not in reported:
            drift.append(f"`{name}` is in evidence.py's QUIET, but {SRC}/report.rs no longer names FailReason::{variant}")
    for fact in re.findall(r"`(REARM_POINTS|MAX_ATTEMPTS|DEFAULT_PROMPT|HANDOFF_PROGRAMS|HANDOFF_SCRIPTS|RETRY_BACKOFF|CHECK)`", skill):
        if fact not in source:
            drift.append(f"constant {fact} no longer in {SRC}")
    hooks = (HOME / ".claude/settings.json").read_text() if (HOME / ".claude/settings.json").exists() else ""
    if "hal2-cli-agents hook claude PreToolUse" not in hooks:
        drift.append("~/.claude/settings.json has no PreToolUse hook: run hal2-cli-agents install-hooks claude")
    for line in drift:
        print("DRIFT", line)
    print("ok" if not drift else f"{len(drift)} drift(s): update SKILL.md (Insider knowledge) to match")
    return 1 if drift else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show")
    s.add_argument("--pane")
    s.add_argument("--session")
    s.add_argument("--worktree", help="worktree slot, e.g. 02 or main")
    s.add_argument("--repo", help="repository name (default: this checkout's, else any)")
    s.add_argument("--hours", type=float, default=3)
    k = sub.add_parser("capture")
    k.add_argument("--pane")
    k.add_argument("--session")
    k.add_argument("--worktree", help="worktree slot, e.g. 02 or main")
    k.add_argument("--repo", help="repository name (default: this checkout's, else any)")
    k.add_argument("--out", required=True)
    k.add_argument("--hours", type=float, default=3)
    d = sub.add_parser("doctor")
    d.add_argument("--hours", type=float, default=24)
    d.add_argument("--json", action="store_true")
    c = sub.add_parser("selfcheck")
    c.add_argument("--repo", default="~/a/hal2")
    args = parser.parse_args()
    if args.cmd == "show":
        show(args)
    elif args.cmd == "capture":
        sys.exit(capture(args))
    elif args.cmd == "doctor":
        doctor(args)
    else:
        sys.exit(selfcheck(args))


if __name__ == "__main__":
    main()
