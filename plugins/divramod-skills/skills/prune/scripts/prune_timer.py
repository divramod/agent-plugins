#!/usr/bin/env python3
"""The farm's prune timer, from the repo (hal2 plan 0695 step 14, gap 03, D31): launchd's tick, the round it starts and the
plist's installer in one script, replacing the hand-made `prune-tick.sh` (in the farmer folder of the hal config root) and `prune-round.py`
(whose bare launchd PATH did not find `hal2-cli-runs`: the farm's prune stood still for 27-29 hours, unseen).

  prune_timer.py tick --repo <farm> [--state <dir>] [--long-minutes 30] [--interval 1200]
      launchd's call (every 5 min): starts a round detached when the last one is older than `--interval` and none runs;
      alarms ONCE per incident (alarm.py, a push): a round that ends non-zero (until a round passes again) and a round
      running over `--long-minutes`. A quiet tick prints nothing.
  prune_timer.py round --repo <farm> --state <dir> --id <n>
      one round: `hal2-cli-runs exec --workflow prune -- prune.py run --repo <farm>` (the disk phase is its first job; one
      field's failure never stops the others, executor.py: the round reports it and exits 1); writes its end to the state.
  prune_timer.py install --repo <farm> [--dry-run] [--load] [--long-minutes 30] [--launch-agents <dir>]
      writes `local.farmer.prune.<repo>.plist`: `python3 prune_timer.py tick` with an EXPLICIT PATH (the dirs of
      hal2-cli-runs, git and python3 found now, then cargo, brew and the system's), no login shell; `--load` also
      (re)loads it with launchctl, else prints that command. `--dry-run` prints the plist and writes nothing.
  prune_timer.py status --repo <farm>      the timer's line (as `due.py check` shows it); exit 1 when dead or red.

State: `prune-timer.json` of the farmer's state folder (timer_state.py, the farmer skill, defines it). Stdlib only.
"""

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's modules on the import path)
import mtm_scan
import roles
import timer_state as ts

HERE = Path(__file__).resolve().parent
LABEL = "local.farmer.prune.{}"
TICK = 300
INTERVAL = 20 * 60
LONG_MINUTES = 30
SYSTEM_PATH = ["/usr/bin", "/bin", "/usr/sbin", "/sbin"]
TOOLS = ("python3", "hal2-cli-runs", "git")  # python3 first: its dir leads the PATH (the farmer scripts need 3.10+)
LOG = "prune-round.log"
CAUSE = ("failed:", "error", "refus", "not installed")


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def push(case: str, reason: str, repo: str) -> None:
    import alarm  # here: alarm imports the farmer's journal, which a test never needs
    alarm.alarm(case, reason, repo)


def cause(folder: Path) -> str:
    """Why the round failed: each failed field's reason (state, else the round log), else the log's last lines naming it."""
    state = ts.load(folder) or {}
    why = (state.get("round") or {}).get("failed") or failures(folder)
    if why:
        return "; ".join(f"{x['field']} {x['action']}: {x['reason']}" for x in why)[:600]
    try:
        lines = (folder / LOG).read_text(errors="replace").splitlines()
    except OSError:
        return "no round log"
    hits = [x.strip() for x in lines if any(c in x.lower() for c in CAUSE)]
    return " | ".join(hits[-3:])[:300] or (lines[-1][:200] if lines else "empty round log")


def failures(folder: Path) -> list[dict]:
    """The failed fields of the round log (executor_out's `failure <field> <action>: <reason>` lines): what failed and why."""
    try:
        lines = (folder / LOG).read_text(errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for x in lines:
        head, _, why = x.partition(": ")
        parts = head.split()
        if len(parts) == 3 and parts[0] == "failure":
            out.append({"field": parts[1], "action": parts[2], "reason": why.strip()})
    return out


def spawn(repo: str, folder: Path, rid: int) -> int:
    argv = [sys.executable, str(Path(__file__).resolve()), "round", "--repo", repo, "--state", str(folder), "--id", str(rid)]
    with (folder / "prune-tick.out").open("ab") as out:
        return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=out, start_new_session=True,
                                cwd=repo).pid


def end_vanished(state: dict, now: float) -> None:
    r = state.get("round") or {}
    if r and r.get("ended") is None and not alive(r.get("pid", 0)):
        r.update(ended=now, rc=r.get("rc") if r.get("rc") is not None else -1)  # killed before it wrote its end


def alarms(state: dict, folder: Path, repo: str, now: float, long_min: int, alarm) -> None:
    r, seen = state.get("round") or {}, state["seen"]
    if r.get("ended") is None and r.get("started") is not None and (now - r["started"]) / 60 > long_min and seen.get("long") != r["id"]:
        seen["long"] = r["id"]
        alarm("prune-long", f"the prune round runs for {ts.minutes(now - r['started'])} (over {long_min} min): "
                            f"hal2-cli-runs list, {folder / LOG}", repo)
    if r.get("ended") is not None and r.get("rc") == 0:
        seen["fail_open"] = False
    elif r.get("ended") is not None and not seen.get("fail_open"):
        seen["fail_open"] = True  # one alarm per incident: the next red rounds are the same one until a round passes
        alarm("prune-failed", f"the prune round ended red (exit {r.get('rc')}): {cause(folder)}", repo)


