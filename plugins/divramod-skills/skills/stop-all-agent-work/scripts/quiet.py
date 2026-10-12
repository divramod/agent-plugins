#!/usr/bin/env python3
"""Quiet the machine for benchmarks once the agent sessions are paused, and undo it afterwards. Deterministic half
of stop-all-agent-work (apply) and continue-all-agent-work (restore); every action and its undo goes into the stop
record (<root>/state.json, see stopall.py), so restore puts back exactly what apply changed.

Usage: quiet.py <command> [options]
  scan    [--keep-cwd DIR]... [--json]   list what still costs CPU, by kind, with what apply would do
  apply   [--keep-cwd DIR]... [--runner] [--dry-run] [--yes PID|LABEL...]
                                         freeze, stop and shut down the safe kinds (below), record each action;
                                         a row marked CONFIRM (important work, below) is only touched when --yes
                                         names it; exit 3 when CONFIRM rows were left for the user's answer
  restore [--dry-run]                    undo the recorded actions in reverse order (thaw, start, load again)

Kinds and what apply does:
  session    a process below a paused agent session (a build, sourcekit-lsp indexing, a test): SIGSTOP; undo SIGCONT
  orphan     a test leftover under /tmp whose session is gone (e.g. UI-test daemons): SIGTERM; no undo
  simulator  a booted iOS simulator: shutdown; no undo (tests boot their own)
  ollama     the Ollama app and server: SIGTERM (the app's quit dialog blocks a polite quit); undo `open -a Ollama`.
             Checked over HTTP only: the `ollama` CLI starts Ollama.app when the server is down
  agent      a loaded LaunchAgent of ~/Library/LaunchAgents that runs on a timer (StartInterval, StartCalendarInterval),
             e.g. local.ollama-keepalive (every 60 s): launchctl bootout; undo launchctl bootstrap
  docker     a running container: docker pause; undo docker unpause
  runner     a self-hosted GitHub Actions runner LaunchAgent: only with --runner (CI jobs wait meanwhile); bootout/bootstrap
  report     listed only, never touched: macOS daemons (syspolicyd, mds, WindowServer), apps the user runs
             (Chrome, VoiceInk, ...), processes of the kept sessions
CONFIRM: a session or orphan process doing important work (copying or moving data to a volume, a git push, merge
or landing, a deploy, a database migration or dump, a software install, an upload, a disk or backup operation) and
the CI runner: stopping it mid-way can break or half-finish something, so the user decides first.
--keep-cwd: a kept session's checkout; the agent whose cwd is in it, and everything below it, are left alone. The
session running this script is always left alone. Exit 2: a required tool is missing.
"""
import argparse
import json
import os
import plistlib
import re
import shutil
import signal
import subprocess
import sys
import urllib.request
from pathlib import Path

import stopall

AGENTS = ("claude", "codex", "opencode")
SYSTEM = ("/System/", "/usr/libexec/", "/usr/sbin/", "/sbin/", "/Library/Apple/", "/usr/bin/", "/bin/")
OLLAMA = "http://127.0.0.1:11434"
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
NEVER_BOOTOUT = ("local.hal2.daemon",)  # the kept session's tools may need it
# Work that breaks or leaves something half done when frozen or killed mid-way: apply asks first (--yes).
IMPORTANT = [
    (r"\b(rsync|ditto|scp)\b|\b(cp|mv)\b.*(/Volumes/|/media/)", "copies or moves data"),
    (r"\bgit\b.*\b(push|merge|rebase|commit)\b|merge-to-main|\bland\b", "git write or landing"),
    (r"\b(deploy|terraform|ansible-playbook|pulumi|kubectl (apply|delete)|helm (install|upgrade))\b",
     "deploys"),
    (r"\b(migrate|migration|psql|pg_dump|pg_restore|mysqldump|sqlite3)\b", "touches a database"),
    (r"\b(brew (install|upgrade|reinstall)|softwareupdate|installer|pkgutil|xcodes install)\b", "installs software"),
    (r"\b(notarytool|altool|docker push|tart push|twine upload|npm publish|cargo publish)\b", "uploads or publishes"),
    (r"\b(diskutil|hdiutil|asr|tmutil)\b", "disk or backup operation"),
]


def need(tool: str):
    if not shutil.which(tool):
        print(f"quiet.py: {tool} is missing; run install-prerequisites.sh", file=sys.stderr)
        sys.exit(2)


def run(argv: list) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def procs() -> dict:
    table = {}
    for line in run(["ps", "-Ao", "pid=,ppid=,pcpu=,rss=,stat=,command="]).splitlines():
        m = re.match(r"\s*(\d+)\s+(\d+)\s+([\d.]+)\s+(\d+)\s+(\S+)\s+(.*)", line)
        if m:
            pid, ppid, cpu, rss, stat, cmd = m.groups()
            table[int(pid)] = {"pid": int(pid), "ppid": int(ppid), "cpu": float(cpu), "rss_mb": int(rss) // 1024,
                               "stat": stat, "cmd": cmd}
    return table


