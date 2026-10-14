"""What `state.py` reads from the outside world (hal2 plan 0268, D6): each source degrades to None when its tool is
missing, fails or is slow (TIMEOUT seconds), never an error. Everything here only reads: no fetch, no write into a
checkout or the farmer's state folder.
"""

import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import farmer_link as fl

TIMEOUT = 10
OPEN_STATUSES = {"queued", "in_progress", "waiting", "pending", "requested"}
RUN_FIELDS = "databaseId,workflowName,status,conclusion,headBranch,headSha,createdAt,url,event"
UNACKED_FRESH = dt.timedelta(hours=12)  # an instruction nobody acked for longer is stale, not a wait
PLAN_NAME = re.compile(r"^(\d{4})-(.+)$")
OPEN_QUESTION = re.compile(r"^## (Q\d+)\b.*·\s*open\s*$", re.M)


def tool(args: list[str], cwd: str | Path | None = None, timeout: float | None = None) -> str | None:
    """stdout of the command, None when it is missing, exits non-zero or takes longer than the timeout."""
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout or TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def tool_json(args: list[str], cwd: str | Path | None = None):
    out = tool(args, cwd)
    try:
        return json.loads(out) if out and out.strip() else None
    except ValueError:
        return None


def git(path: str | Path, *args: str) -> str | None:
    """A read of the checkout: without optional locks, so `status` never refreshes the index of a busy worktree."""
    out = tool(["git", "--no-optional-locks", *args], path)
    return out.strip() if out is not None else None


def agents() -> dict[str, dict] | None:
    """The agent sessions by their real checkout path; None when `hal2-cli-agents` gives nothing."""
    raw = tool_json(["hal2-cli-agents", "list", "--json"])
    if isinstance(raw, dict):
        raw = raw.get("list")
    if not isinstance(raw, list):
        return None
    return {os.path.realpath(path): a for path, a in fl.agents_by_checkout(raw).items()}


def queue(main: str) -> list[dict] | None:
    """The merge queue: `slot` (the worktree's name), `worktree`, position, holding, state per ticket; None when unknown."""
    raw = tool_json(["hal2-cli-git", "worktree", "queue", "--json"], main)
    if not isinstance(raw, dict) or not isinstance(raw.get("queue"), list):
        return None
    return [{"slot": t.get("slot"), "worktree": os.path.realpath(t["worktree"]) if t.get("worktree") else None,
             "position": t.get("position"), "holding": bool(t.get("holding")), "state": t.get("state")}
            for t in raw["queue"]]


def open_runs(main: str) -> list[dict] | None:
    """The repository's open GitHub Actions runs from ONE `gh run list`; None when gh gives nothing."""
    raw = tool_json(["gh", "run", "list", "--limit", "100", "--json", RUN_FIELDS], main)
    if not isinstance(raw, list):
        return None
    return [{"workflow": r.get("workflowName"), "status": r.get("status"), "branch": r.get("headBranch"),
             "sha": (r.get("headSha") or "")[:8], "url": r.get("url")}
            for r in raw if r.get("status") in OPEN_STATUSES]


def farmer_log(main: str) -> list[dict] | None:
    """The farmer's log.jsonl, read only. `roles.state_dir` would create the folder, so the path is computed here;
    None when the repository has no farmer state folder."""
    if fl.roles is None or fl.mtm_scan is None:
        return None
    d = (fl.roles.OVERRIDE / Path(main).name) if fl.roles.OVERRIDE else fl.roles.slot_dir(main) / "roles" / fl.roles.ROLE
    return fl.mtm_scan.entries(d / "log.jsonl") if (d / "log.jsonl").is_file() else None


def asks(log: list[dict] | None) -> set[str]:
    """Worktrees whose last `ask` has no answer."""
    return fl.logstate.waiting_for_user(log) if log and fl.logstate else set()


def unacked(log: list[dict] | None, now: dt.datetime | None = None) -> dict[str, list[str]]:
    """Ids of the farmer's instructions nobody acked yet, per worktree (the last 12 hours)."""
    now, out = now or dt.datetime.now(dt.timezone.utc), {}
    if fl.acks is None:
        return out
    try:
        found = fl.acks.instructions(log or [])
    except (KeyError, ValueError, TypeError):
        return out
    for i in found.values():
        at = i.get("at")
        if at is None or i["acks"] or not i.get("slot"):
            continue
        if now - (at if at.tzinfo else at.replace(tzinfo=dt.timezone.utc)) < UNACKED_FRESH:
            out.setdefault(i["slot"], []).append(i["id"])
    return out


def open_questions(root: str | Path, plan_slug: str | None) -> list[str]:
    """The ids (`Q31`) of the plan's open questions in its `questions.md` (`## Q<n> · date · who · open`)."""
    f = Path(root) / "plans" / plan_slug / "questions.md" if plan_slug else None
    try:
        return OPEN_QUESTION.findall(f.read_text()) if f and f.is_file() else []
    except OSError:
        return []


def plan_of(root: str | Path, current: str) -> dict:
    """A CURRENT_PLAN text as `plan_number`, `plan_name` and the steps `steps_done`/`steps_total` of the plan skill's
    parser (`plan.describe_safe`, D5); a plan is `<NNNN>-<slug>` with a plans/<it>/plan.md, else all None."""
    out = {"plan_number": None, "plan_name": None, "steps_done": None, "steps_total": None, "plan_slug": None}
    current = current.strip().removesuffix("/plan.md").rstrip("/").removeprefix("plans/")  # a path names its plan too
    m = PLAN_NAME.match(current)
    plan_md = Path(root) / "plans" / current / "plan.md"
    if not m or not plan_md.is_file():
        return out
    out.update(plan_number=m.group(1), plan_name=m.group(2), plan_slug=current)
    done = steps(root, plan_md)
    out.update(steps_done=done[0], steps_total=done[1])
    return out


def steps(root: str | Path, plan_md: Path) -> tuple[int | None, int | None]:
    """(done, total) steps of a plan.md from the sibling plan skill; (None, None) when it is missing or fails."""
    scripts = Path(__file__).resolve().parents[2] / "plan" / "scripts"
    if not (scripts / "plan.py").is_file():
        return None, None
    if str(scripts) not in sys.path:
        sys.path.append(str(scripts))  # appended: the farmer's own modules keep their names
    try:
        import plan
        d = plan.describe_safe(Path(root), plan_md)
    except Exception:  # noqa: BLE001  (the plan skill's parser failing never fails the report)
        return None, None
    if "total" not in d:
        return None, None
    return d["done"], d["total"]
