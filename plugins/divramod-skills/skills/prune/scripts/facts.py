"""Prune's facts (hal2 plan 0377 step 3; contract: design/prune-run/sequence/v1/contract.md): what /prune decides on.

The farm's numbered fields (`hal2-cli-git worktree list --json`), the live sessions (`hal2-cli-agents list --json`),
the proof per field (prune_proof.py, the global record never-delete-unsaved-work), the disk, the sizes (sizes.py) and
the config `.hal/prune.toml` (D4, D15, D16). Nothing here changes anything. Every outside call goes through `call`, so
a test replaces it with a fake CLI.
"""

import datetime as dt
import json
import shutil
import subprocess
import time
import tomllib
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import field_facts
import live_sessions
import logstate
import busy
import prune_proof
import responses
import roles
import sizes

NUMBERED = prune_proof.NUMBERED
KEEPER_BELOW, SERVANT_FROM = 10, prune_proof.SUBSERVANTS_FROM
TOOLS = ("git", "hal2-cli-git", "hal2-cli-agents", "hal2-cli-plans")
CONFIG = ".hal/prune.toml"
DEFAULTS = {
    "threshold": {"free_gb": 150, "used_pct": 90},
    "goal": {"free_gb": 250, "used_pct": 85},
    "phases": {"trim_session_less": True, "trim_idle_live": True, "trim": None},  # trim None: cleanup's own set
    "caches": {"paths": [], "tart_older_than_days": 7},  # the disk watermark may clear these (plan 0472 D2); no pattern
}


class ToolMissing(Exception):
    """A CLI prune needs is not installed (prune.py exits 2)."""


class FactsError(Exception):
    """A tool answered something prune cannot read, or the config is invalid (prune.py exits 1)."""


def missing_tools() -> list[str]:
    return [t for t in TOOLS if not shutil.which(t)]


def call(argv: list[str], cwd: str | None = None, timeout: int = 120) -> str:
    """stdout of `argv`; "" on a non-zero exit or a timeout; ToolMissing when the program is not there."""
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        raise ToolMissing(argv[0]) from e
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return p.stdout if p.returncode == 0 else ""


def call_json(argv: list[str], cwd: str | None = None):
    out = call(argv, cwd)
    try:
        return json.loads(out) if out.strip() else None
    except json.JSONDecodeError:
        return None


def kind(slot: str) -> str:
    """keeper 00-09 (only ever mucked out), foreman 10-29, servant 30-99 (persistent-fields-00-09, D6)."""
    n = int(slot)
    return "keeper" if n < KEEPER_BELOW else "servant" if n >= SERVANT_FROM else "foreman"


def fields(main: str) -> list[dict]:
    """The farm's numbered fields `{slot, path, branch, kind, head}` in field order (names-ok: the key `slot`; never main, a role field or a
    name that is not two digits)."""
    data = call_json(["hal2-cli-git", "worktree", "list", "--json"], main)
    if not isinstance(data, dict) or not isinstance(data.get("worktrees"), list):
        raise FactsError("hal2-cli-git worktree list --json gave no worktrees")
    out = []
    for w in data["worktrees"]:
        name = str(w.get("name", ""))
        if w.get("main") or not NUMBERED.fullmatch(name) or not w.get("path"):
            continue
        out.append({"slot": name, "path": w["path"], "branch": w.get("branch"), "kind": kind(name),
                    "head": prune_proof.git(w["path"], "rev-parse", "HEAD")})
    return sorted(out, key=lambda f: f["slot"])


def agents(main: str) -> list[dict] | None:
    """Every agent session `hal2-cli-agents list --json` knows (all repositories), by the farmer's one lookup
    (live_sessions.read, hal2 plan 0412): None when the list cannot be read, never an empty list (the proof then
    refuses every field)."""
    return live_sessions.read(lambda argv: call_json(argv, main))


def session(field: dict, rows: list[dict] | None) -> list[dict]:
    """The field's live sessions as `{pane_id, state, since}` (an ended one is none; a failed one is live)."""
    if rows is None:
        return []
    return [{"pane_id": a.get("pane_id"), "state": a.get("state"), "since": a.get("since")}
            for a in prune_proof.sessions(rows, field["path"])]


def context(main: str, now: dt.datetime | None = None) -> dict:
    """What the proof reads besides git: the queue's tickets and landing, the bosses' pauses and the open questions
    in the tollman's and the farmer's logs (prune_proof.held)."""
    now = now or dt.datetime.now()
    queue = call_json(["hal2-cli-git", "worktree", "queue", "--json"], main) or {}
    tickets = queue.get("queue", []) if isinstance(queue, dict) else []
    landing = {t.get("slot") for t in tickets if t.get("state") == "active"
               or (t.get("hold") or {}).get("reason") == "reserved"}
    return {"main": main, "now": now, "landing": landing,
            "waiting": {t.get("slot") for t in tickets} | logstate.paused_by_any_boss(main, now),
            "log": logstate.read_log(main, "tollman"), "farmer_log": logstate.read_log(main, roles.ROLE)}