def is_agent(cmd: str) -> bool:
    return cmd.split(" ", 1)[0].rsplit("/", 1)[-1] in AGENTS


def cwd(pid: int) -> str:
    for line in run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"]).splitlines():
        if line.startswith("n"):
            return line[1:]
    return ""


def chain(table: dict, pid: int) -> list:
    seen = []
    while pid in table and pid not in seen and pid > 1:
        seen.append(pid)
        pid = table[pid]["ppid"]
    return seen


def under(path: str, dirs: list) -> bool:
    return any(path == d.rstrip("/") or path.startswith(d.rstrip("/") + "/") for d in dirs)


def ollama_running() -> bool:
    try:
        urllib.request.urlopen(OLLAMA + "/api/ps", timeout=3)
        return True
    except OSError:
        return False


def timer_agents(runner: bool) -> list:
    loaded = {}
    for line in run(["launchctl", "list"]).splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) == 3:
            loaded[parts[2]] = parts[0]
    found = []
    for plist in sorted(LAUNCH_AGENTS.glob("*.plist")):
        try:
            data = plistlib.loads(plist.read_bytes())
        except Exception:
            continue
        label = data.get("Label", "")
        if label not in loaded or label in NEVER_BOOTOUT:
            continue
        if label.startswith("actions.runner."):
            found.append(("runner" if runner else "report", label, str(plist), "self-hosted CI runner"))
        elif "StartInterval" in data or "StartCalendarInterval" in data:
            every = f"every {data['StartInterval']} s" if "StartInterval" in data else "on a calendar"
            found.append(("agent", label, str(plist), every))
    return found


def important(cmd: str) -> str:
    """Why stopping this process mid-way is risky, or ''."""
    for pattern, why in IMPORTANT:
        if re.search(pattern, cmd):
            return why
    return ""


def key(row: dict) -> str:
    """What --yes names to confirm a row: its pid, or its LaunchAgent label."""
    return str(row.get("pid") or row.get("label") or row.get("id") or row.get("udid") or "")


def scan(keep: list, runner: bool) -> list:
    table = procs()
    agents = {pid: cwd(pid) for pid, p in table.items() if is_agent(p["cmd"])}
    me = next((a for a in chain(table, os.getpid()) if a in agents), None)
    keep_pids = {pid for pid, path in agents.items() if path and under(path, keep)}
    if me:
        keep_pids.add(me)
    rows = []
    for p in table.values():
        if p["pid"] in agents or p["pid"] == os.getpid():
            continue
        ch = chain(table, p["pid"])
        owner = next((a for a in ch[1:] if a in agents), None)
        cmd, busy = p["cmd"], p["cpu"] >= 5 or p["rss_mb"] >= 1024
        row = {"pid": p["pid"], "cpu": p["cpu"], "rss_mb": p["rss_mb"], "frozen": p["stat"].startswith("T"),
               "session": agents.get(owner, ""), "what": cmd[:300]}
        busy = busy or (owner not in keep_pids and bool(important(cmd)))
        if owner in keep_pids:
            if busy:
                rows.append({**row, "kind": "report", "why": "kept session"})
        elif owner:
            if busy and not row["frozen"]:
                rows.append({**row, "kind": "session"})
        elif "/Ollama.app/" in cmd or cmd.endswith("ollama serve"):
            continue  # handled as one ollama row below
        elif re.search(r"(/private)?/tmp/", cmd) and table.get(p["ppid"], {}).get("ppid") is not None \
                and not cmd.startswith(SYSTEM) and (p["ppid"] == 1 or all(a not in agents for a in ch)):
            rows.append({**row, "kind": "orphan"})
        elif busy:
            rows.append({**row, "kind": "report", "why": "system" if cmd.startswith(SYSTEM) else "app"})
    pids = [p["pid"] for p in table.values() if "/Ollama.app/Contents/" in p["cmd"].split(" ", 1)[0]
            or p["cmd"].endswith("ollama serve")]
    if pids:
        rows.append({"kind": "ollama", "pids": pids, "what": "Ollama app and server"})
    elif ollama_running():
        rows.append({"kind": "report", "pid": "", "cpu": 0, "rss_mb": 0, "why": "ollama server not from the app",
                     "what": "ollama serve on :11434 (stop it how it was started)"})
    if shutil.which("xcrun"):
        for line in run(["xcrun", "simctl", "list", "devices", "booted"]).splitlines():
            m = re.match(r"\s+(.+?) \(([0-9A-F-]{36})\) \(Booted\)", line)
            if m:
                rows.append({"kind": "simulator", "udid": m.group(2), "what": f"simulator {m.group(1)}"})
    if shutil.which("docker"):
        for line in run(["docker", "ps", "--format", "{{.ID}} {{.Names}}"]).splitlines():
            if line.strip():
                cid, name = line.split(" ", 1)
                rows.append({"kind": "docker", "id": cid, "what": f"container {name}"})
    for kind, label, plist, why in timer_agents(runner):
        rows.append({"kind": kind, "label": label, "plist": plist, "what": f"LaunchAgent {label}", "why": why})
    for row in rows:
        why = "self-hosted CI runner: CI jobs wait while it is unloaded" if row["kind"] == "runner" else \
            important(row["what"]) if row["kind"] in ("session", "orphan") else ""
        if why:
            row["confirm"] = why
    order = ["session", "orphan", "ollama", "agent", "simulator", "docker", "runner", "report"]
    return sorted(rows, key=lambda r: (order.index(r["kind"]), -r.get("cpu", 0)))


