#!/usr/bin/env python3
"""The tollman's prune duty (hal2 plan 0143 step 8; moved from the farmer by plan 0360 step 7, D8, D30, D67):
landed fields cleaned or removed, and after the barn the last train's cars cleared or removed (barn.py).

  prune.py scan [--repo <dir>] [--json]
      every numbered worktree 00-99 with whether it is free to prune, and why not
  prune.py clean <NN> [--repo <dir>] [--dry-run]
      a worktree 00-09: checked again, then its build artifacts deleted (the cleanup skill's `delete`)
  prune.py sizes [--repo <dir>]
      the free disk and the biggest worktrees (du over every worktree: minutes) into disk.json in the tollman's
      state folder; the tick starts it in the background and reports it the next round (plan 0011)
  prune.py remove <NN> [--repo <dir>] [--dry-run]
      a worktree 10-99: checked again, its idle session stopped by signal, then `hal2-cli-git worktree remove NN
      --remote`; a servant's worktree 30-99 (`plans/LEAD`): `--force`, then origin/NN once in origin/<foreman>
      (prune_act.py)

What makes a field free is prune_proof.py's (the global record never-delete-unsaved-work). The tick (`handler`)
plans a `clean` per landing (keyed on the worktree's HEAD) for 00-09, one `remove` per round for 10-99 (the last
landed train's cars first), the after-the-barn clears and stuck wakes (barn.py), and every 6 hours the free disk and
the biggest worktrees for the round summary, a notice under 100 GB free: measured by a detached `prune.py sizes`
(never inside a round) and reported by the round after it finished.
Exit 0 done or skipped (the worktree is no longer free: prints why), 1 failed (the tick then wakes the tollman), 2 a
tool missing.
"""

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import barn
import logstate
import mtm_scan
import prune_act
import roles
from prune_proof import NUMBERED, marker, scan
from tick import act

HERE = Path(__file__).resolve().parent
ROLE = "tollman"  # disk.json and disk.lock live in the tollman's state folder
LOW_DISK_GB = 100
SIZES_EVERY = 6 * 3600  # du over every worktree takes minutes
SIZES_TOP = 5
SIZES_FILE, SIZES_LOCK = "disk.json", "disk.lock"
SIZES_STALE = 30 * 60  # a lock this old belongs to a sizes run that died


def state(main: str) -> Path:
    return mtm_scan.state_dir(main, ROLE)


def disk(main: str, paths: list[str], timeout: int = 300) -> dict:
    """Free disk of the main checkout's volume and the biggest worktrees (du, bounded)."""
    free = shutil.disk_usage(main).free / 1e9
    sizes = []
    try:
        out = subprocess.run(["du", "-sk", *paths], capture_output=True, text=True, timeout=timeout).stdout
        for line in out.splitlines():
            kb, _, path = line.partition("\t")
            if kb.isdigit():
                sizes.append((int(kb) / 1e6, Path(path).name))
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {"free_gb": round(free, 1), "biggest": sorted(sizes, reverse=True)[:SIZES_TOP]}


def recent(log: list[dict], prefix: str, now: dt.datetime, seconds: int) -> bool:
    return any(str(e.get("key", "")).startswith(prefix) and (now - dt.datetime.fromisoformat(e["at"])).total_seconds()
               < seconds for e in log)


def measure(main: str) -> None:
    """`prune.py sizes`: du over the main checkout and every worktree, written to SIZES_FILE with its time."""
    folder = state(main)
    try:
        info = disk(main, [main] + [w["path"] for w in mtm_scan.worktrees(main)])
        tmp = folder / f".{SIZES_FILE}.tmp"
        tmp.write_text(json.dumps({"at": time.time(), **info}))
        tmp.replace(folder / SIZES_FILE)
    finally:
        (folder / SIZES_LOCK).unlink(missing_ok=True)


def measured(main: str, now: dt.datetime) -> dict | None:
    """The last `prune.py sizes` result when it is younger than SIZES_EVERY."""
    try:
        info = json.loads((state(main) / SIZES_FILE).read_text())
    except (OSError, ValueError):
        return None
    return info if now.timestamp() - info.get("at", 0) < SIZES_EVERY else None


