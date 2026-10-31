"""The pretest's processes (hal2 plan 0349 step 28, D75): the gate's `list` and `plan` and its jobs, each in a process
group of its own, so a timeout, a red or the end of the landing's process stops all of it, a cargo build a gate
call started included. POSIX only, like engine.spawn (process groups, killpg).

A job runs as merge-to-main.yml's gate action runs it (.github/actions/gate/action.yml): `gate/main.sh <job>` from the
field's root with the plan entry's packages and targets and the range in its environment, and HAL2_GATE_NO_INSTALL
(gate/tools.sh: `need` installs nothing on the user's Mac, it prints `gate: tool missing: <tool>` and fails). Its
end: 0 green; the tool marker in its output, or a signal no one here sent: skipped; any other code red.

Plan 0490 step 9: a job sees a runner's environment (CI_ENV: CI, GITHUB_ACTIONS, CARGO_INCREMENTAL=0; L114, L116,
L120), unless its config says `ci_env = false` (the entry's `plain`: a job whose CI branch differs on a Mac, or that
builds in the checkout's own target, whose fingerprint CARGO_INCREMENTAL would flip). No CARGO_TARGET_DIR: a scratch
target turns the warm build of the checkout cold. A red whose output shows this Mac's fault (transient.MAC, a dyld
`Library not loaded`, L101) is skipped, never a car's. A red whose output is only a test timeout (timeout_only, L27)
runs again once, within the budget; red again it says load-flaky.
"""

import contextlib
import os
import re
import signal
import subprocess
import time
from pathlib import Path

import transient

POLL = 0.1
TOOL = "gate: tool missing:"
CI_ENV = {"CI": "true", "GITHUB_ACTIONS": "true", "CARGO_INCREMENTAL": "0"}
TIMEOUT = re.compile(r"Test timed out in \d+ ?ms|timed out after \d+ ?ms|Exceeded timeout of \d+ ?ms", re.IGNORECASE)
OTHER = re.compile(r"AssertionError|AssertError|error TS\d+|error\[E\d+\]|SyntaxError|ReferenceError|panicked at|"
                   r"expected .+ (to |but )", re.IGNORECASE)
FAILED = re.compile(r"^\s*Tests?\s+(\d+) failed|^\s*(\d+) fail\b", re.MULTILINE)
AGAIN = "a test timeout: run again once (L27)"
FLAKY = "a test timeout twice: load-flaky (flaky_brief.py place)"
MAC = "the Mac's, not a car's (L101: brew reinstall the tool)"


def environment(entry: dict, base: str, head: str) -> dict:
    """What merge-to-main.yml's gate action exports for a job, and the gate's switch that installs nothing."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HAL_CHANGED_", "HAL_GATE_", "HAL_PACKAGE_"))}
    for key, name in (("packages", "HAL_CHANGED_PACKAGES"), ("targets", "HAL_CHANGED_TARGETS")):
        if entry.get(key, "*") != "*":
            env[name] = entry[key]
    if entry.get("plain"):  # a plain job runs as on the Mac, also when the pretest itself runs on a CI runner
        env = {k: v for k, v in env.items() if k not in CI_ENV}
    return {**env, **({} if entry.get("plain") else CI_ENV), "HAL_GATE_BASE": base, "HAL_GATE_HEAD": head,
            "HAL2_GATE_NO_INSTALL": "1"}


def timeout_only(text: str) -> bool:
    """The output's failures are test timeouts only: a timeout line, no assertion or compile error, and no more
    failed tests than timeouts where a summary counts them (vitest, bun)."""
    timeouts = len(TIMEOUT.findall(text))
    failed = [int(a or b) for a, b in FAILED.findall(text)]
    return bool(timeouts) and not OTHER.search(text) and (not failed or max(failed) <= timeouts)


def stop(p: subprocess.Popen) -> None:
    """A process's whole group: TERM, then KILL after two seconds."""
    for sig, wait in ((signal.SIGTERM, 2), (signal.SIGKILL, 5)):
        try:
            os.killpg(p.pid, sig)
        except (ProcessLookupError, PermissionError):
            break
        try:
            p.wait(wait)
            return
        except subprocess.TimeoutExpired:
            continue
    with contextlib.suppress(subprocess.TimeoutExpired):
        p.wait(1)  # reaped, also when its group was gone already


