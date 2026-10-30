#!/usr/bin/env python3
"""The tollman's prune duty (hal2 plan 0143 step 8; the tollman's since plan 0360 step 7; calls /prune since plan 0377
step 7, D3, D12): landed fields mucked out or removed, a stale pointer cleared, and after the barn the last train's cars
cleared (barn.py). The deciding and the deleting are /prune's (the proof, the order, the lock): this duty only asks.

  prune.py plan [--repo <dir>] [--json]
      /prune's own `plan`: the facts and what a run would do (nothing changes)
  prune.py ask [--repo <dir>]
      /prune's `plan --json --cached-sizes` written to `prune-plan.json` of the tollman's state folder (prune_ask.py,
      plan 0480 D4): what the round starts detached and reads the round after
  prune.py start [--repo <dir>] [--slot <field>] [--field NN]...
      one detached run of /prune: `hal2-cli-runs exec --workflow prune --slot <field> -- python3 <prune>/prune.py run
      --repo <main> [--field NN]...` (without hal2-cli-runs: `prune.py run` alone); returns at once, the pid in
      `prune-run.json`, the output in `prune-run.log` of the tollman's state folder

The tick (`handler`) plans nothing while a detached run lives; else it reads /prune's `plan --json` that the round
before asked detached (prune_ask.py: the ask never blocks a round; a plan past its max age or older than the last run
is not used), starts the next ask and plans nothing when /prune plans nothing. Otherwise it keeps the old triggers: a free keeper 00-09 mucked out once per landing (keyed on HEAD),
one removal of a field 10-99 per round (the last train's cars come first in /prune's order), a stale pointer cleared,
a trim while the disk is short and, after the trims, /prune's responses (`tart prune`, the listed caches: disk
watermark, plan 0472 D2); trims, muck outs and responses wait while a train builds (a workqueue hold or a train's local
phase, plan 0472, both checked live: never the old plan's `busy`), and starts one run for them (the first action runs, the others are record lines
carrying their keys). After the barn (barn.py) a car's session is cleared; every 6 hours the free disk and the biggest
fields come from /prune's facts. The notices use /prune's own threshold and goal (its plan's `short` and `goal_met`,
no constant here): a warning once per 6 hours above the goal (default 85% used) before the threshold bites, a
low-disk notice past the threshold (default 90% used or under 150 GB free). /prune not installed or its plan failing
wakes the tollman once per 6 hours.
Exit 0 done, 1 failed (the tick then wakes the tollman), 2 a tool missing.
"""

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import barn
import mtm_scan
import prune_ask
import tick
import train_state
from skillpath import sibling
from tick import act

ROLE = "tollman"
REPORT_EVERY = 6 * 3600
TOP = 5
PLAN_TIMEOUT = prune_ask.PLAN_TIMEOUT
RUN_FILE, RUN_LOG = "prune-run.json", "prune-run.log"
RUN_MAX_AGE = 6 * 3600  # a pid file older than this belongs to a run that died, its pid maybe reused
# A trim and a response may come again after an hour: a train's builds regrow the disk (train 25 reached 97% while a
# trim of the same field and HEAD was held back for 6 hours).
WINDOWS = {"clean": 30 * 24 * 3600, "remove": 3600, "pointer": 3600, "trim": 3600, "response": 3600}
RESPONSES = ("tart-prune", "cache-clear")


def script() -> Path:
    """/prune's `prune.py`, found as a program beside this skill (never imported, D3). FileNotFoundError: not installed."""
    return sibling("prune") / "scripts" / "prune.py"


def state(main: str) -> Path:
    return mtm_scan.state_dir(main, ROLE)


def ask(main: str, timeout: int = PLAN_TIMEOUT) -> tuple[dict | None, str]:
    """/prune's `plan --json` of the farm, synchronously (`prune.py ask`, detached): (its `{plan, facts}`, ""), or
    (None, why it could not be asked)."""
    try:
        return prune_ask.ask(script(), main, timeout)
    except FileNotFoundError as e:
        return None, str(e)


def ask_and_save(main: str) -> int:
    """`prune.py ask`: the plan asked and written for the next round, a failure too (its `why` wakes the tollman)."""
    at = time.time()
    data, why = ask(main)
    prune_ask.save(state(main), at, data, why)
    return 0 if data is not None else 1


def ask_next(main: str, ctx: dict) -> list[dict]:
    """The next ask started detached for the round after, unless one runs or the round is dry; [] or the wake."""
    folder = state(main)
    if ctx.get("dry") or prune_ask.asking(folder):
        return []
    try:
        prune_ask.begin(folder, [sys.executable, str(Path(__file__).resolve()), "ask", "--repo", main], main)
    except OSError as e:
        return [failed(f"prune.py ask could not start: {e}")]
    return []


