"""The foreman's plan through `hal2-cli-plans --json` (hal2 plan 0409 step 6): either home of the farm, its plans folder or
its plan store, answers the same, so the page never reads a plan file itself. Read-only, no model call; a missing CLI,
a failure or garbage gives None, and the page falls back to the files (a machine without the CLI yet).

- `plan(root, slug)`: `show <slug> --repo <root> --json` as the page's plan dict (title, description, landing, land,
  steps, done, total, next).
- `open_questions(root, slug)`: `questions list --open --json --plan <slug>` as `Q<n>: <question>` lines.
- `store(root)`: the farm's plan store as page lines: its home (`home --json`) and, when the farm has a store, its state
  ref (`state status --json`): sync on or off and why, a locked gpg agent, the conflicts, the unsynced records.

`HAL2_CLI_PLANS` names another binary (a test's debug build).
"""

import json
import os
import subprocess
from pathlib import Path

TIMEOUT = 15
MAX_TITLE = 140


def cli() -> str:
    return os.environ.get("HAL2_CLI_PLANS") or "hal2-cli-plans"


def run(args: list[str]) -> dict | None:
    """The CLI's JSON answer to `args`, None when it is missing, fails or answers no object."""
    try:
        done = subprocess.run([cli(), *args], capture_output=True, text=True, timeout=TIMEOUT, check=False)
        found = json.loads(done.stdout) if done.returncode == 0 and done.stdout.strip() else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def after_landing(step: dict) -> bool:
    return str(step.get("done_when") or "").lower().startswith("after the landing")


def is_done(step: dict) -> bool:
    return str(step.get("status") or "").lower().startswith("done")


def plan(root: str | Path, slug: str) -> dict | None:
    """The plan `slug` of the checkout `root` as the page shows it; None without an answer."""
    raw = run(["show", slug, "--repo", str(root), "--json"])
    if not raw or not isinstance(raw.get("steps"), list):
        return None
    steps = [{"number": str(s.get("number", "")), "step": s.get("step", ""), "done_when": s.get("done_when", ""),
              "status": s.get("status", "")} for s in raw["steps"] if isinstance(s, dict)]
    for s in steps:
        s["after_landing"] = after_landing(s)
    open_steps = [s for s in steps if not is_done(s)]
    before = [s for s in open_steps if not s["after_landing"]]
    landing = raw.get("landing") or ""
    land = landing if landing != "auto" else ("wait" if before else "ready")
    return {"slug": slug, "title": raw.get("title") or slug, "description": raw.get("goal") or "",
            "landing": landing, "land": land if landing else "", "steps": steps,
            "done": len(steps) - len(open_steps), "total": len(steps), "next": (before or open_steps or [None])[0]}


def open_questions(root: str | Path, slug: str) -> list[str] | None:
    """`Q31: <the question>` for each open question of the plan; None without an answer."""
    raw = run(["questions", "list", "--open", "--json", "--repo", str(root), "--plan", slug])
    entries = raw.get("entries") if raw else None
    if not isinstance(entries, list):
        return None
    out = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        line = " ".join(str(e.get("question") or "").split())
        line = f"{line[:MAX_TITLE]}{'…' if len(line) > MAX_TITLE else ''}"
        out.append(f"Q{e.get('n')}: {line}" if line else f"Q{e.get('n')}")
    return out


def store(root: str | Path) -> list[str] | None:
    """The farm's plan store as lines; None when the farm has none (or the CLI does not answer)."""
    home = run(["home", "--repo", str(root), "--json"])
    if not home or not home.get("store"):
        return None
    lines = [f"Home: {home.get('home') or 'files'} (farm {home['farm']})"]
    state = run(["state", "status", "--repo", str(root), "--json"])
    if not state:
        return lines + ["Sync: unknown (hal2-cli-plans state status did not answer)"]
    if state.get("sync") == "on":
        lines.append(f"Sync: on, to {state.get('remote')}; {state.get('unsynced', 0)} records not synced yet")
    else:
        lines.append(f"Sync: off: {state.get('why') or 'unknown'}")
    if state.get("locked"):
        lines.append("The gpg agent is locked: unlock it, a sync waits for it")
    if state.get("conflicts"):
        lines.append(f"Conflicts: {state['conflicts']} (hal2-cli-plans conflicts)")
    return lines