def call(argv: list[str], cwd: str, timeout: float, env: dict | None = None) -> tuple[int, str, str]:
    """A gate call in its own group (`env` added to this process's): its code, stdout and stderr; at the timeout (or
    any interruption) the whole group is stopped and the exception goes on."""
    with subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, start_new_session=True, env={**os.environ, **env} if env else None) as p:
        try:
            out, err = p.communicate(timeout=timeout)
        except BaseException:
            stop(p)
            raise
    return p.returncode, out, err


def start(top: str, gate: Path, e: dict, base: str, head: str, row: dict) -> subprocess.Popen | None:
    """The job's process in a group of its own, its output in its row's file; None: it cannot start (why in row)."""
    try:
        with row["out"].open("a" if row.get("retries") else "w") as out:
            return subprocess.Popen(["bash", str(gate), e["job"]], cwd=top, stdin=subprocess.DEVNULL, stdout=out,
                                    stderr=subprocess.STDOUT, env=environment(e, base, head), start_new_session=True)
    except OSError as err:
        row["why"] = f"cannot start: {err}"
        return None


def output(row: dict) -> str:
    try:
        return row["out"].read_text(errors="replace")
    except OSError:
        return ""


def finished(row: dict, code: int, seconds: float) -> str:
    """A job's end in its row (the module doc); its name when it is red."""
    text = output(row) if code else ""
    tools = [line.strip() for line in text.splitlines() if line.strip().startswith(TOOL)]
    mac = transient.MAC.search(text) if code > 0 and not tools else None
    if code < 0 or (code and tools) or mac:
        row.update(seconds=seconds, why=f"killed by signal {-code} from outside" if code < 0 else "; ".join(tools)
                   or f"{MAC}: {mac[0]}"[:300])
        return ""
    flaky = code and row.get("retries") and timeout_only(text)
    row.update(state="run", seconds=seconds, result="red" if code else "green",
               why=(f"exit {code}" + (f": {FLAKY}" if flaky else "")) if code else "")
    return row["job"] if code else ""


def again(row: dict) -> bool:
    """A red row whose output is only a test timeout, not run again yet: set back to wait for its second run."""
    if row.get("retries") or row.get("result") != "red" or not timeout_only(output(row)):
        return False
    row.update(retries=1, state="skipped", result=None, why=f"{AGAIN}; the budget ended before it ran again")
    return True


def run_jobs(top: str, gate: Path, todo: list[dict], base: str, head: str, deadline: float, parallel: int,
             scratch: Path, groups: dict | None = None, progress: dict | None = None) -> list[dict]:
    """Each entry of `todo` as a gate job: its row {job, key, state, seconds, result, why, out}, at most `parallel`
    at once, a job whose group ({job: group}) has one running waiting for it. The first red stops the rest; the
    deadline stops all; whatever ends this (an exception, SIGTERM as SystemExit) stops every job still running.
    `progress["red"]` names the red job as soon as it is known."""
    groups, progress, entries = groups or {}, progress if progress is not None else {}, {e["job"]: e for e in todo}
    rows = {e["job"]: {"job": e["job"], "key": e.get("key"), "state": "skipped", "seconds": 0, "result": None,
                       "why": "the budget ended before it started", "out": scratch / f"{e['job']}.log"} for e in todo}
    waiting, running, red, stopped = list(todo), {}, "", "the pretest ended while it ran"
    try:
        while True:
            for job, (p, began) in list(running.items()):
                if (code := p.poll()) is not None:
                    del running[job]
                    ended = finished(rows[job], code, round(time.monotonic() - began, 1))
                    if ended and again(rows[job]):
                        waiting.insert(0, entries[job])  # L27: once more, first in line
                        ended = ""
                    red = red or ended
            if red:
                progress["red"] = red
            if red or time.monotonic() >= deadline:
                stopped = f"stopped: {red} is red" if red else "the budget ended while it ran"
                for e in waiting if red else []:
                    rows[e["job"]]["why"] = f"not started: {red} is red"
                break
            busy = {groups[j] for j in running if j in groups}
            while len(running) < parallel and (free := [e for e in waiting if groups.get(e["job"]) not in busy]):
                e = free[0]
                waiting.remove(e)
                busy |= {groups[e["job"]]} if e["job"] in groups else set()
                if p := start(top, gate, e, base, head, rows[e["job"]]):
                    running[e["job"]] = (p, time.monotonic())
            if not running and not waiting:
                break
            time.sleep(POLL)
    finally:
        for job, (p, began) in running.items():
            stop(p)
            rows[job].update(seconds=round(time.monotonic() - began, 1), why=stopped)
    return [rows[e["job"]] for e in todo]
