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

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import sibling  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)

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
        raw = raw.get("agents")
    if not isinstance(raw, list):
        return None
    return {os.path.realpath(path): a for path, a in fl.agents_by_checkout(raw).items()}


def ticket_wt(t: dict) -> str | None:
    """The ticket's worktree name: its `slot` field, else the last part of its worktree path."""
    return t.get("slot") or (Path(t["worktree"]).name if t.get("worktree") else None)


def queue_state(main: str) -> dict:
    """ONE `worktree queue --json`: `queue` (see `queue`) and `mode` (`{mode, by, at, since, why}`, plan 0360 D75;
    `since` is `at` under the name plan 0369 D8 shows), None when unknown."""
    raw = tool_json(["hal2-cli-git", "worktree", "queue", "--json"], main)
    if not isinstance(raw, dict) or not isinstance(raw.get("queue"), list):
        return {"queue": None, "mode": None}
    tickets = [{"slot": t.get("slot"), "wt": ticket_wt(t), "worktree": os.path.realpath(t["worktree"]) if t.get("worktree") else None,
                "position": t.get("position"), "holding": bool(t.get("holding")), "state": t.get("state"),
                "land_ref": t.get("land_ref")}  # a train's branch `land/train-...` (plan 0383), else None
               for t in raw["queue"] if isinstance(t, dict)]
    tickets.sort(key=lambda t: (not t["holding"], t["position"] if isinstance(t["position"], int) else 10**9))  # the holder, then by place
    mode = raw.get("mode")
    return {"queue": tickets, "mode": {**mode, "since": mode.get("at")} if isinstance(mode, dict) else None}


def queue(main: str) -> list[dict] | None:
    """The merge queue: `slot` (the worktree's name), `worktree`, position, holding, state per ticket; None when unknown."""
    return queue_state(main)["queue"]


def workqueue_jobs() -> list[dict] | None:
    """The jobs running now from `hal2-cli-workqueue status --json` (plan 0382 step 5): `field`, `class`, `head`, `since`
    (RFC 3339), `source`, `flags` each; None when the CLI is missing, fails or gives no `live` list (shown as nothing)."""
    raw = tool_json(["hal2-cli-workqueue", "status", "--json"])
    if not isinstance(raw, dict) or not isinstance(raw.get("live"), list):
        return None
    return [{k: j.get(k) for k in ("field", "class", "head", "since", "source", "flags")}
            for j in raw["live"] if isinstance(j, dict)]


def git_numbers(path: str) -> dict | None:
    """The statusline's per-worktree numbers (`git-fields.js`'s mapping of `hal2-cli-git status --json --repo <path>`,
    plan 0369 D7): behind/ahead of the default branch, stash, untracked and added (always 0: the statusline does not
    scan them), modified (plus staged), deleted. None when the tool is missing, fails or gives no object."""
    raw = tool_json(["hal2-cli-git", "status", "--json", "--repo", str(path)])
    if not isinstance(raw, dict):
        return None
    num = lambda k: raw[k] if isinstance(raw.get(k), int) and not isinstance(raw.get(k), bool) else 0  # noqa: E731
    return {"behind": num("base_behind"), "ahead": num("base_ahead"), "stash": num("stash"), "untracked": 0, "added": 0,
            "modified": num("modified") + num("staged"), "deleted": num("deleted")}


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
    out = {"plan_number": None, "plan_name": None, "steps_done": None, "steps_total": None, "plan_slug": None,
           "description": None}
    current = current.strip().removesuffix("/plan.md").rstrip("/").removeprefix("plans/")  # a path names its plan too
    m = PLAN_NAME.match(current)
    plan_md = Path(root) / "plans" / current / "plan.md"
    if not m or not plan_md.is_file():
        return out
    out.update(plan_number=m.group(1), plan_name=m.group(2), plan_slug=current)
    done = steps(root, plan_md)
    out.update(steps_done=done[0], steps_total=done[1], description=description(plan_md))
    return out


def description(plan_md: Path) -> str | None:
    """The plan.md front matter's `description:` (a plain, quoted or `>`/`|` block value, whitespace folded), None
    when it has none (plan 0366 D1: the farmer view's "what it brings in", plan fields only)."""
    try:
        lines = plan_md.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    if not lines or lines[0].strip() != "---":
        return None
    block, found = [], False
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if found and line[:1] in " \t":
            block.append(line.strip())
        elif found:
            break
        elif line.startswith("description:"):
            found, value = True, line[len("description:"):].strip()
            block = [] if value in (">", "|", ">-", "|-") else [value]
    text = " ".join(block).strip()
    if len(text) > 1 and text[0] == text[-1] and text[0] in "\"'":
        quote, text = text[0], text[1:-1]
        text = text.replace('\\"', '"') if quote == '"' else text.replace("''", "'")
    return " ".join(text.split()) or None


def steps(root: str | Path, plan_md: Path) -> tuple[int | None, int | None]:
    """(done, total) steps of a plan.md from the sibling plan skill; (None, None) when it is missing or fails."""
    try:
        scripts = sibling("plan", __file__) / "scripts"
    except FileNotFoundError:
        return None, None
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
