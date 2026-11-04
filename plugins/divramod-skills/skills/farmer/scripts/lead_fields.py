"""A foreman's field as the farmer's foreman duty sees it (hal2 plan 0514 D2-D4, D8, D16): its plan's run state, its merge queue
ticket, a push under way, whether its plan is done or landed, and the foreman class that follows.

- `sources(main, queue_doc)`: the round's two documents, each read once per scan: the merge queue (`hal2-cli-git
  worktree queue --json`, the tick's `queue_doc` when given) and the workqueue (`hal2-cli-workqueue status --json`).
- `facts(agent, checkout, src, default)`: {run_state, ticket, push, plan_done, landed} of the field. The run state is
  read by the plan skill's own reader (`runstate.read`, no copy of the format); a ticket and a workqueue job belong to
  the field by its path (`worktree`, `cwd`) or the workqueue's `<repo>/<NN>`, never by a field number or a session
  name prefix (D16: jobsearch's field 02 is not hal2's).
- `kind(agent)`: (kind, why) for an idle foreman's field, else None. In this order: `landed` (state landed, or the plan
  done, no ticket, nothing ahead of the default branch), `pushing` (state pushing, a push job in the workqueue or a
  live shell running `git push`; the why names the hold), `hitched` (a queue ticket or state hitched), `waiting` and
  `blocked` (the state's why), `done-not-hitched` (every step done or state done, no ticket).

None of these kinds is ever nudged here: the foreman duty records them (no send, no wake, 0 tokens); step 5 of plan 0514
gives `done-not-hitched` and `landed` their actions. Fields 09, 23 and 29 (2026-10-30) sat in `git push` behind a
workqueue hold and were nudged to start over: their replay is `testdata/lead-0930/`.
"""

import os
import re
import sys
from pathlib import Path

import lead_marker
import live_sessions
import mtm_scan

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import load, pointers as _pointers  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)

_pointers(__file__)  # runstate.py imports the plan skill's `pointers` by its bare name: load it first
try:
    runstate = load("plan", "runstate", __file__)
except Exception:  # noqa: BLE001  (a broken plan skill never fails the round)
    runstate = None

KINDS = ("landed", "pushing", "hitched", "waiting", "blocked-plan", "done-not-hitched")
QUEUE = ["hal2-cli-git", "worktree", "queue", "--json"]
WORKQUEUE = ["hal2-cli-workqueue", "status", "--json"]
PUSH = re.compile(r"\bgit\s+push\b|pre-push", re.I)


def sources(main: str, queue_doc: dict | None = None, run_json=None) -> dict:
    """The merge queue and the workqueue, read once; an unreadable one is an empty document."""
    run_json = run_json or (lambda args: mtm_scan.run_json(args, main))
    queue = queue_doc if queue_doc is not None else run_json(QUEUE)
    wq = run_json(WORKQUEUE)
    return {"queue": queue if isinstance(queue, dict) else {}, "workqueue": wq if isinstance(wq, dict) else {}}


def real(path) -> str:
    return os.path.realpath(str(path)) if path else ""


def run_state(checkout: Path) -> dict | None:
    """{plan, state, why, at} of the plan the field's CURRENT_PLAN names; None without one (or no plan skill)."""
    if runstate is None:
        return None
    try:
        return runstate.read(checkout)
    except Exception:  # noqa: BLE001
        return None


def ticket(checkout: Path, queue: dict) -> dict | None:
    """The field's merge queue entry, by its worktree path."""
    me = real(checkout)
    return next((t for t in queue.get("queue") or [] if isinstance(t, dict) and real(t.get("worktree")) == me), None)


def _mine(job: dict, checkout: Path) -> bool:
    if job.get("field") == f"{checkout.parent.name}/{checkout.name}":
        return True
    cwd = real(job.get("cwd"))
    return bool(cwd) and (cwd + os.sep).startswith(real(checkout) + os.sep)


def _text(job: dict) -> str:
    return " ".join(str(job.get(k) or "") for k in ("head", "command", "cmd", "argv", "description", "class"))


def hold_named(checkout: Path, wq: dict) -> str:
    """What the field's push waits behind, from the workqueue: another field's hold, else its own place."""
    holds = [h for h in wq.get("holds") or [] if isinstance(h, dict) and not _mine(h, checkout)]
    if holds:
        return "behind " + ", ".join(f"{h.get('field') or '?'} ({h.get('class') or 'hold'})" for h in holds[:3])
    return "in the workqueue" if any(_mine(j, checkout) for j in wq.get("waiting") or [] if isinstance(j, dict)) \
        else "pre-push hook"


def push(agent: dict, checkout: Path, state: dict | None, wq: dict) -> str | None:
    """Why the field is pushing, or None: state pushing, a push job of the field in the workqueue, or a live shell."""
    jobs = [j for key in ("running", "waiting", "frozen", "live") for j in wq.get(key) or []
            if isinstance(j, dict) and _mine(j, checkout) and PUSH.search(_text(j))]
    shells = [t for t in live_sessions.background(agent) if PUSH.search(_text(t))]
    if not (state and state["state"] == "pushing") and not jobs and not shells:
        return None
    where = hold_named(checkout, wq)
    said = state["why"] if state and state["state"] == "pushing" and state.get("why") else ""
    return f"git push {where}" + (f" ({said})" if said and said not in where else "")


def plan_done(checkout: Path, plan: str) -> bool:
    """Every row of the field's own plan.md is done (or dropped); False when the plan cannot be read (never "done")."""
    folder = lead_marker.planread.plan_dir(checkout, plan) if lead_marker.planread else checkout / "plans" / plan
    try:
        cells = lead_marker.statuses((Path(folder) / "plan.md").read_text())
    except OSError:
        return False
    return bool(cells) and all(c.lower().lstrip("*_ ").startswith(("done", "dropped")) for c in cells)


def facts(agent: dict, checkout: Path, src: dict, default: str = "origin/main") -> dict:
    state, plan = run_state(checkout), agent.get("current_plan") or ""
    done = plan_done(checkout, plan) if plan else False
    t = ticket(checkout, src.get("queue") or {})
    ahead = None
    if done or (state and state["state"] in ("done", "hitched")):
        ahead = lead_marker.read(checkout, "rev-list", "--count", f"{default}..HEAD")
    landed = bool(state and state["state"] == "landed") or (not t and ahead == "0" and bool(done))
    return {"run_state": state, "ticket": t, "push": push(agent, checkout, state, src.get("workqueue") or {}),
            "plan_done": done, "landed": landed}


def kind(agent: dict) -> tuple[str, str] | None:
    """The foreman class of an idle foreman's field from its `field` facts (see the module doc), else None."""
    f = agent.get("field")
    if not f or agent.get("lead") or agent.get("slot") in (None, "main"):
        return None
    state, t = f.get("run_state") or {}, f.get("ticket")
    word, why = state.get("state"), state.get("why") or ""
    if f.get("landed"):
        return "landed", "its plan is in the barn" + ("" if word == "landed" else " (nothing ahead of main)")
    if f.get("push"):
        return "pushing", f["push"]
    if t or word == "hitched":
        return "hitched", f"hitched, {(t or {}).get('state') or 'waiting'} in the merge queue" if t else "hitched"
    if word == "waiting":
        return "waiting", f"waits for {why}"
    if word == "blocked":
        return "blocked-plan", f"plan blocked: {why}"
    if f.get("plan_done") or word == "done":
        return "done-not-hitched", "every step done, no merge queue ticket"
    return None