def proofs(fs: list[dict], ctx: dict, rows: list[dict] | None, now_ms: float | None = None,
           build=prune_proof.build_running) -> dict[str, str | None]:
    """{slot: None when the field is free, else why not}, one field after the other (D14: only measuring runs in
    parallel)."""
    now_ms = now_ms if now_ms is not None else time.time() * 1000
    return {f["slot"]: prune_proof.refusal(f, ctx, rows, now_ms, build) for f in fs}


def disk(main: str) -> dict:
    """The volume of the main checkout: `{free_gb, used_pct, total_gb}`."""
    u = shutil.disk_usage(main)
    return {"free_gb": round(u.free / 1e9, 1), "used_pct": round(u.used / u.total * 100, 1) if u.total else 0.0,
            "total_gb": round(u.total / 1e9, 1)}


def config(main: str) -> dict:
    """`.hal/prune.toml` of the main checkout over DEFAULTS: `{source, path, threshold, goal, phases}`. An invalid
    file raises FactsError naming every problem (a bad `trim` entry would be a path to delete). The goal must be
    at least as strict as the threshold, else a run could stop at the edge it started at (D15)."""
    path = Path(main) / CONFIG
    cfg = {k: dict(v) for k, v in DEFAULTS.items()}
    if not path.is_file():
        return {"source": "defaults", "path": str(path), **cfg}
    try:
        raw = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise FactsError(f"{path}: {e}") from e
    problems = []
    for section, values in raw.items():
        if section not in cfg or not isinstance(values, dict):
            problems.append(f"unknown section [{section}]")
            continue
        for key, value in values.items():
            if key not in DEFAULTS[section]:
                problems.append(f"unknown key {section}.{key}")
            elif (why := bad_value(section, key, value)):
                problems.append(f"{section}.{key}: {why}")
            else:
                cfg[section][key] = value
    t, g = cfg["threshold"], cfg["goal"]
    if g["free_gb"] < t["free_gb"] or g["used_pct"] > t["used_pct"]:
        problems.append("goal must be at least as strict as threshold (free_gb not lower, used_pct not higher)")
    if problems:
        raise FactsError(f"{path}: " + "; ".join(problems))
    return {"source": "file", "path": str(path), **cfg}


def bad_value(section: str, key: str, value) -> str | None:
    """Why `value` is not valid for the key, None when it is."""
    if key == "paths":
        if not isinstance(value, list) or not all(isinstance(p, str) and p for p in value):
            return "a list of folders"
        return next((f"{p!r} must be one folder, no pattern" for p in value if any(c in p for c in "*?[]")), None)
    if key == "trim":
        if not isinstance(value, list) or not all(isinstance(p, str) and p for p in value):
            return "a list of paths"
        for p in value:
            parts = Path(p).parts
            if Path(p).is_absolute() or ".." in parts or (parts and parts[0] in (".git", ".hal", ".secrets", "plans")):
                return f"{p!r} must stay inside the field and outside .git, .hal, .secrets and plans"
        return None
    if isinstance(DEFAULTS[section][key], bool):
        return None if isinstance(value, bool) else "true or false"
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return "a number of at least 0"
    return "at most 100" if key == "used_pct" and value > 100 else None


def short_of_space(d: dict, cfg: dict) -> bool:
    """Phases 2-3 start: under the threshold's free GB or over its used percent."""
    return d["free_gb"] < cfg["threshold"]["free_gb"] or d["used_pct"] > cfg["threshold"]["used_pct"]


def above_goal(d: dict, cfg: dict) -> bool:
    """The watermark's warning level (plan 0472 D2): over the goal's used percent or under its free GB."""
    return not goal_met(d, cfg)


def goal_met(d: dict, cfg: dict) -> bool:
    return d["free_gb"] >= cfg["goal"]["free_gb"] and d["used_pct"] <= cfg["goal"]["used_pct"]


def collect(main: str, now: dt.datetime | None = None, build=prune_proof.build_running, measure=sizes.measure_all,
            only: set[str] | None = None, lookup=field_facts.plan_state,
            cached_sizes: bool = False) -> dict:
    """The facts: the disk, the config, the last train's cars and per field its kind, sessions, proof, size and what
    field_facts adds (`only`: those fields;
    `cached_sizes`: sizes from the cache only, a miss is unknown). `now_ms` is the clock the proof used."""
    cfg = config(main)
    every = fields(main)
    fs = [f for f in every if only is None or f["slot"] in only]
    rows = agents(main)
    ctx = context(main, now)
    now_ms = time.time() * 1000
    why = proofs(fs, ctx, rows, now_ms, build)
    wait = busy.reason(main)  # a train builds: no size walk (plan 0472 D1), the cache only
    size = measure(main, fs, cached_only=True) if cached_sizes or wait else measure(main, fs)
    now_disk = disk(main)
    answers = responses.candidates(main, cfg, [main] + [f["path"] for f in every],
                                   measured=not (cached_sizes or wait) and short_of_space(now_disk, cfg))
    more = field_facts.extra(fs, ctx, main, {s: w is None for s, w in why.items()}, lookup, build)
    return {"main": main, "now_ms": now_ms, "busy": wait, "responses": answers, "disk": now_disk, "config": cfg, "cars": field_facts.last_cars(main),
            "fields": [{**f, "sessions": session(f, rows), "free": why[f["slot"]] is None, "proof": why[f["slot"]],
                        "size": size.get(f["slot"]), **more[f["slot"]]} for f in fs]}
