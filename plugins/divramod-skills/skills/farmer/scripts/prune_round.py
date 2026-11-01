#!/usr/bin/env python3
"""The farmer's prune round (hal2 plan 0534; the user, 2026-10-30: "I think it's better if the farmer has this duty
and not the tall man"): one round as code, never deferred, run as the farmer task `farmer prune-round`.

  prune_round.py [--repo <dir>]      (also `farmer.py prune-round`)
      1. disk: while the data volume has under 150 GB free, delete `code/rust/target` of the farm's idle fields,
         biggest first (a field counts only when the target is git-ignored and the cleanup skill's `busy` says idle;
         never a busy field, never tracked files); the port of lookout's disk-free-apply (plan 0514 row 7 later
         replaces it by prune's own disk phase);
      2. prune: `/prune run` for the farm (landed fields 10-99 removed, 00-09 mucked out, stale pointers cleared).
      Prints one line per step and per deletion. Exit 0 when both ran, 1 with `prune round failed: <step> ...`
      naming each failed or timed-out step, so the task notifies (no silent duty).

The fields are the farm's worktrees (`git worktree list`, field_root.is_field: no train worktree); the main checkout
by mtm_scan; the sibling skills by skillpath, never a literal home path.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import field_root
import mtm_scan

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import sibling  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)

TARGET_GB = 150  # free space the disk step restores
TARGET = "code/rust/target"
DISK_LIMIT = 900  # seconds per step (the stopgap's; plan 0534 D11: sized from a live round later)
PRUNE_LIMIT = 1500
PROBE_LIMIT = 240  # one du, git or busy call
TAIL = 400


class StepTimeout(Exception):
    pass


def data_volume() -> str:
    return "/System/Volumes/Data" if os.path.isdir("/System/Volumes/Data") else "/"


def free_gb() -> float:
    return shutil.disk_usage(data_volume()).free / 1e9


def size_gb(path: Path) -> float:
    out = subprocess.run(["du", "-sk", str(path)], capture_output=True, text=True, timeout=PROBE_LIMIT).stdout.split()
    return int(out[0]) / 1e6 if out else 0.0


def busy_script() -> Path:
    return sibling("cleanup") / "scripts/cleanup.py"


def prune_script() -> Path:
    return sibling("prune") / "scripts/prune.py"


def is_idle(field: Path) -> bool:
    return subprocess.run([sys.executable, str(busy_script()), "busy", "--worktree", str(field)],
                          capture_output=True, timeout=PROBE_LIMIT).returncode == 0


def is_ignored(field: Path) -> bool:
    return subprocess.run(["git", "-C", str(field), "check-ignore", "-q", TARGET],
                          capture_output=True, timeout=PROBE_LIMIT).returncode == 0


def candidates(main: str) -> list[Path]:
    """The farm's fields whose build target may go: it exists, is git-ignored and nothing runs in the field."""
    found = []
    for w in mtm_scan.worktrees(main):
        field = Path(w["path"])
        if field_root.is_field(w, main) and (field / TARGET).is_dir() and is_ignored(field) and is_idle(field):
            found.append(field)
    return found


def disk_step(main: str, deadline: float, now=time.monotonic) -> list[str]:
    """Delete idle fields' build targets, biggest first, until TARGET_GB are free. The printed lines; raises
    StepTimeout past `deadline` (a time of `now`), RuntimeError when a target would not go."""
    if free_gb() >= TARGET_GB:
        return [f"{free_gb():.0f} GB free, nothing to do"]
    lines, sized = [], []
    for field in candidates(main):
        if now() > deadline:
            raise StepTimeout
        sized.append((size_gb(field / TARGET), field))
    for gb, field in sorted(sized, reverse=True):
        if free_gb() >= TARGET_GB:
            break
        if now() > deadline:
            raise StepTimeout
        shutil.rmtree(field / TARGET, ignore_errors=True)
        if (field / TARGET).exists():
            raise RuntimeError(f"{field.name}/{TARGET} not fully deleted")
        lines.append(f"deleted {field.parent.name}/{field.name} {TARGET} ({gb:.0f} GB); {free_gb():.0f} GB free")
    return lines


def run_disk(main: str, limit: int = DISK_LIMIT, now=time.monotonic) -> str | None:
    """The disk step, printed; the failure it names, else None."""
    try:
        for line in disk_step(main, now() + limit, now):
            print(f"disk: {line}")
    except StepTimeout:
        return f"disk timed out after {limit} s"
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        return f"disk failed: {e}"
    return None


def run_prune(main: str, limit: int = PRUNE_LIMIT) -> str | None:
    """`prune.py run` for the farm, printed; the failure it names, else None."""
    try:
        p = subprocess.run([sys.executable, str(prune_script()), "run", "--repo", main],
                           capture_output=True, text=True, timeout=limit)
    except subprocess.TimeoutExpired:
        return f"prune timed out after {limit} s"
    print(f"prune: exit {p.returncode}: {(p.stdout or '').strip()[-TAIL:]}")
    return None if p.returncode == 0 else f"prune exit {p.returncode}: {(p.stderr or p.stdout)[-300:]}"


def is_checkout(folder: str) -> bool:
    return subprocess.run(["git", "-C", folder, "rev-parse", "--git-dir"], capture_output=True,
                          timeout=PROBE_LIMIT).returncode == 0


def run(repo: str) -> int:
    if not is_checkout(repo):  # the cause of plan 0534 step 6: a --repo outside git showed up as "no worktrees"
        print(f"prune round failed: {repo} is no git checkout (the round needs the farm's repository)")
        return 1
    main = mtm_scan.main_checkout(repo)
    bad = [b for b in (run_disk(main), run_prune(main)) if b]
    if bad:
        print("prune round failed: " + "; ".join(bad))
        return 1
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="prune_round.py", description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=os.getcwd())
    return run(ap.parse_args(argv).repo)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
