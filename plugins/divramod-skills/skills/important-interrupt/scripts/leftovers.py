"""The report "still running" after the stop settles (plan 0585 step 4, D5, D6): what the interrupt leaves alone and may
still load the Mac, one line each, never stopped: the CPU top 5, the network's top 5 talkers (nettop), Docker
Desktop's VM, Time Machine (tmutil status), Spotlight (mds, mdworker) and Chrome (its helper processes). Every probe
runs through the Sys under a timeout; a missing tool or a timeout is one line, never fatal. `report` returns the items
(`{"item", "text", ...}`) for the stop record's `leftovers` and prints them through `d.out`.
"""
import re

import freeze

NETTOP_TIMEOUT, TM_TIMEOUT = 30, 10
CPU_MIN = 1.0  # a process under this many percent is no load worth naming
DOCKER_VM = re.compile(r"com\.docker\.(virtualization|backend|vmnetd)|qemu-system|vfkit"
                       r"|com\.apple\.Virtualization\.VirtualMachine")
SPOTLIGHT = ("mds", "mds_stores", "mdworker", "mdworker_shared", "mdbulkimport", "corespotlightd")
CHROME = re.compile(r"Google Chrome|Chromium")


def probe(d, cmd: list, timeout: float) -> tuple:
    """(output or None, why): the command's stdout, else None and one line saying why there is none."""
    code, out, err = d.sys.run(cmd, timeout=timeout)
    if code == 0:
        return out, ""
    if code == 127:
        return None, f"{cmd[0]} not found"
    if code == 124:
        return None, f"{cmd[0]} timed out after {timeout:g}s"
    return None, f"{cmd[0]} failed ({code}){': ' + err.strip().splitlines()[0][:80] if err.strip() else ''}"


def item(kind: str, text: str, **extra) -> dict:
    return {"item": kind, "text": text, **extra}


def running(table: dict) -> list:
    """The processes that run (not stopped by the interrupt or a zombie), busiest first."""
    return sorted((p for p in table.values() if p["stat"][:1] not in freeze.STAT_SKIP), key=lambda p: -p["cpu"])


def name(p: dict) -> str:
    return freeze.base(p)


def cpu_top(procs: list, n: int = 5) -> dict:
    top = [p for p in procs if p["cpu"] >= CPU_MIN][:n]
    if not top:
        return item("cpu", f"CPU top: no process over {CPU_MIN:g}%", top=[])
    rows = [{"pid": p["pid"], "cpu": p["cpu"], "what": p["args"][:60]} for p in top]
    return item("cpu", "CPU top: " + "; ".join(f"{r['pid']} {r['cpu']:.0f}% {r['what']}" for r in rows), top=rows)


def group(procs: list, match, label: str) -> dict:
    """The CPU sum and count of the processes `match` picks, named by `label`."""
    found = [p for p in procs if match(p)]
    if not found:
        return item(label.lower().split()[0], f"{label}: not running", cpu=0.0, count=0)
    cpu = sum(p["cpu"] for p in found)
    return item(label.lower().split()[0], f"{label}: {len(found)} process{'' if len(found) == 1 else 'es'}, CPU {cpu:.0f}%", cpu=cpu,
                count=len(found))


def talkers(text: str, n: int = 5) -> list:
    """[(bytes, name, pid, in, out)] of the last sample of `nettop -P -d -L 2 -x` (csv: `name.pid,in,out,`), biggest
    first; the earlier sample is cumulative, the header line `,bytes_in,bytes_out,` starts each one."""
    rows = []
    for line in text.splitlines():
        if line.startswith(",bytes_in"):
            rows = []
            continue
        cells = line.split(",")
        m = re.match(r"(.*)\.(\d+)$", cells[0]) if len(cells) >= 3 else None
        if m and cells[1].isdigit() and cells[2].isdigit():
            rows.append((int(cells[1]) + int(cells[2]), m.group(1), int(m.group(2)), int(cells[1]), int(cells[2])))
    return sorted(rows, reverse=True)[:n]


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return str(n)


def network(d) -> dict:
    out, why = probe(d, ["nettop", "-P", "-d", "-L", "2", "-s", "1", "-J", "bytes_in,bytes_out", "-x"],
                     NETTOP_TIMEOUT)
    if out is None:
        return item("network", f"network: {why}")
    top = [t for t in talkers(out) if t[0] > 0]
    if not top:
        return item("network", "network top: quiet (no bytes in the last second)", top=[])
    rows = [{"name": t[1], "pid": t[2], "bytes_in": t[3], "bytes_out": t[4]} for t in top]
    text = "; ".join(f"{r['name']} {r['pid']} in {human(r['bytes_in'])} out {human(r['bytes_out'])}" for r in rows)
    return item("network", "network top (last second): " + text, top=rows)


def time_machine(d) -> dict:
    out, why = probe(d, ["tmutil", "status"], TM_TIMEOUT)
    if out is None:
        return item("timemachine", f"Time Machine: {why}")
    run = re.search(r"\bRunning\s*=\s*(\d+)", out)
    if not run:
        return item("timemachine", "Time Machine: status not readable")
    if run.group(1) == "0":
        return item("timemachine", "Time Machine: not running", running=False)
    phase = re.search(r"BackupPhase\s*=\s*(\w+)", out)
    pct = re.search(r'Percent\s*=\s*"?(-?[\d.]+)', out)
    more = ", ".join(x for x in (phase and phase.group(1), pct and float(pct.group(1)) >= 0 and
                                 f"{float(pct.group(1)) * 100:.0f}%") if x)
    return item("timemachine", "Time Machine: backup RUNNING" + (f" ({more})" if more else ""), running=True)


def report(d) -> list:
    """Probe everything, print one line per item; the list for the stop record."""
    table = freeze.proc_table(d.sys)
    procs = running(table)
    d.out("still running (reported only, not stopped):")
    items = [cpu_top(procs) if table else item("cpu", "CPU top: ps gave nothing"),
             network(d),
             group(procs, lambda p: DOCKER_VM.search(p["comm"]), "Docker VM"),
             time_machine(d),
             group(procs, lambda p: name(p) in SPOTLIGHT, "Spotlight (mds, mdworker)"),
             group(procs, lambda p: CHROME.search(p["comm"]), "Chrome")]
    for it in items:
        d.out(f"  {it['text']}")
    return items