alive = prune_ask.alive


def run_started(main: str) -> float:
    """When the last detached run started (0.0: none known); a plan asked before it is stale."""
    try:
        return float(json.loads((state(main) / RUN_FILE).read_text())["at"])
    except (OSError, ValueError, KeyError, TypeError):
        return 0.0


def running(main: str, now: float | None = None) -> bool:
    """Does the run this duty started still live (its pid, no older than RUN_MAX_AGE)?"""
    try:
        info = json.loads((state(main) / RUN_FILE).read_text())
        return alive(int(info["pid"])) and (now or time.time()) - info["at"] < RUN_MAX_AGE
    except (OSError, ValueError, KeyError, TypeError):
        return False


def launch_argv(main: str, slot: str, fields: list[str], responses: bool = False) -> list[str]:
    run = [sys.executable, str(script()), "run", "--repo", main] + [x for f in fields for x in ("--field", f)] \
        + (["--responses"] if responses else [])
    if shutil.which("hal2-cli-runs"):
        return ["hal2-cli-runs", "exec", "--workflow", "prune", "--slot", slot, "--trigger",
                "the tollman's duty prune", "--"] + run
    return run


def start(main: str, slot: str, fields: list[str], spawn=subprocess.Popen, responses: bool = False) -> int:
    """`prune.py start`: the detached run of /prune, its pid kept; one at a time."""
    if running(main):
        print("prune run already going")
        return 0
    argv = launch_argv(main, slot, fields, responses)
    folder = state(main)
    with (folder / RUN_LOG).open("w") as out:
        p = spawn(argv, cwd=main, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    tmp = folder / f".{RUN_FILE}.tmp"
    tmp.write_text(json.dumps({"pid": p.pid, "at": time.time(), "argv": argv}))
    tmp.replace(folder / RUN_FILE)
    print(f"started {' '.join(argv[:3])} ... (pid {p.pid}, log {folder / RUN_LOG})")
    return 0


def report(main: str, ctx: dict, data: dict, hold: str | None = None) -> list[dict]:
    """Every REPORT_EVERY: the free disk and the biggest fields (from /prune's facts) as a record; the watermark's
    notices (`watermark`) are their own, once per window each."""
    now = ctx["now"]
    out = []
    if not any(str(e.get("key", "")).startswith("prune:disk:") and
               (now - dt.datetime.fromisoformat(e["at"])).total_seconds() < REPORT_EVERY for e in ctx.get("log", [])):
        free = data["facts"]["disk"]["free_gb"]
        big = sorted(((f["size"]["bytes"] / 1e9, f["slot"]) for f in data["facts"]["fields"]
                      if f.get("size") and f["size"].get("bytes")), reverse=True)[:TOP]
        biggest = ", ".join(f"{slot} {gb:.0f} GB" for gb, slot in big) or "unknown"
        out.append(act("prune", "disk", "record", key=f"prune:disk:{now:%Y-%m-%dT%H}", window=REPORT_EVERY,
                       text=f"free disk {free:.0f} GB; biggest worktrees: {biggest}"))
    return out + tick.fresh(watermark(main, data, hold), ctx.get("log", []), now)


def watermark(main: str, data: dict, hold: str | None = None) -> list[dict]:
    """The disk watermark's notices (plan 0472 D2), read from /prune's plan (`short`: past its threshold, `goal_met`):
    `low-disk` past the threshold (what is deferred, live `hold`, or planned is said), `disk-warn` above the goal before
    it bites."""
    p, d = data["plan"], data["facts"]["disk"]
    state = f"{d['used_pct']:g}% used, {d['free_gb']:.0f} GB free on the disk of {main}"
    if p.get("short"):
        wait = hold or "/prune frees what is safe between trains"
        return [act("prune", "low-disk", "notify", key="prune:low-disk", window=REPORT_EVERY,
                    text=f"disk {state}: past /prune's threshold; {wait}")]
    if p.get("goal_met") is False:
        g = p.get("goal") or {}
        return [act("prune", "disk-warn", "notify", key="prune:disk-warn", window=REPORT_EVERY,
                    text=f"disk {state}: above /prune's goal ({g.get('used_pct', '?')}% used, {g.get('free_gb', '?')} GB "
                         "free); the safe response starts at its threshold")]
    return []


def held(main: str) -> str | None:
    """/prune's own answer now (busy.py as a program: a live workqueue hold), None without /prune."""
    try:
        return prune_ask.held(sibling("prune") / "scripts" / "busy.py", main)
    except FileNotFoundError:
        return None


def building(main: str) -> str | None:
    """Why trims, muck outs and size walks wait (plan 0472 D1), asked live (plan 0480 D4: never the plan's `busy`, it
    may be a round old): /prune's own answer (a live workqueue hold, busy.py) or the tollman's train in its local phase
    (started, its mtm process alive, no land run yet), else None."""
    if busy := held(main):
        return busy
    try:
        train = train_state.standing(train_state.lines(main))
    except OSError:
        return None
    if train and train["state"] in ("landing", "fixing", "retry") and not train.get("land_run") and train.get("pid") \
            and train_state.alive(train["pid"]):
        return f"deferred: train building (train {train.get('train')} in its local phase)"
    return None


def failed(text: str) -> dict:
    return act("prune", "failed", "wake", key="prune:failed", window=REPORT_EVERY, text=f"/prune could not be asked: {text}")


def wanted(plan: dict, heads: dict[str, str]) -> list[dict]:
    """The planned actions as keyed log lines: a clear of a pointer, a muck out per HEAD, a removal, trims, responses."""
    out = []
    for job in ("stale-pointers", "phase-1", "phase-2", "phase-3", "responses"):
        for a in plan["jobs"].get(job, {}).get("actions", []):
            slot, head = a["field"], heads.get(a["field"], "")
            kind = {"clear-pointer": "pointer", "muck-out": "clean", "remove": "remove", "trim": "trim",
                    "tart-prune": "response", "cache-clear": "response"}.get(a["action"])
            if kind is None:
                continue  # an `ask` is the foreman's to answer (/prune's report), never this duty's
            key = f"prune:{kind}:{slot}:{a.get('plan') if kind == 'pointer' else head}"
            if kind == "response":
                slot, key = a["field"], f"prune:response:{a['field']}"
            out.append(act("prune", kind, "record", slot, key=key, window=WINDOWS[kind], field=slot,
                           text=f"{a['action']} field {slot} ({a['why']})"))
    return out


def plan(item: dict, ctx: dict, data: dict | None = None, landed: dict | None = None) -> list[dict]:
    """The duty's actions this round (see the module doc); `data`: /prune's plan --json (the last ask's when None)."""
    main = ctx["main"]
    if running(main):
        return []
    asked = data is None
    if asked:  # the plan the last ask wrote, a round old at most (D4); none usable: ask now, plan the round after
        data, why = prune_ask.load(state(main), since=run_started(main)) or (None, "")
        if data is None:
            return ask_next(main, ctx) + ([failed(why)] if why else [])
    found = [{"slot": f["slot"], "path": f["path"], "head": f.get("head", ""), "why": f["proof"],
              "sessions": f["sessions"]} for f in data["facts"]["fields"]]
    heads = {w["slot"]: w["head"] for w in found}
    landed = barn.last_landed(main) if landed is None else landed
    todo = tick.fresh(wanted(data["plan"], heads), ctx.get("log", []), ctx["now"])
    mass = ("trim", "clean", "response")  # mass deletes: they wait for the gap between trains
    hold = building(main) if data["plan"].get("short") or any(a["kind"] in mass for a in todo) else None
    if hold:
        todo = [a for a in todo if a["kind"] not in mass]
    first = next((a for a in todo if a["kind"] == "remove"), None)  # one removal per round, the cars first
    todo = [a for a in todo if a["kind"] != "remove" or a is first]
    out = []
    if todo:
        fields = sorted({a["field"] for a in todo if a["kind"] != "response"})
        todo[0] = {**todo[0], "do": "run", "cwd": main, "on_fail": [failed("prune.py start failed")],
                   "argv": [sys.executable, str(Path(__file__).resolve()), "start", "--repo", main,
                            "--slot", Path(ctx.get("top", main)).name] + [x for f in fields for x in ("--field", f)]
                            + (["--responses"] if not fields else [])}
        out = todo
    elif asked:  # no run starts this round: the next round's plan is asked now (a run's start makes it stale)
        out = ask_next(main, ctx)
    return out + barn.actions(ctx, found, landed) + report(main, ctx, data, hold)


def handler(item: dict, ctx: dict) -> list[dict]:
    return plan(item, ctx)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=("plan", "ask", "start"))
    p.add_argument("--repo", default=".")
    p.add_argument("--slot")
    p.add_argument("--field", action="append", default=[])
    p.add_argument("--responses", action="store_true", help="the run does only /prune's watermark responses")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    main_dir = mtm_scan.main_checkout(args.repo)
    if args.cmd == "ask":
        return ask_and_save(main_dir)
    try:
        prune = script()
    except FileNotFoundError as e:
        print(f"prune.py: {e}", file=sys.stderr)
        return 2
    if args.cmd == "plan":
        return subprocess.call([sys.executable, str(prune), "plan", "--repo", main_dir, *(["--json"] * args.json)])
    return start(main_dir, args.slot or Path(args.repo).resolve().name, args.field, responses=args.responses)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
