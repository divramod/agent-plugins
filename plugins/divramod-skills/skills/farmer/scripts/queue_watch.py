#!/usr/bin/env python3
"""The merge-queue watch, a farmer tick duty (hal2 plan 0570 step 5, D8; the user, 2026-11-02: "watching the merge
queue with this possible error should also be a duty of all 3 farmers"). Read-only on the queue: it never orders,
clears or lands anything; the woken farmer acts (instructions/queue.md).

  queue_watch.py --repo-dir <any checkout of the farm> [--json]
      one line per finding, nothing when the queue is healthy (`--json`: the lines as a JSON list), as the old
      ~/.local/share/hal2-watch/queuewatch.py printed them; exit 0 healthy, 1 findings, 2 the queue unreadable.
      Writes nothing.

Findings, read from `hal2-cli-git worktree queue --json` (only the front of the queue blocks; a reserved ticket
further back that idles is harmless):

  IDLE-RESERVATION  a place at the front with no landing running (no live pid, no running harvest), reserved or
                    without a pid, while others wait > 15 min; never the tollman's train between its red run and its
                    rerun (open fix orders, a fixed-wait: `train_between_runs`, plan 0695 D43; a started landing
                    finishes, merge-queue-policy), which is busy and gets no advice to clear its reservation
  DEAD-HOLDER       the same, but the holder had a pid that is gone
  STALLED-GATE      the holder's landing sits in one step > 45 min AND its gate does not move: no job started or
                    finished for MOVE_MIN, or a job queued beside an idle runner with its labels (queue_gate.py;
                    all runners busy and jobs finishing is a slow lane, no finding; gate unreadable: by time alone)
  NOT-MOVING        the same holder's landing runs > 60 min with others waiting
  STALLED-PUSH      the holder's landing or train is still in its local phase (merge-from-main, candidate, own-cli,
                    push: no land run yet, `run_url` empty) > 20 min (hal2 plan 0695 step 20, D25, tollman L259);
                    alarmed once as soon as the next tick still sees it (push only, `queue-stalled-push`)

The duty (`plan_queue`, `farmer.HANDLERS["duty:queue"]`) keeps each finding's first-seen time in the farmer's state
folder (`queue-watch.json`: `{schema 1, at, findings: {<KIND> <repo>/<worktree>: {kind, repo, slot, first_seen,  names-ok: the queue JSON key
alarmed, line}}}`, UTC, replaced atomically every real round, a finding that went away dropped; a dry round writes
nothing). A new finding wakes the farmer once; one lasting > 30 min runs `alarm.py` once (STALLED-GATE as the stuck
case `runner-down`, which rings; the others as `queue-<kind>`, which only push: the user named four stuck cases).
"""

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import bounded
import mtm_scan
import queue_gate
import roletime
from skillpath import sibling

IDLE_MIN, STEP_MIN, HOLD_MIN = 15, 45, 60
LOCAL_MIN = 20  # a landing without its land run (the local phase) this long is stalled
ALARM_AFTER = {"STALLED-PUSH": 0}  # kinds that alarm at their second sighting, not after ALARM_MIN
ALARM_MIN = 30  # a finding lasting this long reaches the user (alarm.py)
SCHEMA = 1
FILE = "queue-watch.json"
QUEUE = ["hal2-cli-git", "worktree", "queue", "--json"]
ALARM = Path(__file__).resolve().parent / "alarm.py"
TOLLMAN = sibling("tollman") / "scripts" / "tollman.py"
CASE = {"STALLED-GATE": "runner-down"}  # the one finding that is a stuck case; the others push only
FIX = {
    "IDLE-RESERVATION": "clear the order and tell the field it gets first place when ready (never a started "
                        "landing's or a train's between its runs)",
    "DEAD-HOLDER": "tell the field to run /mtm again",
    "STALLED-GATE": "look at its run, a runner problem: fix the runner",
    "STALLED-PUSH": "look at its local phase (own-cli build, push): a load or a hung command, tell the field",
    "NOT-MOVING": "find out why: one of the others, or a red gate",
}
_UNSET = object()


def mins(ts, now: dt.datetime) -> float:
    """Minutes from the stamp `ts` to `now`; 0 for none or one that does not parse."""
    t = roletime.parse(ts) if ts else None
    return (now - t).total_seconds() / 60 if t else 0.0


def finding(kind: str, head: dict, line: str) -> dict:
    repo, slot = str(head.get("repo") or "-"), str(head.get("slot") or "-")
    return {"kind": kind, "repo": repo, "slot": slot, "key": f"{kind} {repo}/{slot}",
            "line": f"{kind} {repo}/{slot}: {line}", "fix": FIX[kind]}


def gate_stalled(state: dict | None) -> bool:
    """Whether a gate's state (queue_gate.gate_state) is a stall; unknown (None) counts as one: judged by time alone."""
    if state is None:
        return True
    idle = state.get("idle_min")
    return bool(state.get("waits_beside_idle")) or idle is None or idle > queue_gate.MOVE_MIN


