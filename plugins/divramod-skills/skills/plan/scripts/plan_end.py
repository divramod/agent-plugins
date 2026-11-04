"""plan_end.py: the plan's end as one call, `plan.py end [--dry-run] [--json]` (hal2 plan 0514 step 2, D3, D5, D6).

When every step before the landing is done (`land: ready`), the field's work goes to the barn without a prompt:

    1. refused: a step before the landing still open, a plan that does not land itself (`manual`, `none`), a detached
       HEAD or the default branch, uncommitted tracked changes (named; it commits nothing, untracked files are only
       named);
    2. run state `pushing`, its why from `hal2-cli-workqueue status --json` (this field's waiting or running job, a
       hold of another field, else "pre-push hook"), then `git push origin <branch>` (skipped when origin's ref is
       HEAD already); a failed push is state `blocked` with the hook's last line;
    3. mtm's `tollman.sh` prints `yes` and the queue mode is not smuggle: `hal2-cli-git worktree queue ready --json`
       (the hitch), state `hitched`; else state `done` and the answer names `/mtm` (it lands or smuggles itself).

Fields 09, 23 and 29 (2026-10-30) sat 10-50 min in the pre-push hook behind workqueue holds, shown as idle and done:
the push is now a state, and the end needs no hand-off before it (the guard passes plan.py and git). Every external
call goes through `Calls`, which a test replaces. JSON: {"schema": 1, "plan", "branch", "action", "state", "why",
"next", "pushed", "notes"}; `action` one of refused, dry-run, hitched, mtm, smuggle, blocked.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import runstate

SCHEMA = 1
HERE = Path(__file__).resolve().parent
Runner = Callable[..., subprocess.CompletedProcess]


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    except OSError as error:  # a missing program answers like a failed one
        return subprocess.CompletedProcess(command, 127, "", str(error))


def tollman_script() -> Path | None:
    """mtm's `scripts/tollman.sh` beside this skill (flat or in a category), None when it is not installed."""
    try:
        base = next(p / "scripts" for p in HERE.parents if (p / ".claude-plugin").is_dir())
        if str(base) not in sys.path:
            sys.path.insert(0, str(base))
        from skillpath import sibling
        found = sibling("merge-to-main", HERE / "plan.py") / "scripts" / "tollman.sh"
    except (StopIteration, ImportError, FileNotFoundError):
        found = HERE.parent.parent / "merge-to-main" / "scripts" / "tollman.sh"
    return found if found.is_file() else None


@dataclass
class Calls:
    """The external calls of the end; a test swaps `run` (or puts fake programs on PATH) and `tollman`."""
    run: Runner = _run
    tollman: Callable[[], Path | None] = lambda: tollman_script()  # looked up per call: a test patches it

    def git(self, root: Path, *args: str) -> subprocess.CompletedProcess:
        return self.run(["git", *args], root)

    def awake(self, root: Path) -> tuple[bool, str]:
        """mtm's answer: is there a working, awake tollman? Every doubt is no."""
        script = self.tollman()
        if script is None:
            return False, "the merge-to-main skill's tollman.sh is not installed"
        done = self.run(["bash", str(script), str(root)], root)
        words = done.stdout.split()
        reason = (done.stderr.strip().splitlines() or [""])[-1]
        return (words[:1] == ["yes"], reason or f"tollman.sh: {' '.join(words) or 'no answer'}")

    def mode(self, root: Path) -> str:
        """The queue mode of this field (`production`, `smuggle`), "" when it cannot be read."""
        done = self.run(["hal2-cli-git", "worktree", "queue", "mode", "--slot", root.name, "--json"], root)
        try:
            return str(json.loads(done.stdout).get("mode") or "") if done.returncode == 0 else ""
        except (ValueError, AttributeError):
            return ""

    def workqueue(self, root: Path) -> dict:
        done = self.run(["hal2-cli-workqueue", "status", "--json"], root)
        try:
            found = json.loads(done.stdout) if done.returncode == 0 else {}
        except ValueError:
            return {}
        return found if isinstance(found, dict) else {}

    def hitch(self, root: Path) -> subprocess.CompletedProcess:
        return self.run(["hal2-cli-git", "worktree", "queue", "ready", "--json"], root)


