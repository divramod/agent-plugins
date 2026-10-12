#!/usr/bin/env python3
"""The farmer's prune duty (hal2 plan 0143 step 8; the user, 2026-10-06): landed worktree slots cleaned or deleted.

  prune.py scan [--repo <dir>] [--json]
      every numbered slot 00-99 with whether it is free to prune, and why not
  prune.py clean <NN> [--repo <dir>] [--dry-run]
      a slot 00-09: checked again, then its build artifacts deleted (the cleanup skill's `delete`)
  prune.py sizes [--repo <dir>]
      the free disk and the biggest worktrees (du over every worktree: minutes) into disk.json in the farmer's state
      folder; the tick starts it in the background and reports it the next round (plan 0011)
  prune.py remove <NN> [--repo <dir>] [--dry-run]
      a slot 10-99: checked again, its idle session stopped by signal (delete-worktree-session's stop.py through
      `hal2-cli-agents stop`, never a typed `/exit`; a draft or background tasks leave it running), then
      `hal2-cli-git worktree remove NN --remote`; a
      subservant's slot 30-99 (marked, below): fetched and checked again, `hal2-cli-git worktree remove NN --force`
      (its branch is not on main by design), then `git push origin --delete NN` once origin/NN is in origin/<lead>

A slot is free when nothing in it is unsaved: no commit (its branch or a side branch `NN-*`) that origin's default
branch lacks, no change, no plans/CURRENT_PLAN, no merge queue ticket or boss pause, no busy agent (working,
starting, blocked), no session active in the last 30 minutes (10-99), no build running in it (cleanup's `busy`)
and no open question to the user in the farmer's log. Never main, a role slot or a name that is not two digits.
A slot marked `plans/LEAD` (`<lead-slot> <plan> <step>`: a parallel plan's subservant, skills plan 0013) is measured
against its lead's branch instead, never main: a marked slot 30-99 is free when HEAD, origin/NN and every side branch
`NN-*` are in origin/<lead>, nothing is uncommitted (the ignored LEAD and CURRENT_PLAN aside), no ticket, boss pause,
open question or busy agent, no session active and no LEAD written in the last hour, and no build runs. A marked
slot below 30 is never pruned.
The tick (`handler`) plans a `clean` per landing (keyed on the slot's HEAD) for 00-09, one `remove` per round for
10-99, and every 6 hours the free disk and the biggest worktrees for the round summary, a notice under 100 GB free:
measured by a detached `prune.py sizes` (never inside a round) and reported by the round after it finished.
Exit 0 done or skipped (the slot is no longer free: prints why), 1 failed (the tick then wakes the farmer), 2 a
tool missing.
"""

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import lead_marker
import logstate
import mtm_scan
import tick
from tick import act

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]
CLEANUP = SKILLS / "cleanup/scripts/cleanup.py"
STOP = SKILLS / "delete-worktree-session/scripts/stop.py"
NUMBERED = re.compile(r"\d\d")
BUSY = {"working", "starting", "blocked"}
GONE = {"ended", "failed"}
QUIET = 30 * 60  # a 10-99 session active more recently is left alone
SUBSERVANT_QUIET = 3600  # a marked 30-99 slot: the lead may reuse it with its warm build cache meanwhile
SUBSERVANTS_FROM = 30  # subservants work only in slots 30-99 (the user, skills plan 0013)
LEAD = lead_marker.LEAD
LOW_DISK_GB = 100
SIZES_EVERY = 6 * 3600  # du over every worktree takes minutes
SIZES_TOP = 5
SIZES_FILE, SIZES_LOCK = "disk.json", "disk.lock"  # in the farmer's state folder
SIZES_STALE = 30 * 60  # a lock this old belongs to a sizes run that died
EXIT_WAIT = 15


def git(path: str, *args: str) -> str:
    return tick.git(path, *args)