def action(row: dict):
    """(do argv or signal, undo argv or signal, text) for one row; None for report rows."""
    uid = str(os.getuid())
    k = row["kind"]
    if k == "session":
        return ("STOP", row["pid"]), ("CONT", row["pid"]), f"freeze {row['pid']} ({row['session']})"
    if k == "orphan":
        return ("TERM", row["pid"]), None, f"terminate orphan {row['pid']}"
    if k == "ollama":
        return ("TERM", row["pids"]), ["open", "-a", "Ollama"], "terminate Ollama"
    if k == "simulator":
        return ["xcrun", "simctl", "shutdown", row["udid"]], None, f"shut down {row['what']}"
    if k == "docker":
        return ["docker", "pause", row["id"]], ["docker", "unpause", row["id"]], f"pause {row['what']}"
    if k in ("agent", "runner"):
        return (["launchctl", "bootout", f"gui/{uid}/{row['label']}"],
                ["launchctl", "bootstrap", f"gui/{uid}", row["plist"]], f"unload {row['what']}")
    return None


def perform(step) -> bool:
    if isinstance(step, tuple):
        sig, pids = step
        ok = True
        for pid in pids if isinstance(pids, list) else [pids]:
            try:
                os.kill(pid, getattr(signal, "SIG" + sig))
            except ProcessLookupError:
                ok = False
        return ok
    return subprocess.run(step, capture_output=True).returncode == 0


def show(step) -> str:
    if isinstance(step, tuple):
        return f"kill -{step[0]} {' '.join(map(str, step[1] if isinstance(step[1], list) else [step[1]]))}"
    return " ".join(step)


def apply(keep: list, runner: bool, dry: bool, yes: list) -> int:
    """Exit 3 when rows wait for the user's confirmation (--yes <pid|label>); everything else is done."""
    rows = scan(keep, runner)
    done, waiting = [], []
    for row in rows:
        act = action(row)
        if not act:
            continue
        do, undo, text = act
        if row.get("confirm") and key(row) not in yes:
            waiting.append(row)
            continue
        ok = True if dry else perform(do)
        print(f"{'would ' if dry else ''}{text}: {show(do)}{'' if ok else '  (failed)'}")
        if ok and not dry:
            done.append({"text": text, "do": list(do) if isinstance(do, tuple) else do,
                         "undo": list(undo) if isinstance(undo, tuple) else undo})
    if done:
        stopall.add_actions(done)
    for row in rows:
        if row["kind"] == "report":
            cpu = f" {row['cpu']}%" if "cpu" in row else ""
            print(f"left alone ({row.get('why')}): {row.get('pid', '')}{cpu} {row['what'][:100]}")
    for row in waiting:
        print(f"CONFIRM {key(row)}: {row['confirm']}: {text_of(row)} ({row.get('session') or '-'}) "
              f"{row['what'][:160]}")
    return 3 if waiting else 0


def text_of(row: dict) -> str:
    return action(row)[2]


def restore(dry: bool) -> int:
    for a in reversed(stopall.actions()):
        undo = a.get("undo")
        if not undo:
            continue
        step = tuple(undo) if undo[0] in ("STOP", "CONT", "TERM") else undo
        ok = True if dry else perform(step)
        print(f"{'would undo' if dry else 'undo'} {a['text']}: {show(step)}{'' if ok else '  (gone or failed)'}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="quiet.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("scan", "apply"):
        s = sub.add_parser(name)
        s.add_argument("--keep-cwd", action="append", default=[])
        s.add_argument("--runner", action="store_true")
    sub.choices["scan"].add_argument("--json", action="store_true")
    sub.choices["apply"].add_argument("--dry-run", action="store_true")
    sub.choices["apply"].add_argument("--yes", nargs="*", default=[], metavar="PID|LABEL")
    sub.add_parser("restore").add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    for tool in ("ps", "lsof", "launchctl"):
        need(tool)
    if a.cmd == "restore":
        return restore(a.dry_run)
    if a.cmd == "apply":
        return apply(a.keep_cwd, a.runner, a.dry_run, a.yes)
    rows = scan(a.keep_cwd, a.runner)
    if a.json:
        print(json.dumps(rows, indent=1))
        return 0
    print(run(["uptime"]).strip())
    for r in rows:
        act = action(r)
        num = f"{r['cpu']:5.1f}% {r['rss_mb']:6}MB" if "cpu" in r else " " * 14
        ask = f"  CONFIRM ({r['confirm']})" if r.get("confirm") else ""
        print(f"{r['kind']:9} {r.get('pid', ''):>6} {num} {r.get('session') or r.get('why') or '':40.40} "
              f"{r['what'][:80]}  -> {act[2] if act else 'left alone'}{ask}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