@dataclass
class Result:
    plan: str
    branch: str = ""
    action: str = "refused"
    state: str | None = None
    why: str = ""
    next: str = ""
    pushed: str = ""
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"schema": SCHEMA, "plan": self.plan, "branch": self.branch, "action": self.action,
                "state": self.state, "why": self.why, "next": self.next, "pushed": self.pushed, "notes": self.notes}

    def line(self) -> str:
        head = {"refused": "plan.py end refused", "dry-run": "plan.py end --dry-run",
                "blocked": "plan.py end: blocked"}.get(self.action, f"plan.py end: {self.action}")
        text = f"{head}: {self.why}" if self.why else head
        lines = [text, *(f"  {n}" for n in self.notes)]
        if self.next:
            lines.append(f"next: {self.next}")
        return "\n".join(lines)


def push_why(root: Path, queue: dict) -> str:
    """Why `pushing` may take long, from the workqueue now: this field's job, a hold of another field, else the hook."""
    me = f"{root.parent.name}/{root.name}"
    mine = lambda job: job.get("field") == me or str(job.get("cwd", "")).startswith(str(root))
    waiting = [j for j in queue.get("waiting") or [] if isinstance(j, dict) and mine(j)]
    if waiting:
        return f"pre-push hook waits in the workqueue (place {waiting[0].get('position') or '?'})"
    holds = [h for h in queue.get("holds") or [] if isinstance(h, dict) and h.get("field") != me]
    if holds:
        named = ", ".join(f"{h.get('field') or '?'} ({h.get('class') or 'hold'})" for h in holds[:3])
        return f"pre-push hook; workqueue holds by {named}"
    return "pre-push hook"


GIT_OWN = ("To ", "error: failed to push", "hint:", " ! ")