def unsaved(path: str, slot: str, base: str) -> list[str]:
    """What the slot holds that `base` (origin's default branch) lacks: commits on HEAD or a side branch, changes."""
    out = []
    ahead = git(path, "rev-list", "--count", f"{base}..HEAD")
    if ahead and ahead != "0":
        out.append(f"{ahead} commit(s) not on {base}")
    for ref in git(path, "for-each-ref", "--format=%(refname:short)", f"refs/heads/{slot}-*").split():
        n = git(path, "rev-list", "--count", f"{base}..{ref}")
        if n and n != "0":
            out.append(f"side branch {ref}: {n} commit(s) not on {base}")
    if git(path, "status", "--porcelain"):
        out.append("uncommitted changes")
    plan = Path(path) / "plans/CURRENT_PLAN"
    if plan.exists() and plan.read_text().strip():
        out.append(f"plans/CURRENT_PLAN names {plan.read_text().strip()}")
    return out


def marker(path: str) -> dict | None:
    """lead_marker's plans/LEAD with `at`, its mtime: the lead's `plan.py assign` rewrites it when it reuses the
    slot. A malformed marker is {bad: True, error, text}: still marked, never pruned."""
    lead = lead_marker.marker(path)
    if lead is None:
        return None
    try:
        return {**lead, "at": (Path(path) / LEAD).stat().st_mtime}
    except OSError:
        return {**lead, "at": time.time()}


ref_exists = lead_marker.ref_exists
unsaved_for_lead = lead_marker.unsaved_for_lead


