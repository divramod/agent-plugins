#!/usr/bin/env python3
"""Deterministic half of stop-all-agent-work and continue-all-agent-work: the record of which Claude sessions were
told to stop, so the continue skill tells exactly those to go on.

Usage: stopall.py <command> [args]
  save --stopped NAME... [--keep NAME...] [--note TEXT]
                 write the record; a record that exists already gets the new names added (a second stop)
  status         print the record; exit 1 when no stop is active
  finish         move the record to <root>/history/<timestamp>.json (the continue skill, after it sent all)

<root> is $STOP_ALL_AGENT_WORK_ROOT or ~/skills/stop-all-agent-work; the record is <root>/state.json.
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path


def root() -> Path:
    return Path(os.environ.get("STOP_ALL_AGENT_WORK_ROOT") or Path.home() / "skills" / "stop-all-agent-work")


def record() -> Path:
    return root() / "state.json"


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def merge(names: list, more: list) -> list:
    return names + [n for n in more if n not in names]


def save(stopped: list, keep: list, note: str) -> dict:
    path = record()
    if path.exists():
        state = json.loads(path.read_text())
        state["stopped"] = merge(state["stopped"], stopped)
        state["keep"] = [n for n in merge(state["keep"], keep) if n not in state["stopped"]]
        state.setdefault("again", []).append(now())
    else:
        state = {"stopped_at": now(), "note": note, "keep": keep, "stopped": stopped}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1) + "\n")
    return state


def actions() -> list:
    path = record()
    return json.loads(path.read_text()).get("actions", []) if path.exists() else []


def add_actions(done: list) -> None:
    """Append what quiet.py did to the record (created when no stop is recorded yet)."""
    path = record()
    state = json.loads(path.read_text()) if path.exists() else {"stopped_at": now(), "note": "", "keep": [],
                                                                "stopped": []}
    state.setdefault("actions", []).extend(done)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1) + "\n")


def finish() -> Path:
    path = record()
    dest = root() / "history" / (datetime.now().strftime("%Y%m%d-%H%M%S") + ".json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(path.read_text())
    state["continued_at"] = now()
    dest.write_text(json.dumps(state, indent=1) + "\n")
    path.unlink()
    return dest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="stopall.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("save")
    s.add_argument("--stopped", nargs="+", required=True)
    s.add_argument("--keep", nargs="*", default=[])
    s.add_argument("--note", default="")
    sub.add_parser("status")
    sub.add_parser("finish")
    a = ap.parse_args(argv)
    if a.cmd == "save":
        state = save(a.stopped, a.keep, a.note)
        print(f"{record()}: {len(state['stopped'])} stopped, kept: {', '.join(state['keep']) or 'none'}")
        return 0
    if not record().exists():
        print(f"no stop is active ({record()} missing)", file=sys.stderr)
        return 1
    if a.cmd == "status":
        print(record())
        print(record().read_text(), end="")
        return 0
    print(f"finished: {finish()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
