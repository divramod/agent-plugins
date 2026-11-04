"""The disk phase's facts (hal2 plan 0514 step 7, D18): what `disk_phase.py` decides on, read in seconds.

Free space comes from the filesystem's own count (`shutil.disk_usage`), never a size walk or `du` (the lookout
stopgap's `du` took 120 s and more). Per numbered field: its Rust build folder (`TARGETS`), why it is busy (a busy
agent, a build or test whose command line names it, a workqueue job or hold of it, its running landing), whether a
session lives in it, and the build folder's age stamp (sizes.stamp: its root and top entries, no walk). Nothing here
changes anything; every outside call goes through `call`, so a test hands in a fake.

The proof of a deletion (`refusal`) is the cleanup skill's check without its tree walk: a real folder inside the
field (no link out of it), git-ignored and holding no tracked file, so it holds no unsaved work (the global record
never-delete-unsaved-work); only the fixed `TARGETS` paths are ever asked.
"""

import os
import shutil
import subprocess
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import batch
import facts
import live_sessions
import prune_proof
import sizes

TARGETS = ("code/rust/target",)
GIT_TIMEOUT = 60


def free_gb(main: str) -> float:
    return shutil.disk_usage(main).free / 1e9


def limits(main: str) -> tuple[dict, str | None]:
    """`[disk]` of `.hal/prune.toml` (`below_gb`, `until_gb`); an invalid file never stops the guard: the defaults
    hold and the problem is said."""
    try:
        return dict(facts.config(main)["disk"]), None
    except facts.FactsError as e:
        return dict(facts.DEFAULTS["disk"]), f"{e}; the defaults hold"


def safe(call, argv: list[str], main: str):
    """`call(argv, main)`; a missing program answers None (its readers decide what None means)."""
    try:
        return call(argv, main)
    except facts.ToolMissing:
        return None


def numbered(main: str) -> list[dict]:
    """The farm's numbered fields `{slot, path}` (never main, a role field or another name) by one `git worktree list
    --porcelain` (hal2-cli-git's list took 27 s under load). FactsError when git cannot list them."""
    try:
        p = subprocess.run(["git", "-C", main, "worktree", "list", "--porcelain"], capture_output=True, text=True,
                           timeout=GIT_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise facts.FactsError(f"git worktree list: {e}") from e
    if p.returncode:
        raise facts.FactsError(f"git worktree list: {p.stderr.strip()[-200:]}")
    paths = [line[9:] for line in p.stdout.splitlines() if line.startswith("worktree ")][1:]  # the first is main
    return sorted(({"slot": Path(x).name, "path": x} for x in paths if prune_proof.NUMBERED.fullmatch(Path(x).name)),
                  key=lambda f: f["slot"])


def inside(path, field: str) -> bool:
    if not path:
        return False
    p, top = os.path.realpath(str(path)), os.path.realpath(field)
    return p == top or p.startswith(top + os.sep)


def busy_why(f: dict, rows: list[dict] | None, wq: dict, landing: set[str], processes) -> str | None:
    """Why the field is busy now, None when it is idle. An unreadable agents list makes every field busy."""
    if rows is None:
        return "the agents list cannot be read"
    for s in prune_proof.sessions(rows, f["path"]):
        if s.get("state") in prune_proof.BUSY:
            return f"its agent {s.get('pane_id')} is {s.get('state')}"
    names = {f["slot"], f"{Path(f['path']).parent.name}/{f['slot']}", f["path"]}
    for h in wq.get("holds") or []:
        if isinstance(h, dict) and str(h.get("field")) in names:
            return f"it holds the workqueue hold {h.get('id', '?')}"
    for j in (wq.get("running") or []) + (wq.get("waiting") or []):
        if isinstance(j, dict) and inside(j.get("cwd"), f["path"]):
            return f"a workqueue job runs in it ({j.get('class', '?')})"
    if f["slot"] in landing:
        return "its landing runs"
    if processes.running(f["path"]):
        return "a build or test runs in it"
    return None


def read(main: str, call=facts.call_json, processes=None, only: str | None = None) -> list[dict]:
    """Every numbered field holding a target (`only`: that field): `{slot, path, rel, target, busy, sessions, stamp}`,
    read now."""
    processes = processes or batch.Processes()
    rows = live_sessions.read(lambda argv: safe(call, argv, main))
    wq = safe(call, ["hal2-cli-workqueue", "status", "--json"], main)
    wq = wq if isinstance(wq, dict) else {}
    queue = safe(call, ["hal2-cli-git", "worktree", "queue", "--json"], main)
    tickets = queue.get("queue", []) if isinstance(queue, dict) else []
    landing = {str(t.get("slot")) for t in tickets if isinstance(t, dict) and t.get("state") == "active"}
    out = []
    for f in (f for f in numbered(main) if only is None or f["slot"] == only):
        for rel in TARGETS:
            target = Path(f["path"]) / rel
            if not target.is_dir() or target.is_symlink():
                continue
            live = [] if rows is None else prune_proof.sessions(rows, f["path"])
            out.append({**f, "rel": rel, "target": str(target), "busy": busy_why(f, rows, wq, landing, processes),
                        "sessions": len(live), "stamp": int(sizes.stamp(target))})
    return out


def order(found: list[dict]) -> list[dict]:
    """The idle ones: session-less fields first, then the build folder built longest ago, then by field."""
    return sorted((f for f in found if not f["busy"]), key=lambda f: (f["sessions"] > 0, f["stamp"], f["slot"]))


def git(field: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", field, *args], capture_output=True, text=True, timeout=GIT_TIMEOUT)


def refusal(field: str, rel: str) -> str | None:
    """Why `field/rel` must not be deleted, None when it may (the cleanup skill's check, no tree walk)."""
    if rel not in TARGETS:
        return f"{rel} is not a build folder the disk phase deletes"
    path = Path(field) / rel
    if path.is_symlink() or not path.is_dir():
        return "no real folder"
    if not inside(path.resolve(), field):
        return "outside the field"
    try:
        tracked = git(field, "ls-files", "--", rel)
        ignored = git(field, "check-ignore", "-q", rel)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"git cannot answer: {e}"
    if tracked.returncode or tracked.stdout.strip():
        return "holds tracked files" if tracked.stdout.strip() else "git cannot list it"
    return None if ignored.returncode == 0 else "not git-ignored"
