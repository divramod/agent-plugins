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
      Before both, the farm's autopilot (`hal2-cli-agents autopilot show --json`, hal2 plan 0543 step 27, D97) says
      whether the round is due: a "Prune now" asked (`prune_due`) always, else only with `auto_prune` on and
      `prune_interval_s` passed since the last passed round (`pruned_at`); not due: exit 0, one line why. A passed
      round is recorded by `autopilot set --pruned <its start>`, which clears a Prune now asked before it. An
      unreadable autopilot runs the round by the task's cron, as before the switch.

The fields are the farm's worktrees (`git worktree list`, field_root.is_field: no train worktree); the main checkout
by mtm_scan; the sibling skills by skillpath, never a literal home path.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import bounded
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
AUTOPILOT = ["hal2-cli-agents", "autopilot"]
AUTOPILOT_LIMIT = 60


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


def autopilot(main: str) -> dict | None:
    """The farm's autopilot part (`farm` of `autopilot show --json`, run in the main checkout: its repository's
    name), None when it cannot be read."""
    try:
        p = bounded.run(AUTOPILOT + ["show", "--json"], cwd=main, other=AUTOPILOT_LIMIT)
        farm = json.loads(p.stdout).get("farm") if p.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return None
    return farm if isinstance(farm, dict) else None


def stamp(at: datetime) -> str:
    return at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def due(farm: dict, now: datetime) -> tuple[bool, str]:
    """Whether the round runs now, and why (or why not)."""
    if farm.get("prune_due"):
        return True, f"Prune now asked at {farm['prune_due']}"
    if farm.get("auto_prune") is False:
        return False, "auto prune off, no Prune now asked"
    interval, last = int(farm.get("prune_interval_s") or 0), farm.get("pruned_at")
    try:
        ago = (now - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() if last else None
    except (AttributeError, ValueError):
        ago = None  # an unreadable last run: run
    if ago is not None and 0 <= ago < interval:
        return False, f"last round {last}, every {interval} s"
    return True, f"auto prune every {interval} s, last round {last or 'never'}"


def record(main: str, started: str) -> str | None:
    """`autopilot set --pruned <started>`; the failure it names, else None."""
    try:
        p = bounded.run(AUTOPILOT + ["set", "--pruned", started, "--json"], cwd=main, other=AUTOPILOT_LIMIT)
    except (OSError, subprocess.SubprocessError) as e:
        return f"record failed: {e}"
    return None if p.returncode == 0 else f"record exit {p.returncode}: {(p.stderr or p.stdout)[-300:]}"


def is_checkout(folder: str) -> bool:
    return subprocess.run(["git", "-C", folder, "rev-parse", "--git-dir"], capture_output=True,
                          timeout=PROBE_LIMIT).returncode == 0


def run(repo: str, now=lambda: datetime.now(timezone.utc)) -> int:
    if not is_checkout(repo):  # the cause of plan 0534 step 6: a --repo outside git showed up as "no worktrees"
        print(f"prune round failed: {repo} is no git checkout (the round needs the farm's repository)")
        return 1
    main = mtm_scan.main_checkout(repo)
    started, farm = now(), autopilot(main)
    if farm is None:
        print("autopilot: unreadable, the round runs by the task's cron")
    else:
        go, why = due(farm, started)
        print(f"autopilot: {why}" + ("" if go else ": not due"))
        if not go:
            return 0
    bad = [b for b in (run_disk(main), run_prune(main)) if b]
    if not bad and farm is not None:
        bad = [b for b in [record(main, stamp(started))] if b]
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