def measure_later(main: str, spawn=subprocess.Popen) -> bool:
    """Start `prune.py sizes` detached, one at a time (a lock older than SIZES_STALE is taken over)."""
    lock = state(main) / SIZES_LOCK
    try:
        if time.time() - lock.stat().st_mtime < SIZES_STALE:
            return False
    except OSError:
        pass
    lock.write_text(str(os.getpid()))
    spawn([sys.executable, str(HERE / "prune.py"), "sizes", "--repo", main], cwd=main, stdin=subprocess.DEVNULL,
          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return True


def disk_actions(main: str, ctx: dict, info: dict | None) -> list[dict]:
    """Every SIZES_EVERY: the free disk and the biggest worktrees as a record, a notice when low. The sizes come
    from a background `prune.py sizes` (started here, outside a dry run), so a round never waits for du."""
    now = ctx["now"]
    if info is None:
        if recent(ctx.get("log", []), "prune:disk:", now, SIZES_EVERY):
            return []
        info = measured(main, now)
        if info is None:
            if not ctx.get("dry", True):
                measure_later(main)
            return []
    biggest = ", ".join(f"{name} {gb:.0f} GB" for gb, name in info["biggest"]) or "unknown"
    out = [act("prune", "disk", "record", key=f"prune:disk:{now:%Y-%m-%dT%H}", window=SIZES_EVERY,
               text=f"free disk {info['free_gb']:.0f} GB; biggest worktrees: {biggest}")]
    if info["free_gb"] < LOW_DISK_GB:
        out.append(act("prune", "low-disk", "notify", key="prune:low-disk", window=SIZES_EVERY,
                       text=f"only {info['free_gb']:.0f} GB free on the disk of {main}; biggest worktrees: {biggest}"))
    return out


def failed(w: dict, what: str) -> dict:
    return act("prune", "failed", "wake", w["slot"], text=f"prune.py {what} {w['slot']} failed: see its log entry")


def plan(item: dict, ctx: dict, found: list[dict] | None = None, info: dict | None = None,
         landed: dict | None = None) -> list[dict]:
    """The prune duty's actions this round (see the module doc); `landed`: the last landed train (read when None)."""
    main = ctx["main"]
    if found is None:
        ctx = {**ctx, "farmer_log": logstate.read_log(main, roles.ROLE)}  # its open questions to the user count too
        found = scan(main, ctx, list(ctx.get("agents_by_pane", {}).values()))
    landed = barn.last_landed(main) if landed is None else landed
    me = [sys.executable, str(HERE / "prune.py")]
    out, removed = [], False
    for w in barn.first(found, barn.cars(landed)):
        if w["why"]:
            continue
        if int(w["slot"]) < 10:
            out.append(act("prune", "clean", "run", w["slot"], key=f"prune:clean:{w['slot']}:{w['head']}",
                           window=30 * 24 * 3600, argv=me + ["clean", w["slot"], "--repo", main],
                           text=f"clean landed worktree {w['slot']}'s build artifacts", on_fail=[failed(w, "clean")]))
        elif not removed:
            removed = True
            out.append(removal(w, me, main))
    return out + barn.actions(ctx, found, landed) + disk_actions(main, ctx, info)


def removal(w: dict, me: list[str], main: str) -> dict:
    lead = marker(w["path"])
    text = (f"remove servant worktree {w['slot']} (its work is in origin/{lead['slot']}) with origin/{w['slot']}"
            if lead else f"remove landed worktree {w['slot']} with its branch (origin/{w['slot']} once merged)")
    return act("prune", "remove", "run", w["slot"], key=f"prune:remove:{w['slot']}:{w['head']}", window=3600,
               argv=me + ["remove", w["slot"], "--repo", main], text=text, on_fail=[failed(w, "remove")])


def handler(item: dict, ctx: dict) -> list[dict]:
    return plan(item, ctx)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=("scan", "sizes", "clean", "remove"))
    p.add_argument("slot", nargs="?")
    p.add_argument("--repo", default=".")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    missing = [t for t in ("git", "hal2-cli-git", "hal2-cli-agents") if not shutil.which(t)]
    if missing:
        print(f"prune.py: missing {', '.join(missing)}", file=sys.stderr)
        return 2
    main_dir = mtm_scan.main_checkout(args.repo)
    if args.cmd == "scan":
        ctx, agents = prune_act.live(main_dir)
        found = scan(main_dir, ctx, agents)
        print(json.dumps(found, indent=1) if args.json else
              "\n".join(f"{w['slot']}: {w['why'] or 'free'}" for w in found) or "no numbered worktrees")
        return 0
    if args.cmd == "sizes":
        measure(main_dir)
        return 0
    if not args.slot or not NUMBERED.fullmatch(args.slot):
        print("prune.py: give a two-digit worktree (00-99)", file=sys.stderr)
        return 1
    code, text = prune_act.act_on(main_dir, args.slot, args.cmd, args.dry_run)
    print(text)
    return 1 if code else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
