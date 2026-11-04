"""The role timers' answer to hal2-machine's standard installer contract (hal2 plan 0581, step 6b).

`<cli> timer install|enable|disable|status --json` prints one line, `{schema, job, state, enabled, last_exit,
last_run, message}` (hal2-machine's `InstallerReply`, schema 1, pinned there by tests/fixtures/installer/*.json), and
exits 0, or 3 when no timer is installed. Exit 4 (needs an administrator) never happens: the timers are the user's own
LaunchAgents and systemd user units. The job is `<role>-timer` (the catalog's id), for the farmer, the tollman and the
lookout; the verbs run over timer.py (launchd on macOS, systemd on Linux), every system call through `timer.run`.

    install  the role's own install (timer.install: unit files, load, mode `timer`)
    enable   load the installed timer again (mode `timer`); nothing to do when it is loaded
    disable  stop the timer, keep its files (mode `claude`); nothing to do when it is stopped
    status   missing (no files, not loaded), disabled (files, not loaded), failing (loaded and the last run exited
             non-zero, or the role's own `down` check fires), else installed

`last_run` is the tick log's modification time (every tick appends to it), `last_exit` the system's view (timer.probe).
"""

import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path

import roles
import timer

SCHEMA = 1
STATES = ("installed", "missing", "disabled", "failing")
FIELDS = ("schema", "job", "state", "enabled", "last_exit", "last_run", "message")
ACTIONS = ("install", "enable", "disable", "status")
MISSING = 3  # the contract's exit code: not installed


def job_id(wiring: roles.Wiring) -> str:
    return f"{wiring.role}-timer"


def last_run(state: Path) -> str | None:
    """The tick log's modification time, RFC 3339 UTC; None before the first tick."""
    try:
        mtime = (state / "tick.log").stat().st_mtime
    except OSError:
        return None
    return dt.datetime.fromtimestamp(mtime, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def reply(name: str, state: Path, wiring: roles.Wiring, down: Callable[[], str | None] | None = None) -> dict:
    """The status as the contract's reply. `down`: the role's own health check, a message when it is not ticking."""
    unit, seen = timer.label(name, wiring), timer.probe(name, wiring)
    present = [p for p in timer.files(name, wiring) if p.exists()]
    cron = timer.installed(state).get("cron")
    out = {"schema": SCHEMA, "job": job_id(wiring), "state": "installed", "enabled": True,
           "last_exit": seen["last_exit"], "last_run": last_run(state), "message": ""}
    if not present and not seen["loaded"]:
        out.update(state="missing", enabled=False, last_run=None, message=f"{unit} is not installed")
    elif not seen["loaded"]:
        out.update(state="disabled", enabled=False, message=f"{unit} is installed and stopped")
    elif len(present) != len(timer.files(name, wiring)):
        out.update(state="failing", message=f"{unit} is loaded but its unit files are gone")
    elif seen["last_exit"] not in (None, 0):
        out.update(state="failing", message=f"{unit}: the last run exited {seen['last_exit']}")
    elif (late := down() if down else None):
        out.update(state="failing", message=f"{unit}: {late}")
    else:
        out["message"] = f"{unit} runs on cron {cron}" if cron else f"{unit} is loaded"
    return out


def line(r: dict) -> str:
    """The reply as one compact JSON line, the fields in the contract's order."""
    return json.dumps({k: r[k] for k in FIELDS}, separators=(",", ":"))


def apply(action: str, name: str, state: Path, wiring: roles.Wiring, install: Callable[[], object],
          down: Callable[[], str | None] | None = None) -> tuple[int, dict]:
    """Run the verb, then read the status back (status decides). `install` does the role's own install and may raise
    RuntimeError or ValueError (the caller says so, exit 2). enable and disable of a timer that is not installed
    change nothing and answer missing."""
    before = reply(name, state, wiring, down)
    if action == "install":
        install()
    elif before["state"] != "missing":
        if action == "enable" and before["state"] == "disabled":
            timer.load(name, state, wiring)
        elif action == "disable" and before["state"] != "disabled":
            timer.unload(name, state, wiring)
    now = reply(name, state, wiring, down)
    return (MISSING if now["state"] == "missing" else 0), now


def problems(r: object) -> list[str]:
    """Why `r` is not an InstallerReply of schema 1 (hal2-machine's installer.rs); empty when it is one."""
    if not isinstance(r, dict):
        return ["not an object"]
    out = [f"fields {list(r)} are not {list(FIELDS)}"] if list(r) != list(FIELDS) else []
    kinds = {"schema": (int,), "job": (str,), "state": (str,), "enabled": (bool,), "last_exit": (int, type(None)),
             "last_run": (str, type(None)), "message": (str,)}
    for key, types in kinds.items():
        if key in r and (not isinstance(r[key], types) or (key != "enabled" and isinstance(r[key], bool))):
            out.append(f"{key} is {r[key]!r}")
    if r.get("schema") != SCHEMA:
        out.append(f"schema is {r.get('schema')!r}")
    if r.get("state") not in STATES:
        out.append(f"state is {r.get('state')!r}")
    if isinstance(r.get("last_run"), str):
        try:
            dt.datetime.fromisoformat(r["last_run"].replace("Z", "+00:00"))
        except ValueError:
            out.append(f"last_run is {r['last_run']!r}")
    return out
