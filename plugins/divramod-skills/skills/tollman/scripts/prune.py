#!/usr/bin/env python3
"""The tollman's prune duty (hal2 plan 0143 step 8; the tollman's since plan 0360 step 7; calls /prune since plan 0377
step 7, D3, D12): landed fields mucked out or removed, a stale pointer cleared, and after the barn the last train's cars
cleared (barn.py). The deciding and the deleting are /prune's (the proof, the order, the lock): this duty only asks.

  prune.py plan [--repo <dir>] [--json]
      /prune's own `plan`: the facts and what a run would do (nothing changes)
  prune.py start [--repo <dir>] [--slot <field>] [--field NN]...
      one detached run of /prune: `hal2-cli-runs exec --workflow prune --slot <field> -- python3 <prune>/prune.py run
      --repo <main> [--field NN]...` (without hal2-cli-runs: `prune.py run` alone); returns at once, the pid in
      `prune-run.json`, the output in `prune-run.log` of the tollman's state folder

The tick (`handler`) runs /prune's `plan --json` each round and plans nothing while a detached run lives or /prune
plans nothing. Otherwise it keeps the old triggers: a free keeper 00-09 mucked out once per landing (keyed on HEAD),
one removal of a field 10-99 per round (the last train's cars come first in /prune's order), a stale pointer cleared,
a trim while the disk is short, and starts one run for them (the first action runs, the others are record lines
carrying their keys). After the barn (barn.py) a car's session is cleared; every 6 hours the free disk and the biggest
fields come from /prune's facts, a notice under 100 GB free. /prune not installed or its plan failing wakes the
tollman once per 6 hours.
Exit 0 done, 1 failed (the tick then wakes the tollman), 2 a tool missing.
"""

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import barn
import mtm_scan
import tick
from skillpath import sibling
from tick import act

ROLE = "tollman"
LOW_DISK_GB = 100
REPORT_EVERY = 6 * 3600
TOP = 5
PLAN_TIMEOUT = 120  # a round asks with --cached-sizes (no walk, D26); the detached run measures and fills the cache
RUN_FILE, RUN_LOG = "prune-run.json", "prune-run.log"
RUN_MAX_AGE = 6 * 3600  # a pid file older than this belongs to a run that died, its pid maybe reused
WINDOWS = {"clean": 30 * 24 * 3600, "remove": 3600, "pointer": 3600, "trim": REPORT_EVERY}


def script() -> Path:
    """/prune's `prune.py`, found as a program beside this skill (never imported, D3). FileNotFoundError: not installed."""
    return sibling("prune") / "scripts" / "prune.py"


def state(main: str) -> Path:
    return mtm_scan.state_dir(main, ROLE)


