"""Prune's disk phase (hal2 plan 0514 step 7, D18): the lookout stopgap `disk-free` moved into hal2.

While the disk has less than `below_gb` free (`.hal/prune.toml` `[disk]`, default 80 GB) the Rust build folders
(`code/rust/target`, rebuilt by the next build) of idle fields are deleted, session-less fields first and the build
built longest ago first, until `until_gb` are free (default 150 GB). Free space is read from the filesystem before
each deletion (disk_facts: no `du`, no size walk); what a deletion freed is the free space it added.

Never deferred: a workqueue hold or a train's build only keeps the field that holds it (D18; the trims and muck outs
of the phases still wait for the gap between trains, busy.py). Never a busy field (a busy agent, a build or test, a
workqueue job, its landing) and never unsaved work: each deletion reads the field again just before and asks the
proof (disk_facts.refusal: git-ignored, no tracked file, a real folder inside the field). Its own lock (`disk-lock`
in prune's state folder), so a long prune run under the farm lock never holds it back; a second disk phase says
"already running" and leaves.
"""

import shutil
import time
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import disk_facts
import store
from executor_out import Out

JOB, ACTION, LOCK = "disk", "delete-target", "disk-lock"
TOOLS = ("git",)  # without hal2-cli-agents every field counts busy; the workqueue and queue answers are optional


def due(main: str, free=None) -> dict:
    """`{due, free_gb, below_gb, until_gb, note}`: is the disk below its mark now?"""
    lim, note = disk_facts.limits(main)
    gb = (free or disk_facts.free_gb)(main)
    return {"due": gb < lim["below_gb"], "free_gb": round(gb, 1), "below_gb": lim["below_gb"],
            "until_gb": lim["until_gb"], "note": note}


def remove(target: str) -> str | None:
    """The folder deleted; None when it is gone, else what is left (a file in use, a permission)."""
    shutil.rmtree(target, ignore_errors=True)
    return "partly deleted: some files could not be removed" if Path(target).exists() else None


def age(stamp_ns: int, now: float | None = None) -> str:
    if not stamp_ns:
        return "built at an unknown time"
    hours = max(0.0, ((now or time.time()) - stamp_ns / 1e9) / 3600)
    return f"built {hours:.0f} h ago" if hours < 48 else f"built {hours / 24:.0f} days ago"


class Phase:
    """One disk phase. `free`, `read`, `proof`, `delete` are the outside world, replaced in tests."""

    def __init__(self, main: str, dry: bool, out: Out, free=None, read=None, proof=None, delete=None):
        self.main, self.dry, self.out = main, dry, out
        self.free, self.read = free or disk_facts.free_gb, read or disk_facts.read
        self.proof, self.delete = proof or disk_facts.refusal, delete or remove
        self.rows: list[dict] = []

    def run(self) -> list[dict]:
        self.out.job(JOB)
        state = due(self.main, self.free)
        self.out.line(f"disk: {state['free_gb']:g} GB free; idle fields' {', '.join(disk_facts.TARGETS)} go below "
                      f"{state['below_gb']:g} GB until {state['until_gb']:g} GB")
        if state["note"]:
            self.out.line(f"note: {state['note']}")
        if not state["due"]:
            self.out.line(f"skipped: disk fine ({state['free_gb']:g} GB free)")
            return self.rows
        found = self.read(self.main)
        for f in found:
            if f["busy"]:
                self.out.line(f"kept {f['slot']}: {f['busy']}")
        todo = disk_facts.order(found)
        if not todo:
            self.out.line("skipped: no idle field holds a build folder")
        for f in todo:
            gb = self.free(self.main)
            if not self.dry and gb >= state["until_gb"]:
                self.out.line(f"stopped: {gb:.1f} GB free, the mark of {state['until_gb']:g} GB reached")
                break
            self.one(f)
        return self.rows

    def row(self, f: dict, status: str, freed: int, why: str) -> None:
        self.rows.append({"field": f["slot"], "action": ACTION, "status": status, "bytes": freed, "why": why})

    def one(self, f: dict) -> None:
        self.out.step(f["slot"])
        why = f"{f['rel']}, {age(f['stamp'])}" + (", a resting session" if f["sessions"] else ", no session")
        if self.dry:
            self.out.line(f"would delete {f['slot']} {why}")
            self.row(f, "would", 0, why)
            return self.out.end("success")
        now = next((x for x in self.read(self.main, only=f["slot"]) if x["rel"] == f["rel"]), None)
        no = "its build folder is gone" if now is None else now["busy"] or self.proof(f["path"], f["rel"])
        if no:
            self.out.line(f"skipped {f['slot']}: {no}")
            self.row(f, "skipped", 0, no)
            return self.out.end("skipped")
        before = self.free(self.main)
        left = self.delete(f["target"])
        freed = max(0, int((self.free(self.main) - before) * 1e9))
        status = "failure" if left else "success"
        self.out.line(f"{'deleted' if not left else 'failed to delete'} {f['slot']} {f['rel']}: "
                      f"{freed / 1e9:.1f} GB freed{'; ' + left if left else ''}")
        self.row(f, status, freed, left or why)
        self.out.end(status)


def run(main: str, dry: bool = False, out: Out | None = None, **world) -> list[dict]:
    """The disk phase under its own lock (a dry run takes none); its rows for the run's report."""
    out = out or Out()
    if dry:
        return Phase(main, dry, out, **world).run()
    try:
        with store.farm_lock(main, LOCK):
            return Phase(main, dry, out, **world).run()
    except store.Locked as e:
        out.job(JOB)
        out.line(f"already running: {e}")
        return []
