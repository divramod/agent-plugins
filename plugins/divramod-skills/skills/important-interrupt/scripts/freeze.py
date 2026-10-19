#!/usr/bin/env python3
"""Freeze half of the important-interrupt skill: the build and test processes, the CI VMs and hal2-daemon.

A build or test root is a process named cargo, rustc, cargo-nextest, xcodebuild, swift-build, swift-test,
swift-frontend, bats or buildkitd, a node/bun running vitest or `playwright test` (never playwright-mcp, an agent's
browser), a pytest, or a docker build; it and every process below it (rustc, clang, ld, build scripts, the test
binaries) are frozen with SIGSTOP, undo SIGCONT, whoever started them. Kept: the calling session's process tree
(walked up to its `claude`, then everything below that), a root whose cwd is in a kept checkout, processes of other
users, already stopped ones (stat T) and zombies.
The CI VMs: every running tart VM is stopped (`tart stop <name>`, no undo: the daemon's VM node starts fresh ones on
continue); hal2-daemon itself is frozen first (SIGSTOP, undo SIGCONT) so it does not start them again (D5).
Every external call goes through one `Sys` (run, kill, cwd), so tests fake the whole machine.
"""
import json
import os
import re
import signal
import subprocess

BUILD_NAMES = ("cargo", "rustc", "cargo-nextest", "xcodebuild", "swift-build", "swift-test", "swift-frontend",
               "bats", "buildkitd")
JS_TESTS = re.compile(r"\bvitest\b|\bplaywright\S*\s+test\b")
DOCKER_BUILD = re.compile(r"\bdocker\b.*\b(build|buildx)\b")
DAEMON = re.compile(r"^hal2-daemon(-macos)?$")
STAT_SKIP = ("T", "Z")


class Sys:
    """The real machine: commands, signals, a process's cwd."""

    def run(self, cmd: list, timeout: float = 60) -> tuple:
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return p.returncode, p.stdout, p.stderr
        except FileNotFoundError as e:
            return 127, "", str(e)
        except subprocess.TimeoutExpired:
            return 124, "", f"timed out after {timeout}s"

    def kill(self, pid: int, sig: str) -> bool:
        try:
            os.kill(pid, getattr(signal, "SIG" + sig))
            return True
        except (ProcessLookupError, PermissionError):
            return False

    def cwd(self, pid: int) -> str:
        _, out, _ = self.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], timeout=10)
        return next((line[1:] for line in out.splitlines() if line.startswith("n")), "")


def proc_table(sys_: Sys) -> dict:
    """{pid: {pid, ppid, uid, stat, cpu, comm, args}}: comm (the executable) and args from two ps calls."""
    table = {}
    _, out, _ = sys_.run(["ps", "-axo", "pid=,ppid=,uid=,stat=,pcpu=,comm="])
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s+([\d.]+)\s+(.*)", line)
        if m:
            pid, ppid, uid, stat, cpu, comm = m.groups()
            table[int(pid)] = {"pid": int(pid), "ppid": int(ppid), "uid": int(uid), "stat": stat,
                               "cpu": float(cpu), "comm": comm.strip(), "args": comm.strip()}
    _, out, _ = sys_.run(["ps", "-axo", "pid=,args="])
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)\s+(.*)", line)
        if m and int(m.group(1)) in table:
            table[int(m.group(1))]["args"] = m.group(2)
    return table


def base(p: dict) -> str:
    return os.path.basename(p["comm"])


def children(table: dict) -> dict:
    kids = {}
    for p in table.values():
        kids.setdefault(p["ppid"], []).append(p["pid"])
    return kids


def below(table: dict, root: int) -> list:
    """root and every process below it, parents before children."""
    kids, out, todo = children(table), [], [root]
    while todo:
        pid = todo.pop(0)
        if pid in out:
            continue
        out.append(pid)
        todo.extend(sorted(kids.get(pid, [])))
    return out


def caller_tree(table: dict, start: int | None = None) -> set:
    """The calling session's processes: the chain up from start, and everything below its `claude`."""
    pid, chain = start or os.getpid(), []
    while pid in table and pid not in chain and pid > 1:
        chain.append(pid)
        if base(table[pid]) == "claude":
            return set(chain) | set(below(table, pid))
        pid = table[pid]["ppid"]
    return set(chain)


def is_root(p: dict) -> bool:
    name, args = base(p), p["args"]
    if name in BUILD_NAMES:
        return True
    if name in ("node", "bun") and JS_TESTS.search(args):
        return True
    if name == "pytest" or (name.startswith("python") and re.search(r"\bpytest\b", args)):
        return True
    return name == "docker" and bool(DOCKER_BUILD.search(args))