TRAIN_OPEN = ("red", "fixing", "retry")  # a train's states between its red run and its rerun (train_fold)


def train_between_runs(main: str, runner=None) -> bool:
    """Is the tollman's train between its red run and its rerun: in the state `red`, `fixing` or `retry`, or with open
    fix orders (`tollman.py state --json`, schema 1)? Unreadable: no. `runner(argv, cwd) -> stdout` for tests."""
    argv = [sys.executable, str(TOLLMAN), "state", "--json", "--repo", main]
    try:
        out = runner(argv, main) if runner else bounded.run(argv, cwd=main).stdout
        doc = json.loads(out)
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
        return False
    if not isinstance(doc, dict):
        return False
    train = doc.get("train")
    return bool((isinstance(train, dict) and train.get("state") in TRAIN_OPEN) or doc.get("orders"))


def findings(queue: list[dict], now: dt.datetime, alive=mtm_scan.pid_alive, gate=None, between=None) -> list[dict]:
    """The queue's findings at `now` (aware); `alive(pid) -> bool` asks whether the holder's process lives;
    `gate(run_url) -> state | None` reads the land run's gate (None: not asked, STALLED-GATE by time alone);
    `between() -> bool` whether a train waits for its rerun (asked only when the tollman's train would be idle)."""
    if not queue:
        return []
    now, head, waiting = roletime.aware(now), queue[0], queue[1:]
    oldest = max((mins(e.get("enqueued"), now) for e in waiting), default=0)
    h = head.get("harvest") or {}
    running = h.get("outcome") == "running" and not h.get("finished")
    out = []
    if waiting and not running and not alive(head.get("pid")) and oldest > IDLE_MIN:
        idle = head.get("reserved") or (head.get("hold") or {}).get("reason") == "reserved" or not head.get("pid")
        kind = "IDLE-RESERVATION" if idle else "DEAD-HOLDER"
        train = str(head.get("slot") or "").startswith("tollman") and between is not None and between()
        if not (train and kind == "IDLE-RESERVATION"):  # a train between its runs is busy (plan 0695 D43)
            out.append(finding(kind, head, f"holds the front with no landing running while {len(waiting)} wait "
                                           f"(oldest {oldest:.0f} min): {FIX[kind]}"))
    if running and not h.get("run_url") and mins(h.get("started"), now) > LOCAL_MIN:
        out.append(finding("STALLED-PUSH", head, f"local phase ({h.get('step')}) for "
                                                 f"{mins(h.get('started'), now):.0f} min, no land run yet: "
                                                 f"{FIX['STALLED-PUSH']}"))
    if (running and h.get("run_url") and mins(h.get("step_started"), now) > STEP_MIN
            and gate_stalled(gate(h["run_url"]) if gate else None)):
        out.append(finding("STALLED-GATE", head, f"step {h.get('step')} for {mins(h.get('step_started'), now):.0f} "
                                                 f"min, {h.get('jobs_green')}/{h.get('jobs')} jobs green, "
                                                 f"{h.get('run_url')}"))
    if waiting and running and mins(h.get("started"), now) > HOLD_MIN:
        out.append(finding("NOT-MOVING", head, f"landing since {mins(h.get('started'), now):.0f} min, "
                                               f"{len(waiting)} wait behind it"))
    return out


def read_queue(repo: str, runner=None) -> tuple[list[dict] | None, str]:
    """(the queue's tickets, "") or (None, why) when `hal2-cli-git worktree queue --json` gives no queue. Bounded
    like every hal2-cli-git call of a tick (bounded.run, the limit under tick.sh; stdout alone, so a warning on
    stderr never spoils the JSON). `runner(argv, cwd) -> (code, stdout, stderr)` for tests."""
    if runner is None:
        def runner(argv, cwd):
            try:
                p = bounded.run(argv, cwd=cwd)
                return p.returncode, p.stdout, p.stderr
            except (OSError, subprocess.TimeoutExpired) as exc:
                return 127, "", str(exc)
    code, out, err = runner(QUEUE, repo)
    queue, why = tickets(parse(out))
    return (queue, "") if queue is not None else (None, (err or why or f"exit {code}").strip()[:200])


def parse(text: str):
    try:
        return json.loads(text) if text and text.strip() else None
    except json.JSONDecodeError:
        return None


def tickets(doc) -> tuple[list[dict] | None, str]:
    """The `queue` list of a queue document, or (None, why)."""
    queue = doc.get("queue") if isinstance(doc, dict) else None
    return (queue, "") if isinstance(queue, list) else (None, "no `queue` list in the answer")


def state_file(main: str) -> Path:
    return mtm_scan.state_dir(main) / FILE


