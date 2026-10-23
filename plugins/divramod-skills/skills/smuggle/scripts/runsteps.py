"""The run steps of `units.py run` (hal2 plan 0420 step 3, shot 14 of skill-mtm).

With SMUGGLE_RUN_LOGS set (hal2-git's smuggle names the folder), each command of a lane is a step of the smuggle's
run, written as code/bash/scripts/smuggle/checks.sh writes its lanes: `== <step>` into `<lane>.log`, then
`<step> start <utc>` into `<lane>.jobs`, the command's output into `<lane>.log` as it comes, and
`<step> end <utc> <exit> [cpu=<s>] [load0=<l>] [load1=<l>] [sccache=<h>/<m>] [key=<k>]` (a job green before:
`<step> skipped <utc> key=<k>`); hal2-git's lane follower turns them into steps whose message holds the measures. The
lane's output then reaches the terminal only when a command is red (the lane's log whole, as checks.sh prints a red
lane). Without the folder a command runs as ever, its output on the terminal.
"""

import datetime
import json
import os
import re
import resource
import shutil
import subprocess
import sys


def utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def step_name(text):
    """A step's name: one word (the follower's marker `== <name>`)."""
    return re.sub(r"[^A-Za-z0-9._]+", "-", text).strip("-")[:48].strip("-") or "step"


def cpu():
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def load():
    try:
        return f"{os.getloadavg()[0]:.2f}"
    except OSError:
        return None


def sccache(rust):
    """(hits, misses) of the sccache server for a Rust command; None for another or without sccache."""
    program = os.environ.get("SMUGGLE_SCCACHE", "sccache")
    if not rust or not program or not shutil.which(program):
        return None
    try:
        out = subprocess.run([program, "--show-stats", "--stats-format", "json"], capture_output=True, text=True,
                             check=False, timeout=30)
        stats = json.loads(out.stdout)["stats"]
        return (sum(stats["cache_hits"]["counts"].values()), sum(stats["cache_misses"]["counts"].values()))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.TimeoutExpired):
        return None


class Lane:
    """One lane of the run: its steps in `<lane>.jobs`, its output in `<lane>.log`."""

    def __init__(self, lane, env=None):
        folder = (env if env is not None else os.environ).get("SMUGGLE_RUN_LOGS")
        self.dir = folder or None
        self.lane = lane
        if self.dir:
            os.makedirs(self.dir, exist_ok=True)

    def _append(self, ext, text):
        with open(os.path.join(self.dir, f"{self.lane}.{ext}"), "a", encoding="utf-8") as out:
            out.write(text)

    def skipped(self, step, key):
        if self.dir:
            self._append("jobs", f"{step} skipped {utc()} key={key}\n")

    def run(self, step, argv, cwd, env, key=None, rust=False):
        """Runs <argv> as step <step>; its exit code. The caller prints its own `== ...` line."""
        if not self.dir:
            return subprocess.run(argv, cwd=cwd, env=env, check=False).returncode
        self._append("log", f"== {step}\n")
        self._append("jobs", f"{step} start {utc()}\n")
        cpu0, load0, sc0 = cpu(), load(), sccache(rust)
        with open(os.path.join(self.dir, f"{self.lane}.log"), "a", encoding="utf-8") as log:
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, errors="replace")
            for line in proc.stdout:
                log.write(line)
                log.flush()
            code = proc.wait()
        extras = [f"cpu={max(cpu() - cpu0, 0):.1f}"]
        load1 = load()
        extras += [f"load0={load0}"] if load0 else []
        extras += [f"load1={load1}"] if load1 else []
        sc1 = sccache(rust)
        if sc0 and sc1:
            extras.append(f"sccache={sc1[0] - sc0[0]}/{sc1[1] - sc0[1]}")
        extras += [f"key={key}"] if key else []
        self._append("jobs", f"{step} end {utc()} {code} {' '.join(extras)}\n")
        if code != 0:
            with open(os.path.join(self.dir, f"{self.lane}.log"), encoding="utf-8", errors="replace") as log:
                sys.stdout.write(log.read())
            sys.stdout.flush()
        return code
