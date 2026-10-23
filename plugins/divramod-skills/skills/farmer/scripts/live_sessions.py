"""The live agent sessions of a farm's fields, one lookup for every rule that must not start into a held field (hal2
plan 0412, D2): the boss's work-without-agent and orphaned-servant findings (mtm_scan), the tollman's start guard
(boss.orphan) and the prune proof.

A live session is any `hal2-cli-agents list --json` entry of the checkout whose state is not `ended` (hal2's "gone"),
whatever its kind and its host: a tmux pane (`%<n>`) or a terminal host (`t:<id>`, `session: terminal`), sleeping,
idle, done and failed included, as `hal2-cli-git worktree run` refuses a field (occupied.rs). A list that cannot be
read is no empty list: `read` gives None, and its callers fail closed (2026-10-20: a list read that failed under load
made every field "no agent session", and the orphan rule started `/handoff c` into fields holding sessions).
"""

import json
import os
import subprocess

LIST = ["hal2-cli-agents", "list", "--json"]
BUSY = {"working", "starting"}
GONE = "ended"
UNKNOWN = "unknown"  # a field's agent_state when the list could not be read: never "no session"
TIMEOUT = 120  # seconds; the list takes 2 s on a quiet Mac, a loaded one has needed far more


def read(run_json=None) -> list[dict] | None:
    """Every entry of `hal2-cli-agents list --json`, or None when the list cannot be read (the CLI is missing, fails,
    times out, prints no or broken JSON, or a body without an `agents` list). `run_json(args)` answers like
    mtm_scan.run_json (parsed JSON or None); without one the CLI is asked here."""
    data = run_json(LIST) if run_json else _ask()
    rows = data.get("agents") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return None
    return [a for a in rows if isinstance(a, dict)]


def _ask():
    try:
        out = subprocess.run(LIST, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    try:
        return json.loads(out.stdout) if out.returncode == 0 and out.stdout.strip() else None
    except json.JSONDecodeError:
        return None


def live(agent: dict) -> bool:
    """The entry is a live session: any state but `ended`; an entry without a state counts (fail closed)."""
    return agent.get("state") != GONE


def key(path: str) -> str:
    return os.path.realpath(path)


def by_checkout(agents: list[dict]) -> dict[str, dict]:
    """The live session of each checkout (tmux and terminal host alike), keyed by the checkout as listed and by its
    realpath; a busy one (working, starting) wins over the others."""
    by: dict[str, dict] = {}
    for a in agents:
        if not a.get("checkout") or not live(a):
            continue
        for k in {a["checkout"], key(a["checkout"])}:
            prev = by.get(k)
            if prev is None or (a.get("state") in BUSY and prev.get("state") not in BUSY):
                by[k] = a
    return by


def session_of(by: dict[str, dict], path: str) -> dict | None:
    """The live session of the field at `path` from `by_checkout`'s map, matched by the path or its realpath."""
    return by.get(path) or by.get(key(path))


def live_session(agents: list[dict] | None, path: str) -> dict | None:
    """The start guard's and the prune proof's question: the live session in the field at `path`. With an unreadable
    list (None) the answer is a stand-in entry `{"state": "unknown"}`: never start, never remove."""
    if agents is None:
        return {"state": UNKNOWN, "checkout": path, "pane_id": None}
    return session_of(by_checkout(agents), path)