def load(main: str) -> dict:
    """The kept findings by key; {} for a missing, unreadable or foreign-schema file."""
    try:
        data = json.loads(state_file(main).read_text())
    except (OSError, ValueError):
        return {}
    kept = data.get("findings") if isinstance(data, dict) and data.get("schema") == SCHEMA else None
    return {k: v for k, v in kept.items() if isinstance(v, dict)} if isinstance(kept, dict) else {}


def save(main: str, kept: dict, now: dt.datetime) -> None:
    """Replace the snapshot atomically: a temp file in the same folder, then a rename."""
    path = state_file(main)
    fd, tmp = tempfile.mkstemp(prefix=f".{FILE}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps({"schema": SCHEMA, "at": roletime.stamp(now), "findings": kept}) + "\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def track(kept: dict, found: list[dict], now: dt.datetime) -> tuple[dict, list[dict], list[dict]]:
    """(the new kept findings, the new ones, the ones to alarm now): first-seen carried, gone ones dropped, a finding
    lasting > ALARM_MIN alarmed once (its `alarmed` stamp set)."""
    now, out, new, due = roletime.aware(now), {}, [], []
    for f in found:
        old = kept.get(f["key"]) or {}
        first = old.get("first_seen") if roletime.parse(old.get("first_seen")) else None
        entry = {"kind": f["kind"], "repo": f["repo"], "slot": f["slot"], "first_seen": first or roletime.stamp(now),
                 "alarmed": old.get("alarmed") if first else None, "line": f["line"]}
        if first is None:
            new.append({**f, "first_seen": entry["first_seen"]})
        elif not entry["alarmed"] and mins(first, now) > ALARM_AFTER.get(f["kind"], ALARM_MIN):
            entry["alarmed"] = roletime.stamp(now)
            due.append({**f, "first_seen": first, "minutes": round(mins(first, now))})
        out[f["key"]] = entry
    return out, new, due


def alarm_argv(f: dict, main: str) -> list[str]:
    case = CASE.get(f["kind"], "queue-" + f["kind"].lower())
    reason = f"{f['line']} (for {f['minutes']} min); do: {f['fix']}"
    return [sys.executable, str(ALARM), case, reason, "--repo", main, "--slot", f["slot"]]


def plan_queue(item: dict, ctx: dict, queue=_UNSET, alive=mtm_scan.pid_alive, gate=_UNSET) -> list[dict]:
    """The duty's acts: a wake per new finding, an alarm run per finding past ALARM_MIN; the state saved unless the
    round is dry. The queue is the round's (`ctx["queue_doc"]`, tick.context), else read here; unreadable: no acts."""
    from tick import act
    main = ctx["main"]
    if queue is _UNSET:
        queue = tickets(ctx["queue_doc"])[0] if "queue_doc" in ctx else read_queue(main)[0]
    if queue is None:
        return []
    if gate is _UNSET:  # read lazily, only for a gate past STEP_MIN (two GETs); a dry round asks GitHub too
        gate = lambda url: queue_gate.gate_state(url, ctx["now"], mtm_scan.run_json, main)  # noqa: E731
    between = ctx.get("train_between") or (lambda: train_between_runs(main))
    kept, new, due = track(load(main), findings(queue, ctx["now"], alive, gate, between), ctx["now"])
    if not ctx.get("dry"):
        save(main, kept, ctx["now"])
    out = [act("queue", f["kind"].lower(), "wake", "-", key=f"queue:{f['key']}:{f['first_seen']}",
               text=f"{f['line']}; do: {f['fix']}", evidence=f) for f in new]
    out += [act("queue", "alarm", "run", "-", key=f"queue-alarm:{f['key']}:{f['first_seen']}",
                argv=alarm_argv(f, main), text=f"alarm: {f['line']} (for {f['minutes']} min)") for f in due]
    return out


def main(argv: list[str] | None = None, runner=None, now: dt.datetime | None = None, gate=_UNSET) -> int:
    p = argparse.ArgumentParser(prog="queue_watch.py", description="The merge queue's findings, read-only.")
    p.add_argument("--repo-dir", default=os.getcwd(), help="any checkout of the farm")
    p.add_argument("--json", action="store_true", help="the lines as a JSON list")
    args = p.parse_args(argv)
    queue, why = read_queue(args.repo_dir, runner)
    if queue is None:
        print(f"QUEUE-UNREADABLE {args.repo_dir}: {why}")
        return 2
    when = now or roletime.utcnow()
    if gate is _UNSET:
        gate = lambda url: queue_gate.gate_state(url, when, mtm_scan.run_json, args.repo_dir)  # noqa: E731
    lines = [f["line"] for f in findings(queue, when, gate=gate)]
    print(json.dumps(lines) if args.json else "\n".join(lines), end="\n" if args.json or lines else "")
    return 1 if lines else 0


if __name__ == "__main__":
    sys.exit(main())
