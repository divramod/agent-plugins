"""What quiet.py asks the machine, every call under a timeout (plan 0585 D6, D12): a probe that hangs (`xcrun simctl`
did, 30 s on a loaded Mac) or an action that blocks (launchctl, docker) is killed with its process group and reported,
never fatal. One `ps` table per pass, the agents' cwds in one batched `lsof`, simulators asked only when a simulator
runs. quiet.py imports these and keeps the old names."""
import os
import plistlib
import re
import signal
import subprocess
import urllib.request
from pathlib import Path

PROBE = 15  # seconds a read-only probe may take
ACTION = 20  # seconds one action (launchctl, docker, simctl) may take
SIMCTL = 8
OLLAMA = "http://127.0.0.1:11434"
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
NEVER_BOOTOUT = ("local.hal2.daemon",)  # the kept session's tools may need it


def call(argv: list, timeout: float) -> tuple:
    """(returncode, stdout) with the child's whole process group killed at the timeout; (124, "") on a timeout,
    (127, "") when the program is missing."""
    try:
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                             start_new_session=True)
    except OSError:
        return 127, ""
    try:
        out = p.communicate(timeout=timeout)[0]
        return p.returncode, out
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            p.kill()
        try:
            p.communicate(timeout=2)
        except (subprocess.TimeoutExpired, OSError):
            pass
        return 124, ""


def run(argv: list, timeout: float = PROBE) -> str:
    return call(argv, timeout)[1]


def run_step(argv: list, timeout: float = ACTION) -> bool | None:
    """An action's argv: True done, False failed, None timed out (the child killed)."""
    code, _ = call(argv, timeout)
    return None if code == 124 else code == 0


def procs() -> dict:
    table = {}
    for line in run(["ps", "-Ao", "pid=,ppid=,pcpu=,rss=,stat=,command="]).splitlines():
        m = re.match(r"\s*(\d+)\s+(\d+)\s+([\d.]+)\s+(\d+)\s+(\S+)\s+(.*)", line)
        if m:
            pid, ppid, cpu, rss, stat, cmd = m.groups()
            table[int(pid)] = {"pid": int(pid), "ppid": int(ppid), "cpu": float(cpu), "rss_mb": int(rss) // 1024,
                               "stat": stat, "cmd": cmd}
    return table


def cwds(pids: list) -> dict:
    """{pid: cwd} of all pids in one lsof call (a pid lsof cannot see is left out)."""
    if not pids:
        return {}
    found, pid = {}, None
    for line in run(["lsof", "-a", "-p", ",".join(map(str, pids)), "-d", "cwd", "-Fpn"]).splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pid = int(line[1:])
        elif line.startswith("n") and pid is not None:
            found.setdefault(pid, line[1:])
    return found


def ollama_running() -> bool:
    try:
        urllib.request.urlopen(OLLAMA + "/api/ps", timeout=3)
        return True
    except OSError:
        return False


def timer_agents(runner: bool, listing: str | None = None) -> list:
    loaded = {}
    for line in (run(["launchctl", "list"]) if listing is None else listing).splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) == 3:
            loaded[parts[2]] = parts[0]
    found = []
    for plist in sorted(LAUNCH_AGENTS.glob("*.plist")):
        try:
            data = plistlib.loads(plist.read_bytes())
        except Exception:
            continue
        label = data.get("Label", "")
        if label not in loaded or label in NEVER_BOOTOUT:
            continue
        if label.startswith("actions.runner."):
            found.append(("runner" if runner else "report", label, str(plist), "self-hosted CI runner"))
        elif "StartInterval" in data or "StartCalendarInterval" in data:
            every = f"every {data['StartInterval']} s" if "StartInterval" in data else "on a calendar"
            found.append(("agent", label, str(plist), every))
    return found


def simulator_rows(table: dict) -> list:
    """Booted simulators. `xcrun simctl` is asked only when a simulator process (launchd_sim) runs: with none it
    answers nothing but may hang for the whole timeout."""
    if not any("launchd_sim" in p["cmd"].split(" ", 1)[0] for p in table.values()):
        return []
    rows = []
    for line in run(["xcrun", "simctl", "list", "devices", "booted"], SIMCTL).splitlines():
        m = re.match(r"\s+(.+?) \(([0-9A-F-]{36})\) \(Booted\)", line)
        if m:
            rows.append({"kind": "simulator", "udid": m.group(2), "what": f"simulator {m.group(1)}"})
    return rows


def container_rows() -> list:
    rows = []
    for line in run(["docker", "ps", "--format", "{{.ID}} {{.Names}}"]).splitlines():
        if line.strip():
            cid, name = line.split(" ", 1)
            rows.append({"kind": "docker", "id": cid, "what": f"container {name}"})
    return rows
