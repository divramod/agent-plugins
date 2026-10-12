#!/usr/bin/env python3
"""Deterministic half of the pause and continue skills: where the pause record lives, which processes the agent
session runs, and freezing (SIGSTOP) / thawing (SIGCONT) process trees.

Usage: pause.py <command> [args]
  path                 print the pause record (<root>/<slug>.md) for the current checkout
  status               print the record's path and age; exit 1 when nothing is paused here
  procs [--root PID]   the agent session's process tree: pid, ppid, state, started, command
  freeze PID...        SIGSTOP each pid and its descendants, remember them in <root>/<slug>.procs.json
  thaw                 SIGCONT the remembered processes that still run (same pid and start time)
  finish               move the record and its procs file to <root>/<slug>/history/<timestamp>-*

<root> is $PAUSE_ROOT or ~/skills/pause; <slug> is the git worktree root (or the current directory) with every
character outside [A-Za-z0-9] replaced by '-'. Exit 2: a required tool (ps) is missing.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

AGENTS = ("claude", "codex", "opencode", "grok")


def need_ps():
    if not shutil.which("ps"):
        print("pause.py: ps is missing; run install-prerequisites.sh", file=sys.stderr)
        sys.exit(2)


def root() -> Path:
    return Path(os.environ.get("PAUSE_ROOT") or Path.home() / "skills" / "pause")


def checkout() -> str:
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True)
        return top.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return os.getcwd()


def slug() -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", checkout())


def record() -> Path:
    return root() / f"{slug()}.md"


def procs_file() -> Path:
    return root() / f"{slug()}.procs.json"


def table():
    """Every process: pid -> {pid, ppid, stat, started, command}."""
    need_ps()
    out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,stat=,lstart=,command="],
                         capture_output=True, text=True, check=True, env={**os.environ, "LC_ALL": "C"}).stdout
    rows = {}
    for line in out.splitlines():
        parts = line.split(None, 8)
        if len(parts) < 8:
            continue
        pid, ppid, stat = int(parts[0]), int(parts[1]), parts[2]
        rows[pid] = {"pid": pid, "ppid": ppid, "stat": stat, "started": " ".join(parts[3:8]),
                     "command": parts[8] if len(parts) > 8 else ""}
    return rows


def descendants(rows, pid):
    kids = {}
    for r in rows.values():
        kids.setdefault(r["ppid"], []).append(r["pid"])
    found, todo = [], [pid]
    while todo:
        p = todo.pop()
        for k in kids.get(p, []):
            found.append(k)
            todo.append(k)
    return found


def agent_root(rows):
    """The nearest ancestor whose executable is an agent CLI; else the parent of this script's shell."""
    pid = os.getppid()
    while pid in rows and pid > 1:
        exe = os.path.basename(rows[pid]["command"].split(" ", 1)[0])
        if exe in AGENTS or any(exe.startswith(a + "-") for a in AGENTS):
            return pid
        pid = rows[pid]["ppid"]
    return rows.get(os.getppid(), {}).get("ppid", os.getppid())


def cmd_procs(args):
    rows = table()
    rid = int(args[args.index("--root") + 1]) if "--root" in args else agent_root(rows)
    # The shell running this script and its pipeline are not session work.
    mine = {os.getpid(), os.getppid(), *descendants(rows, os.getppid())}
    print(f"root {rid}: {rows.get(rid, {}).get('command', '?')}")
    for p in descendants(rows, rid):
        r = rows[p]
        if p in mine:
            continue
        print(f"{r['pid']}\t{r['ppid']}\t{r['stat']}\t{r['started']}\t{r['command']}")
    return 0


def load_procs():
    f = procs_file()
    return json.loads(f.read_text()) if f.exists() else []


def cmd_freeze(args):
    if not args:
        print("pause.py freeze: name at least one pid", file=sys.stderr)
        return 1
    rows = table()
    known = {(p["pid"], p["started"]) for p in load_procs()}
    frozen = load_procs()
    status = 0
    for arg in args:
        pid = int(arg)
        if pid not in rows:
            print(f"gone {pid}")
            status = 1
            continue
        for p in [pid, *descendants(rows, pid)]:
            try:
                os.kill(p, signal.SIGSTOP)
            except ProcessLookupError:
                continue
            r = rows[p]
            if (p, r["started"]) not in known:
                frozen.append({"pid": p, "started": r["started"], "command": r["command"], "top": pid})
                known.add((p, r["started"]))
            print(f"frozen {p}\t{r['command']}")
    root().mkdir(parents=True, exist_ok=True)
    procs_file().write_text(json.dumps(frozen, indent=2) + "\n")
    return status


def cmd_thaw(_args):
    rows = table()
    for p in load_procs():
        r = rows.get(p["pid"])
        if r and r["started"] == p["started"]:
            try:
                os.kill(p["pid"], signal.SIGCONT)
                print(f"thawed {p['pid']}\t{p['command']}")
                continue
            except ProcessLookupError:
                pass
        print(f"gone {p['pid']}\t{p['command']}")
    if procs_file().exists():
        procs_file().unlink()
    return 0


def cmd_status(_args):
    f = record()
    if not f.exists():
        print(f"nothing paused for {checkout()} ({f} does not exist)")
        return 1
    age = int(time.time() - f.stat().st_mtime)
    print(f"{f}\tpaused {age // 3600}h {age % 3600 // 60}m ago\t{len(load_procs())} frozen process(es)")
    return 0


def cmd_finish(_args):
    f = record()
    if not f.exists():
        print(f"pause.py finish: {f} does not exist", file=sys.stderr)
        return 1
    hist = root() / slug() / "history"
    hist.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    f.rename(hist / f"{stamp}-pause.md")
    if procs_file().exists():
        procs_file().rename(hist / f"{stamp}-procs.json")
    print(hist / f"{stamp}-pause.md")
    return 0


COMMANDS = {"path": lambda a: print(record()) or 0, "status": cmd_status, "procs": cmd_procs,
            "freeze": cmd_freeze, "thaw": cmd_thaw, "finish": cmd_finish}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(1)
    sys.exit(COMMANDS[sys.argv[1]](sys.argv[2:]))