def build_running(path: str) -> bool:
    """cleanup.py's `busy`: a process whose command line names the worktree."""
    try:
        p = subprocess.run([sys.executable, str(CLEANUP), "busy", "--worktree", path], cwd=path,
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return True
    return p.returncode == 1


def sessions(agents: list[dict], path: str) -> list[dict]:
    here = Path(path).resolve()
    return [a for a in agents if a.get("checkout") and Path(a["checkout"]).resolve() == here
            and a.get("state") not in GONE]


def refusal(w: dict, ctx: dict, agents: list[dict], now_ms: float, build=build_running) -> str | None:
    """Why the slot `w` (a worktree: path, slot) may not be pruned now, None when it may."""
    slot, path = w["slot"], w["path"]
    lead = marker(path)
    if lead is not None:
        return subservant_refusal(w, lead, ctx, agents, now_ms, build)
    why = unsaved(path, slot, tick.default_ref(path))
    if why:
        return "; ".join(why)
    if slot in ctx.get("waiting", set()) | ctx.get("landing", set()):
        return "it has a merge queue ticket or the boss paused it"
    if slot in logstate.waiting_for_user(ctx.get("log", [])):
        return "it waits for the user's answer"
    for a in sessions(agents, path):
        if a.get("state") in BUSY:
            return f"its agent {a.get('pane_id')} is {a['state']}"
        if int(slot) >= 10 and now_ms - (a.get("since") or 0) < QUIET * 1000:
            return f"its session {a.get('pane_id')} was active in the last {QUIET // 60} min"
    if build(path):
        return "a build or test runs in it"
    return None


def subservant_refusal(w: dict, lead: dict, ctx: dict, agents: list[dict], now_ms: float, build) -> str | None:
    """`refusal` for a slot marked plans/LEAD: its work belongs in origin/<lead>, never on main."""
    slot, path = w["slot"], w["path"]
    if lead.get("bad"):
        return lead["error"]
    if int(slot) < SUBSERVANTS_FROM:
        return f"a subservant's slot below {SUBSERVANTS_FROM} (lead {lead['slot']}) is never pruned"
    base = f"origin/{lead['slot']}"
    if not ref_exists(path, base):
        return f"its lead's branch {base} does not exist"
    why = unsaved_for_lead(path, slot, base)
    if why:
        return "; ".join(why)
    if slot in ctx.get("waiting", set()) | ctx.get("landing", set()):
        return "it has a merge queue ticket or the boss paused it"
    if slot in logstate.waiting_for_user(ctx.get("log", [])):
        return "it waits for the user's answer"
    if now_ms - lead["at"] * 1000 < SUBSERVANT_QUIET * 1000:
        return f"its plans/LEAD was written in the last {SUBSERVANT_QUIET // 60} min"
    for a in sessions(agents, path):
        if a.get("state") in BUSY:
            return f"its agent {a.get('pane_id')} is {a['state']}"
        if now_ms - (a.get("since") or 0) < SUBSERVANT_QUIET * 1000:
            return f"its session {a.get('pane_id')} was active in the last {SUBSERVANT_QUIET // 60} min"
    if build(path):
        return "a build or test runs in it"
    return None


def slots(main: str) -> list[dict]:
    """The repository's numbered worktree slots (path, slot, head)."""
    out = []
    for w in mtm_scan.worktrees(main):
        name = Path(w["path"]).name
        if NUMBERED.fullmatch(name):
            out.append({"path": w["path"], "slot": name, "head": git(w["path"], "rev-parse", "HEAD")})
    return sorted(out, key=lambda w: w["slot"])


def scan(main: str, ctx: dict, agents: list[dict], now_ms: float | None = None, build=build_running) -> list[dict]:
    now_ms = now_ms if now_ms is not None else time.time() * 1000
    return [{**w, "why": refusal(w, ctx, agents, now_ms, build)} for w in slots(main)]


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
    state = mtm_scan.state_dir(main)
    try:
        info = disk(main, [main] + [w["path"] for w in mtm_scan.worktrees(main)])
        tmp = state / f".{SIZES_FILE}.tmp"
        tmp.write_text(json.dumps({"at": time.time(), **info}))
        tmp.replace(state / SIZES_FILE)
    finally:
        (state / SIZES_LOCK).unlink(missing_ok=True)


def measured(main: str, now: dt.datetime) -> dict | None:
    """The last `prune.py sizes` result when it is younger than SIZES_EVERY."""
    try:
        info = json.loads((mtm_scan.state_dir(main) / SIZES_FILE).read_text())
    except (OSError, ValueError):
        return None
    return info if now.timestamp() - info.get("at", 0) < SIZES_EVERY else None


def measure_later(main: str, spawn=subprocess.Popen) -> bool:
    """Start `prune.py sizes` detached, one at a time (a lock older than SIZES_STALE is taken over)."""
    lock = mtm_scan.state_dir(main) / SIZES_LOCK
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


def plan(item: dict, ctx: dict, found: list[dict] | None = None, info: dict | None = None) -> list[dict]:
    """The prune duty's actions this round (see the module doc)."""
    main = ctx["main"]
    if found is None:
        found = scan(main, ctx, list(ctx.get("agents_by_pane", {}).values()))
    me = [sys.executable, str(HERE / "prune.py")]
    out, removed = [], False
    for w in found:
        if w["why"]:
            continue
        if int(w["slot"]) < 10:
            out.append(act("prune", "clean", "run", w["slot"], key=f"prune:clean:{w['slot']}:{w['head']}",
                           window=30 * 24 * 3600, argv=me + ["clean", w["slot"], "--repo", main],
                           text=f"clean landed slot {w['slot']}'s build artifacts", on_fail=[failed(w, "clean")]))
        elif not removed:
            removed = True
            lead = marker(w["path"])
            text = (f"remove subservant slot {w['slot']} (its work is in origin/{lead['slot']}) with origin/{w['slot']}"
                    if lead else f"remove landed slot {w['slot']} with its branch (origin/{w['slot']} once merged)")
            out.append(act("prune", "remove", "run", w["slot"], key=f"prune:remove:{w['slot']}:{w['head']}",
                           window=3600, argv=me + ["remove", w["slot"], "--repo", main], text=text,
                           on_fail=[failed(w, "remove")]))
    return out + disk_actions(main, ctx, info)


def handler(item: dict, ctx: dict) -> list[dict]:
    return plan(item, ctx)


def live(main: str) -> tuple[dict, list[dict]]:
    """The tick's context (queue, pauses, log) and the agents, read now."""
    ctx = tick.context(main, main, {}, dt.datetime.now(), True)
    return ctx, list(ctx["agents_by_pane"].values())


def stop(main: str, pane: str) -> str | None:
    """delete-worktree-session's stop.py on `pane`: by signal (hal2-cli-agents stop), never a typed `/exit`, which
    was not taken (hal2 plan 0212, 2026-10-08); None when it is gone, else why not (a draft, background tasks)."""
    p = subprocess.run([sys.executable, str(STOP), "stop", pane, "--repo", main, "--wait", str(EXIT_WAIT)],
                       capture_output=True, text=True)
    if p.returncode == 0:
        return None
    if p.returncode == 3:
        return json.loads(p.stdout or "{}").get("refused") or "refused"
    return f"did not stop: {(p.stdout + p.stderr).strip()[-300:]}"


def end_sessions(main: str, path: str, slot: str, dry: bool) -> str | None:
    """End every resting session in the slot by signal; a draft or running background tasks leave it running."""
    for a in sessions(live(main)[1], path):
        pane = a["pane_id"]
        if dry:
            print(f"would stop {pane} in {slot}")
            continue
        refused = stop(main, pane)
        if refused:
            return f"{pane}: not stopped: {refused}"
    return None


def act_on(main: str, slot: str, what: str, dry: bool) -> tuple[int, str]:
    w = next((x for x in slots(main) if x["slot"] == slot), None)
    if w is None:
        return 1, f"no numbered slot {slot} in {main}"
    if (what == "clean") != (int(slot) < 10):
        return 1, f"{what} is for slots {'00-09' if what == 'clean' else '10-99'}"
    lead = marker(w["path"])
    if lead and not lead.get("bad") and what == "remove" and not dry:
        tick.git(main, "fetch", "--quiet", "--prune", "origin")  # checked again against the lead's newest branch
    ctx, agents = live(main)
    why = refusal(w, ctx, agents, time.time() * 1000)
    if why:
        return 0, f"skipped {what} {slot}: {why}"
    if what == "clean":
        argv = [sys.executable, str(CLEANUP), "delete", "--worktree", w["path"]] + (["--dry-run"] if dry else [])
        p = subprocess.run(argv, cwd=w["path"], capture_output=True, text=True)
        return p.returncode, (p.stdout + p.stderr).strip()
    problem = end_sessions(main, w["path"], slot, dry)
    if problem:
        return 0, f"skipped remove {slot}: {problem}"
    if lead:
        return remove_subservant(main, w, lead["slot"], dry)
    argv = ["hal2-cli-git", "worktree", "remove", slot, "--remote"]
    if dry:
        return 0, "would run " + " ".join(argv)
    code, text = tick.sh(argv, main)
    return code, text


def remove_subservant(main: str, w: dict, lead_slot: str, dry: bool) -> tuple[int, str]:
    """A free subservant's slot: `--force` (its branch is not on main by design), then origin/NN deleted once it is
    in origin/<lead> (hal2's `--remote` only deletes a branch origin's default branch contains)."""
    slot, base = w["slot"], f"origin/{lead_slot}"
    remote = ref_exists(main, f"origin/{slot}")
    argv = ["hal2-cli-git", "worktree", "remove", slot, "--force"]
    push = ["git", "push", "--quiet", "origin", "--delete", slot]
    if dry:
        return 0, "would run " + " ".join(argv) + ("; then " + " ".join(push) if remote else "")
    code, text = tick.sh(argv, main)
    if code or not remote:
        return code, text
    if git(main, "rev-list", "--count", f"{base}..origin/{slot}") != "0":
        return 1, f"{text}\norigin/{slot} kept: it holds commits not in {base}"
    pushed, out = tick.sh(push, main)
    return pushed, "\n".join(x for x in (text, out or f"deleted origin/{slot}") if x)


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
        ctx, agents = live(main_dir)
        found = scan(main_dir, ctx, agents)
        print(json.dumps(found, indent=1) if args.json else
              "\n".join(f"{w['slot']}: {w['why'] or 'free'}" for w in found) or "no numbered slots")
        return 0
    if args.cmd == "sizes":
        measure(main_dir)
        return 0
    if not args.slot or not NUMBERED.fullmatch(args.slot):
        print("prune.py: give a two-digit slot (00-99)", file=sys.stderr)
        return 1
    code, text = act_on(main_dir, args.slot, args.cmd, args.dry_run)
    print(text)
    return 1 if code else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