def ask(main: str, timeout: int = PLAN_TIMEOUT) -> tuple[dict | None, str]:
    """/prune's `plan --json` of the farm: (its `{plan, facts}`, ""), or (None, why it could not be asked)."""
    try:
        argv = [sys.executable, str(script()), "plan", "--json", "--cached-sizes", "--repo", main]
    except FileNotFoundError as e:
        return None, str(e)
    try:
        p = subprocess.run(argv, cwd=main, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"prune.py plan: {e}"
    if p.returncode:
        return None, f"prune.py plan exited {p.returncode}: {(p.stderr or p.stdout).strip()[-300:]}"
    try:
        data = json.loads(p.stdout)
        data["plan"]["jobs"], data["facts"]["fields"], data["facts"]["disk"]
    except (ValueError, KeyError, TypeError):
        return None, "prune.py plan --json gave no plan"
    return data, ""


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def running(main: str, now: float | None = None) -> bool:
    """Does the run this duty started still live (its pid, no older than RUN_MAX_AGE)?"""
    try:
        info = json.loads((state(main) / RUN_FILE).read_text())
        return alive(int(info["pid"])) and (now or time.time()) - info["at"] < RUN_MAX_AGE
    except (OSError, ValueError, KeyError, TypeError):
        return False


def launch_argv(main: str, slot: str, fields: list[str]) -> list[str]:
    run = [sys.executable, str(script()), "run", "--repo", main] + [x for f in fields for x in ("--field", f)]
    if shutil.which("hal2-cli-runs"):
        return ["hal2-cli-runs", "exec", "--workflow", "prune", "--slot", slot, "--trigger",
                "the tollman's duty prune", "--"] + run
    return run


def start(main: str, slot: str, fields: list[str], spawn=subprocess.Popen) -> int:
    """`prune.py start`: the detached run of /prune, its pid kept; one at a time."""
    if running(main):
        print("prune run already going")
        return 0
    argv = launch_argv(main, slot, fields)
    folder = state(main)
    with (folder / RUN_LOG).open("w") as out:
        p = spawn(argv, cwd=main, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    tmp = folder / f".{RUN_FILE}.tmp"
    tmp.write_text(json.dumps({"pid": p.pid, "at": time.time(), "argv": argv}))
    tmp.replace(folder / RUN_FILE)
    print(f"started {' '.join(argv[:3])} ... (pid {p.pid}, log {folder / RUN_LOG})")
    return 0


def report(main: str, ctx: dict, data: dict) -> list[dict]:
    """Every REPORT_EVERY: the free disk and the biggest fields (from /prune's facts) as a record, a notice when low."""
    now = ctx["now"]
    if any(str(e.get("key", "")).startswith("prune:disk:") and
           (now - dt.datetime.fromisoformat(e["at"])).total_seconds() < REPORT_EVERY for e in ctx.get("log", [])):
        return []
    free = data["facts"]["disk"]["free_gb"]
    big = sorted(((f["size"]["bytes"] / 1e9, f["slot"]) for f in data["facts"]["fields"]
                  if f.get("size") and f["size"].get("bytes")), reverse=True)[:TOP]
    biggest = ", ".join(f"{slot} {gb:.0f} GB" for gb, slot in big) or "unknown"
    out = [act("prune", "disk", "record", key=f"prune:disk:{now:%Y-%m-%dT%H}", window=REPORT_EVERY,
               text=f"free disk {free:.0f} GB; biggest worktrees: {biggest}")]
    if free < LOW_DISK_GB:
        out.append(act("prune", "low-disk", "notify", key="prune:low-disk", window=REPORT_EVERY,
                       text=f"only {free:.0f} GB free on the disk of {main}; biggest worktrees: {biggest}"))
    return out


def failed(text: str) -> dict:
    return act("prune", "failed", "wake", key="prune:failed", window=REPORT_EVERY, text=f"/prune could not be asked: {text}")


def wanted(plan: dict, heads: dict[str, str]) -> list[dict]:
    """The planned actions as keyed log lines: a clear of a pointer, a muck out per HEAD, a removal, trims."""
    out = []
    for job in ("stale-pointers", "phase-1", "phase-2", "phase-3"):
        for a in plan["jobs"].get(job, {}).get("actions", []):
            slot, head = a["field"], heads.get(a["field"], "")
            kind = {"clear-pointer": "pointer", "muck-out": "clean", "remove": "remove", "trim": "trim"}.get(a["action"])
            if kind is None:
                continue  # an `ask` is the foreman's to answer (/prune's report), never this duty's
            key = f"prune:{kind}:{slot}:{a.get('plan') if kind == 'pointer' else head}"
            out.append(act("prune", kind, "record", slot, key=key, window=WINDOWS[kind], field=slot,
                           text=f"{a['action']} field {slot} ({a['why']})"))
    return out


def plan(item: dict, ctx: dict, data: dict | None = None, landed: dict | None = None) -> list[dict]:
    """The duty's actions this round (see the module doc); `data`: /prune's plan --json (asked when None)."""
    main = ctx["main"]
    if running(main):
        return []
    if data is None:
        data, why = ask(main)
        if data is None:
            return [failed(why)]
    found = [{"slot": f["slot"], "path": f["path"], "head": f.get("head", ""), "why": f["proof"],
              "sessions": f["sessions"]} for f in data["facts"]["fields"]]
    heads = {w["slot"]: w["head"] for w in found}
    landed = barn.last_landed(main) if landed is None else landed
    todo = tick.fresh(wanted(data["plan"], heads), ctx.get("log", []), ctx["now"])
    first = next((a for a in todo if a["kind"] == "remove"), None)  # one removal per round, the cars first
    todo = [a for a in todo if a["kind"] != "remove" or a is first]
    out = []
    if todo:
        fields = sorted({a["field"] for a in todo})
        todo[0] = {**todo[0], "do": "run", "cwd": main, "on_fail": [failed("prune.py start failed")],
                   "argv": [sys.executable, str(Path(__file__).resolve()), "start", "--repo", main,
                            "--slot", Path(ctx.get("top", main)).name] + [x for f in fields for x in ("--field", f)]}
        out = todo
    return out + barn.actions(ctx, found, landed) + report(main, ctx, data)


def handler(item: dict, ctx: dict) -> list[dict]:
    return plan(item, ctx)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=("plan", "start"))
    p.add_argument("--repo", default=".")
    p.add_argument("--slot")
    p.add_argument("--field", action="append", default=[])
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    main_dir = mtm_scan.main_checkout(args.repo)
    try:
        prune = script()
    except FileNotFoundError as e:
        print(f"prune.py: {e}", file=sys.stderr)
        return 2
    if args.cmd == "plan":
        return subprocess.call([sys.executable, str(prune), "plan", "--repo", main_dir, *(["--json"] * args.json)])
    return start(main_dir, args.slot or Path(args.repo).resolve().name, args.field)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
