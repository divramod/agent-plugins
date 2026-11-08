"""The throwaway fields of the live ack check (hal2 plan 0731 D15, acks_live.py): which field 90-99 is free, how one
is removed (never forced), and the bounded wait both use. `lv` is acks_live.Live."""

import json
import os
import signal
from pathlib import Path

FIELDS = tuple(str(n) for n in range(90, 100))
POLL = 5
STOP_WAIT = 120


def kill(pid: int, sig: int) -> bool:
    """os.kill; False when the process is gone."""
    try:
        os.kill(pid, sig)
        return True
    except ProcessLookupError:
        return False


def until(lv: Live, wait: int, probe):
    """`probe()` every POLL seconds until it returns something true or `wait` seconds passed (None)."""
    end = lv.clock() + wait
    while True:
        got = probe()
        if got or lv.clock() >= end:
            return got or None
        lv.sleep(POLL)


def fields(lv: Live) -> set[str]:
    """The names of the repository's worktrees (`git worktree list`)."""
    _, out, _ = lv.call("git", "-C", lv.main, "worktree", "list", "--porcelain")
    return {Path(line[9:]).name for line in out.splitlines() if line.startswith("worktree ")}


def paused(lv: Live) -> set[str]:
    code, out, _ = lv.call("hal2-cli-git", "worktree", "paused", "--json")
    try:
        return {f["field"] for f in json.loads(out)["fields"]} if code == 0 else set(FIELDS)
    except (ValueError, KeyError, TypeError):
        return set(FIELDS)  # unreadable: take none


def free_field(lv: Live) -> str | None:
    """The first field 90-99 with no worktree, no branch (local or on origin) and no pause record: a paused field is
    never started by a program (paused-fields-never-woken), a removed field's record stays (step 1's 90, 92, 93)."""
    taken = fields(lv) | paused(lv)
    for nn in FIELDS:
        if nn in taken:
            continue
        code, out, _ = lv.call("git", "-C", lv.main, "branch", "-a", "--list", nn, f"origin/{nn}")
        if code == 0 and not out.strip():
            return nn
    return None


def remove(lv: Live, nn: str, pane: str = "") -> str:
    """`worktree remove --remote --stop`, never forced. Its `--stop` refuses a busy agent (listed `starting` or
    `working`: a grok or codex that never leaves `starting`, an opencode still turning after its ack): then this
    run's own host (`t:<id>`, its pid from the host record) is ended by SIGTERM and the removal tried once more; the
    removal's own proof of nothing unsaved stays. `hal2-cli-agents stop --force` would pause the field for good."""
    argv = ("hal2-cli-git", "worktree", "remove", nn, "--remote", "--stop", "--json")
    code, out, err = lv.call(*argv, timeout=STOP_WAIT)
    if code and pane.startswith("t:") and "busy" in out + err and end_host(lv, pane[2:]):
        code, out, err = lv.call(*argv, timeout=STOP_WAIT)
        if code == 0 and nn not in fields(lv):
            return "y (own host ended first: --stop refused a busy agent)"
    if code == 0 and nn not in fields(lv):
        return "y"
    return f"refused ({code}): {(err or out).strip()[-200:]}"


def end_host(lv: Live, tid: str) -> bool:
    """SIGTERM to the terminal host `tid` this run started; True once it is gone (at most STOP_WAIT)."""
    try:
        pid = int(json.loads((lv.terminals / f"{tid}.json").read_text())["host_pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if not lv.kill(pid, signal.SIGTERM):
        return True
    return bool(until(lv, STOP_WAIT, lambda: not lv.kill(pid, 0)))