def hook_line(text: str) -> str:
    """The last line of a failed push that is not git's own (`error: failed to push some refs`): the hook's words."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return next((l for l in reversed(lines) if not l.startswith(GIT_OWN)), lines[-1] if lines else "")


def branch_of(root: Path, calls: Calls) -> tuple[str, str]:
    """(the checked-out branch, why it cannot land: "" when it can)."""
    done = calls.git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    branch = done.stdout.strip()
    if done.returncode != 0 or not branch:
        return "", "HEAD is detached: check out the field's branch"
    head = calls.git(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD").stdout.strip()
    default = head.split("/", 1)[1] if "/" in head else ""
    if branch in {default, "main", "master"} - {""}:
        return branch, f"{branch} is the default branch: nothing to land"
    return branch, ""


def dirty(root: Path, calls: Calls) -> tuple[list[str], list[str]]:
    """(tracked files with changes, untracked files), by `git status --porcelain`."""
    lines = calls.git(root, "status", "--porcelain").stdout.splitlines()
    return ([l[3:] for l in lines if l and not l.startswith("??")], [l[3:] for l in lines if l.startswith("??")])


def refusal(info: dict) -> str:
    land = info.get("land")
    if land == "wait":
        step = info.get("next") or {}
        number = info.get("ref") or step.get("number") or "?"
        return f"step {number} is still open before the landing: finish it first (plan.py current)"
    if land == "manual":
        return "the plan lands by the user's /mtm (landing: manual): plan.py end runs only for landing: auto"
    if land == "none":
        return "a global plan has nothing to land"
    if info.get("problems"):
        return f"the plan has problems: {info['problems'][0]}"
    return ""


def preflight(root: Path, info: dict, result: Result, calls: Calls) -> str:
    """Why the end refuses (a step open, the branch, tracked changes), else ""; names untracked files."""
    if why := refusal(info):
        return why
    result.branch, why = branch_of(root, calls)
    if why:
        return why
    tracked, untracked = dirty(root, calls)
    if tracked:
        return f"uncommitted changes: {', '.join(tracked[:10])}: commit them (the step's commit) first"
    if untracked:
        result.notes.append(f"left untracked: {', '.join(untracked[:10])}")
    return ""


def end(root: Path, info: dict, dry_run: bool = False, calls: Calls | None = None) -> Result:
    """The end of the plan `info` (describe()'s dict of the current plan) in the field `root`."""
    calls = calls or Calls()
    result = Result(plan=info.get("slug") or "")
    if why := preflight(root, info, result, calls):
        result.why = why
        return result
    head = calls.git(root, "rev-parse", "HEAD").stdout.strip()
    remote = calls.git(root, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{result.branch}").stdout.strip()
    needs_push = not head or head != remote
    if dry_run:
        return dry(root, result, needs_push, calls)
    if needs_push:
        why = push_why(root, calls.workqueue(root))
        runstate.write(root, result.plan, "pushing", why)
        done = calls.git(root, "push", "origin", result.branch)
        if done.returncode != 0:
            last = hook_line(done.stderr or done.stdout)
            return blocked(root, result, f"git push failed ({why}): {last or 'exit ' + str(done.returncode)}",
                           "fix what the pre-push hook names, commit, then plan.py end again")
    result.pushed = "pushed" if needs_push else "up-to-date"
    return hitch(root, result, calls)


def dry(root: Path, result: Result, needs_push: bool, calls: Calls) -> Result:
    """What `end` would do, changing nothing."""
    awake, reason = calls.awake(root)
    mode = calls.mode(root) if awake else ""
    result.action = "dry-run"
    result.why = (f"would push {result.branch}" if needs_push else f"{result.branch} is pushed") + (
        ", then hitch for the tollman" if awake and mode not in ("smuggle", "") else
        f", then name /mtm ({'queue mode ' + (mode or 'unknown') if awake else reason})")
    return result


def hitch(root: Path, result: Result, calls: Calls) -> Result:
    """After the push: hitch for an awake tollman (state `hitched`), else name /mtm (state `done`)."""
    awake, reason = calls.awake(root)  # asked after the push: the hook may have taken an hour
    mode = calls.mode(root) if awake else ""
    if awake and mode == "smuggle":
        return mtm(root, result, "smuggle", "the queue is in smuggle mode: /mtm smuggles it")
    if not awake or not mode:
        return mtm(root, result, "mtm", reason if not awake else "the queue mode cannot be read")
    done = calls.hitch(root)
    if done.returncode != 0:
        last = next((l.strip() for l in reversed(done.stderr.splitlines()) if l.strip()), "")
        return blocked(root, result, f"the hitch was refused: {last or 'exit ' + str(done.returncode)}",
                       "fix what it names, then plan.py end again")
    runstate.write(root, result.plan, "hitched")
    result.action, result.state = "hitched", "hitched"
    result.why = f"field {root.name} rides the next train"
    result.next = "wait for the tollman's \"in the barn\", then mtm's after-barn path"
    return result


def blocked(root: Path, result: Result, why: str, then: str) -> Result:
    runstate.write(root, result.plan, "blocked", why)
    result.action, result.state, result.why, result.next = "blocked", "blocked", why, then
    return result


def mtm(root: Path, result: Result, action: str, why: str) -> Result:
    runstate.write(root, result.plan, "done", f"/mtm lands it: {why}")
    result.action, result.state, result.why, result.next = action, "done", why, "/mtm"
    return result


def show(result: Result, as_json: bool) -> int:
    print(json.dumps(result.as_dict(), ensure_ascii=False) if as_json else result.line())
    return 0 if result.action in ("dry-run", "hitched", "mtm", "smuggle") else 1
