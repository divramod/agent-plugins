"""What a train's local phase costs this machine (hal2 plan 0472 step 4, D4): the 1-minute load average and the
whole disks' operations per second at the start, mid and end of the pretest, the only local compute of a train
(`pretest_train.before_landing`). No sleep, no extra load: a probe is one load read and one cumulative counter read
(macOS `iostat -Id`, Linux /proc/diskstats; none on Windows: `ops` null), a rate is the difference of two probes over
the seconds between. A timer thread adds a probe every INTERVAL seconds while the pretest runs; the middle one is the
`mid` mark (none when the pretest was shorter than a probe). The same totals as hal2's `disk-io` sampler
(code/python/scripts/disk-io), its own small copy: this skill is published without that unit.

`Phase.record()` is the `local` key of the train's `pretest` line (schema: train.schema.json):

  {"seconds", "load_peak", "disk_ops_s", "marks": [{"t": start|mid|end, "at", "load1", "ops_s"}]}

`ops_s` of a mark is the rate since the mark before it (none for `start`); `disk_ops_s` the mean over the phase.
`metrics.py` reports `local_load` (the peak) and `local_disk_ops` (the mean) per train.
"""

import datetime as dt
import os
import re
import subprocess
import sys
import threading
import time

INTERVAL = 60.0
WHOLE_DISK = re.compile(r"^(sd[a-z]+|vd[a-z]+|xvd[a-z]+|hd[a-z]+|nvme\d+n\d+|mmcblk\d+)$")


def disk_ops(platform: str = sys.platform) -> int | None:
    """The whole disks' transfers since boot, or None where the OS gives none without root."""
    try:
        if platform == "darwin":
            rows = [r.split() for r in subprocess.run(["iostat", "-Id"], capture_output=True, text=True,
                                                      timeout=10).stdout.strip().splitlines()]
            vals = rows[-1] if len(rows) >= 3 else []
            return sum(int(float(vals[i + 1])) for i in range(0, len(vals) - 2, 3)) if vals else None
        if platform.startswith("linux"):
            with open("/proc/diskstats") as fh:
                rows = [line.split() for line in fh]
            found = [int(f[3]) + int(f[7]) for f in rows if len(f) >= 10 and WHOLE_DISK.match(f[2])]
            return sum(found) if found else None
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        pass
    return None


def probe() -> dict:
    try:
        load1 = round(os.getloadavg()[0], 2)
    except (OSError, AttributeError):
        load1 = None
    return {"at": time.monotonic(), "utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "load1": load1, "ops": disk_ops()}


class Phase:
    """`with Phase() as p: ...; p.record()`; never raises into the pretest, a failed probe is a gap."""

    def __init__(self, read=None, interval: float = INTERVAL, thread: bool = True):
        self.read, self.interval, self.threaded = read or probe, interval, thread
        self.probes: list[tuple[str, dict]] = []
        self.stop = threading.Event()
        self.worker = None

    def mark(self, kind: str) -> None:
        try:
            self.probes.append((kind, self.read()))
        except Exception:  # noqa: BLE001  (a probe is a measurement, never a reason for a train to fail)
            pass

    def __enter__(self):
        self.mark("start")
        if self.threaded:
            self.worker = threading.Thread(target=self.tick, daemon=True)
            self.worker.start()
        return self

    def tick(self) -> None:
        while not self.stop.wait(self.interval):
            self.mark("tick")

    def __exit__(self, *exc) -> None:
        self.stop.set()
        if self.worker:
            self.worker.join(timeout=5)
        self.mark("end")

    def record(self) -> dict | None:
        """The `local` key; None when the start or the end probe failed."""
        if len(self.probes) < 2 or self.probes[0][0] != "start" or self.probes[-1][0] != "end":
            return None
        start, end = self.probes[0][1], self.probes[-1][1]
        span = end["at"] - start["at"]
        ticks = [p for k, p in self.probes if k == "tick"]
        mid = min(ticks, key=lambda p: abs(p["at"] - (start["at"] + span / 2))) if ticks else None
        chain = [("start", start)] + ([("mid", mid)] if mid else []) + [("end", end)]
        marks, before = [], None
        for kind, p in chain:
            rate = None
            if before and before["ops"] is not None and p["ops"] is not None and p["at"] > before["at"]:
                rate = round((p["ops"] - before["ops"]) / (p["at"] - before["at"]), 1)
            marks.append({"t": kind, "at": p["utc"], "load1": p["load1"], "ops_s": rate})
            before = p
        loads = [m["load1"] for m in marks if m["load1"] is not None]
        mean = None
        if start["ops"] is not None and end["ops"] is not None and span > 0:
            mean = round((end["ops"] - start["ops"]) / span, 1)
        return {"seconds": round(span, 1), "load_peak": max(loads) if loads else None, "disk_ops_s": mean,
                "marks": marks}
