#!/usr/bin/env python3
"""The prune duty's disk phase (hal2 plan 0514 step 7, D18): /prune's `disk` started in every round it is due.

Each round the duty asks /prune `disk --due --json` (a program, never imported: plan 0377 D3; the free space from the
filesystem's own count, no `du`) and, when the disk is below /prune's mark and no disk phase of this duty lives,
starts `prune.py disk --repo <main>` detached (its pid in DISK_FILE, its output in DISK_LOG of the tollman's state
folder). Neither a workqueue hold, a train's local phase nor a detached prune run holds it back: the phase keeps the
busy fields itself (a busy agent, a build, the hold's own field) and deletes only idle fields' Rust build folders
through its proof. A failed ask wakes the tollman once per 6 hours.

  prune_disk.py start [--repo DIR]
      the detached disk phase; returns at once ("disk phase already going" while one lives)
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import prune_ask
from skillpath import sibling
from tick import act

DISK_FILE, DISK_LOG = "prune-disk.json", "prune-disk.log"
DUE_TIMEOUT = 60
MAX_AGE = 6 * 3600  # a pid file older than this belongs to a phase that died, its pid maybe reused
WINDOW = 10 * 60  # a phase that ended with the disk still low (nothing idle left) is started again after this
FAILED_EVERY = 6 * 3600


def script() -> Path:
    """/prune's `prune.py` (FileNotFoundError: not installed)."""
    return sibling("prune") / "scripts" / "prune.py"


def folder(main: str) -> Path:
    return mtm_scan.state_dir(main, "tollman")


def running(main: str, now: float | None = None) -> bool:
    try:
        info = json.loads((folder(main) / DISK_FILE).read_text())
        return prune_ask.alive(int(info["pid"])) and (now or time.time()) - info["at"] < MAX_AGE
    except (OSError, ValueError, KeyError, TypeError):
        return False


def due(main: str, run=subprocess.run) -> tuple[dict | None, str]:
    """/prune's `disk --due --json`: (its answer, ""), or (None, why it could not be asked)."""
    try:
        argv = [sys.executable, str(script()), "disk", "--due", "--json", "--repo", main]
        p = run(argv, cwd=main, capture_output=True, text=True, timeout=DUE_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"prune.py disk --due: {e}"
    try:
        state = json.loads(p.stdout) if p.returncode == 0 else None
    except ValueError:
        state = None
    if not isinstance(state, dict) or "due" not in state:
        return None, f"prune.py disk --due exited {p.returncode}: {(p.stderr or p.stdout).strip()[-200:]}"
    return state, ""


def failed(text: str) -> dict:
    return act("prune", "disk-failed", "wake", key="prune:disk-failed", window=FAILED_EVERY,
               text=f"/prune's disk phase could not be asked: {text}")


def actions(ctx: dict, ask=None) -> list[dict]:
    """The round's disk phase: a detached start when the disk is below /prune's mark, else nothing."""
    main = ctx["main"]
    if running(main):
        return []
    state, why = (ask or due)(main)
    if state is None:
        return [failed(why)]
    if not state["due"]:
        return []
    return [act("prune", "disk-phase", "run", key="prune:disk-phase", window=WINDOW, cwd=main,
                argv=[sys.executable, str(Path(__file__).resolve()), "start", "--repo", main],
                on_fail=[failed("prune_disk.py start failed")],
                text=f"disk phase started: {state['free_gb']:g} GB free, below {state['below_gb']:g} GB")]


def start(main: str, spawn=subprocess.Popen) -> int:
    """The detached `prune.py disk`, its pid kept; one at a time."""
    if running(main):
        print("disk phase already going")
        return 0
    argv = [sys.executable, str(script()), "disk", "--repo", main]
    where = folder(main)
    with (where / DISK_LOG).open("w") as out:
        p = spawn(argv, cwd=main, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    tmp = where / f".{DISK_FILE}.tmp"
    tmp.write_text(json.dumps({"pid": p.pid, "at": time.time(), "argv": argv}))
    tmp.replace(where / DISK_FILE)
    print(f"started the disk phase (pid {p.pid}, log {where / DISK_LOG})")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=("start",))
    p.add_argument("--repo", default=".")
    args = p.parse_args(argv)
    try:
        script()
    except FileNotFoundError as e:
        print(f"prune_disk.py: {e}", file=sys.stderr)
        return 2
    return start(mtm_scan.main_checkout(args.repo))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