def under(path: str, dirs: list) -> bool:
    return any(path == d.rstrip("/") or path.startswith(d.rstrip("/") + "/") for d in dirs if d)


def builds(table: dict, keep_pids: set, keep_dirs: list, sys_: Sys, uid: int | None = None) -> list:
    """Rows of the build/test processes to freeze: every root and all below it, outermost root first."""
    uid = os.getuid() if uid is None else uid
    rows, seen = [], set(keep_pids)
    roots = [p for p in table.values() if is_root(p) and p["uid"] == uid and p["pid"] not in keep_pids]
    roots = [r for r in roots if not any(a in table and is_root(table[a]) for a in ancestors(table, r["pid"]))]
    for r in sorted(roots, key=lambda p: p["pid"]):
        if keep_dirs and under(sys_.cwd(r["pid"]), keep_dirs):
            seen.update(below(table, r["pid"]))
            continue
        for pid in below(table, r["pid"]):
            p = table[pid]
            if pid in seen or p["uid"] != uid or p["stat"][:1] in STAT_SKIP:
                continue
            seen.add(pid)
            rows.append({"kind": "build", "pid": pid, "root": r["pid"], "cpu": p["cpu"], "what": p["args"][:200]})
    return rows


def ancestors(table: dict, pid: int) -> list:
    out = []
    pid = table[pid]["ppid"] if pid in table else 0
    while pid in table and pid not in out and pid > 1:
        out.append(pid)
        pid = table[pid]["ppid"]
    return out


def daemon(table: dict, uid: int | None = None) -> list:
    """hal2-daemon, to freeze before its VMs are stopped (it starts new ones otherwise)."""
    uid = os.getuid() if uid is None else uid
    return [{"kind": "daemon", "pid": p["pid"], "cpu": p["cpu"], "what": p["args"][:200]}
            for p in table.values() if DAEMON.match(base(p)) and p["uid"] == uid and p["stat"][:1] not in STAT_SKIP]


def vms(sys_: Sys) -> list:
    """The running tart VMs (`tart list --format json`); none when tart is missing."""
    code, out, _ = sys_.run(["tart", "list", "--format", "json"])
    try:
        data = json.loads(out) if code == 0 else []
    except ValueError:
        data = []
    return [{"kind": "vm", "name": v["Name"], "what": f"tart VM {v['Name']}"} for v in data
            if isinstance(v, dict) and v.get("Name") and (v.get("Running") or v.get("State") == "running")]


def action(row: dict) -> tuple:
    """(do, undo, text): a signal pair ("STOP", pid) or an argv; undo None when nothing undoes it."""
    if row["kind"] == "vm":
        return ["tart", "stop", row["name"]], None, f"stop {row['what']}"
    label = "hal2-daemon" if row["kind"] == "daemon" else "build"
    return ("STOP", row["pid"]), ("CONT", row["pid"]), f"freeze {label} {row['pid']} ({row['what'][:80]})"


def show(step) -> str:
    return f"kill -{step[0]} {step[1]}" if isinstance(step, tuple) else " ".join(step)


def perform(step, sys_: Sys) -> bool:
    if isinstance(step, tuple):
        return sys_.kill(step[1], step[0])
    return sys_.run(step)[0] == 0


def apply(rows: list, sys_: Sys, dry: bool, out=print) -> list:
    """Do every row's action (or print it with --dry-run); return the record entries of what was done."""
    done = []
    for row in rows:
        do, undo, text = action(row)
        ok = True if dry else perform(do, sys_)
        out(f"{'would ' if dry else ''}{text}: {show(do)}{'' if ok else '  (failed)'}")
        if ok and not dry:
            done.append({"text": text, "kind": row["kind"], "do": list(do) if isinstance(do, tuple) else do,
                         "undo": list(undo) if isinstance(undo, tuple) else undo})
    return done


def cpu_idle(sys_: Sys) -> float | None:
    """The CPU idle percent of top's second sample (the first one averages since boot)."""
    _, out, _ = sys_.run(["top", "-l", "2", "-n", "0"], timeout=30)
    found = re.findall(r"CPU usage:.*?([\d.]+)% idle", out)
    return float(found[-1]) if found else None


def busiest(table: dict, n: int = 5) -> list:
    """The n processes costing the most CPU, for the report when the machine did not get quiet."""
    top = sorted((p for p in table.values() if p["cpu"] >= 1), key=lambda p: -p["cpu"])[:n]
    return [f"{p['pid']} {p['cpu']:.0f}% {p['args'][:60]}" for p in top]