def tick(repo: str, folder: Path, now: float, long_min: int = LONG_MINUTES, interval: int = INTERVAL,
         start=spawn, alarm=push) -> str:
    state = ts.load(folder) or {"label": LABEL.format(Path(mtm_scan.main_checkout(repo)).name), "round": {}, "seen": {}}
    state.setdefault("seen", {})["ticked"] = now
    end_vanished(state, now)
    alarms(state, folder, repo, now, long_min, alarm)
    r, said = state.get("round") or {}, "waiting"
    if r.get("ended") is None and r.get("started") is not None:
        said = "running"
    elif not r or now - r["started"] >= interval:
        rid = int(now)
        state["round"] = {"id": rid, "pid": 0, "started": now, "ended": None, "rc": None}
        ts.save(folder, state)  # the round is on file before it starts: a second tick never starts a second one
        state["round"]["pid"] = start(repo, folder, rid)
        said = "started"
    ts.save(folder, state)
    return said


def round_(repo: str, folder: Path, rid: int, run=subprocess.run) -> int:
    """One round; its output is the round log's. A tool that cannot start is exit 127, never a traceback."""
    argv = ["hal2-cli-runs", "exec", "--workflow", "prune", "--", sys.executable, str(HERE / "prune.py"), "run",
            "--repo", repo]
    try:
        rc = run(argv, cwd=repo, stdin=subprocess.DEVNULL, stdout=(folder / LOG).open("wb"), stderr=subprocess.STDOUT).returncode
    except OSError as e:
        (folder / LOG).write_text(f"error: {argv[0]}: {e} (PATH {os.environ.get('PATH', '')})\n")
        rc = 127
    state = ts.load(folder) or {"round": {}, "seen": {}}
    if (state.get("round") or {}).get("id") == rid:
        state["round"].update(ended=time.time(), rc=rc, failed=failures(folder))  # a red round says why in its state
        ts.save(folder, state)
    return rc


def path_dirs(which=shutil.which, home: Path | None = None) -> list[str]:
    """The explicit PATH: the dirs of the tools found now, then cargo, brew and the system's (no login shell, D31)."""
    home = home or Path.home()
    found = [str(Path(p).parent) for t in TOOLS if (p := which(t))]
    out: list[str] = []
    for d in [*found, str(home / ".cargo/bin"), "/opt/homebrew/bin", "/usr/local/bin", *SYSTEM_PATH]:
        if d not in out:
            out.append(d)
    return out


def plist(repo: str, folder: Path, long_min: int, path: list[str], label: str, python: str) -> dict:
    return {"Label": label,
            "ProgramArguments": [python, str(Path(__file__).resolve()), "tick", "--repo", repo,
                                 "--long-minutes", str(long_min)],
            "EnvironmentVariables": {"PATH": ":".join(path)}, "StartInterval": TICK, "RunAtLoad": True,
            "StandardOutPath": str(folder / "prune-tick.out"), "StandardErrorPath": str(folder / "prune-tick.out")}


def install(repo: str, folder: Path, args, which=shutil.which, run=subprocess.run) -> int:
    missing = [t for t in TOOLS if not which(t)]
    if missing:
        print(f"prune_timer: not installed: {', '.join(missing)}", file=sys.stderr)
        return 2
    label = LABEL.format(Path(mtm_scan.main_checkout(repo)).name)
    data = plist(repo, folder, args.long_minutes, path_dirs(which), label, which('python3'))
    target = Path(args.launch_agents).expanduser() / f"{label}.plist"
    if args.dry_run:
        print(f"would write {target}:\n{plistlib.dumps(data).decode()}")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(plistlib.dumps(data))
    domain = f"gui/{os.getuid()}"
    print(f"wrote {target}")
    if not args.load:
        print(f"load it: launchctl bootout {domain}/{label}; launchctl bootstrap {domain} {target}")
        return 0
    run(["launchctl", "bootout", f"{domain}/{label}"], capture_output=True)  # not loaded yet is fine
    return run(["launchctl", "bootstrap", domain, str(target)]).returncode


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="prune_timer.py", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("tick", "round", "install", "status"):
        x = sub.add_parser(name)
        x.add_argument("--repo", default=os.getcwd())
        x.add_argument("--state", default=None, help="the state folder (default: the farmer's roles/farmer/)")
        x.add_argument("--long-minutes", type=int, default=LONG_MINUTES)
    sub.choices["tick"].add_argument("--interval", type=int, default=INTERVAL)
    sub.choices["round"].add_argument("--id", type=int, required=True)
    sub.choices["install"].add_argument("--dry-run", action="store_true")
    sub.choices["install"].add_argument("--load", action="store_true")
    sub.choices["install"].add_argument("--launch-agents", default="~/Library/LaunchAgents")
    args = ap.parse_args(argv)
    folder = Path(args.state) if args.state else roles.state_dir(args.repo)
    if args.cmd == "round":
        return round_(args.repo, folder, args.id)
    if args.cmd == "install":
        return install(args.repo, folder, args)
    if args.cmd == "status":
        text = ts.line(folder)
        print(text)
        return 1 if "DEAD" in text or "RED" in text or "no state" in text else 0
    said = tick(args.repo, folder, time.time(), args.long_minutes, args.interval)
    if said == "started":
        print(f"prune_timer: round started ({time.strftime('%F %T')})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
