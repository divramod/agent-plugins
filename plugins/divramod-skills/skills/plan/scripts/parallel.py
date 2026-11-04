"""Parallel plans (skills plan 0013; hal2 02's one-plan-answer.md, section D): a step table with the columns
`| # | Step | Needs | Touches | Who | Done when | Status |` runs its steps in parallel.

- Needs: comma-separated step ids and ranges (`3-7`); blank or `-` is none. Ids are integers, never renumbered.
- Touches: comma-separated resources (`rust:<crate>`, `ts:<package>`, `proto:<package>`, `docs`, `@hub-stack`, ...);
  two steps sharing one never run at once. Each resource has room for one step, `@vm` for two; a `Capacity:` line
  under the title (`Capacity: @vm=2, @x=3`; a plan in the record format: above its step table) overrides. A row whose Step starts with `Milestone <n>` touches `@land`.
  Resources compare without backticks, whitespace and case.
- Who: `lead`, `subagent` or `user`; every step runs in a subagent (plan 0016: `plan.py prompt <n>`). A `slot NN`
  an older row names (a servant session, gone) is still read but never assigned.
- Status: `done...`, `running`, `blocked <why>`, anything else (blank, `next`) is open. A running step, and a blocked
  one with a Who, holds its Touches.

A servant's field holds the gitignored marker `plans/LEAD` (`<foreman's field> <plan-slug> <steps>`; of a masterplan's
servant the masterplan's slug and its row): plan.py and mtm refuse to write the plan or land there (plan 0015 D12;
hal2 plan 0275 D26): the foreman marks the steps and brings the work in. The marker's existence marks the field; its
parts come from `hal2-cli-plans servant show --json` (`read_marker`, hal2 plan 0594), never from a split of the line.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import planread
import milestone
import pointers

try:  # the skills unit's scripts/: the one reader of plans/LEAD (plan 0594); the plan skill copied out of the unit has none
    sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
    import servant_state
except (StopIteration, ImportError):
    servant_state = None

LEAD = Path("plans") / "LEAD"  # the words of the messages; the file is the git dir's or plans/ (pointers.py)
DEFAULT_CAPACITY = {"@vm": 2}
MILESTONE = milestone.ROW  # the row form is milestone.py's (one definition with hal2-plans)
WHO = re.compile(r"^(lead|subagent|user)$")
SLOT = re.compile(r"^slot\s*\d+$")
SUBPLAN_REF = re.compile(r"(\d\d)\.\d+")  # a schema 2 step ref `02.01`: the servant object's step of a sub-plan servant
SUBPLAN_DIR = re.compile(r"\d\d-[a-z0-9][a-z0-9-]*")  # a sub-plan `02-readers`


class ParallelError(Exception):
    pass


def is_parallel(cols: dict[str, int]) -> bool:
    return "needs" in cols


def parse_needs(text: str) -> tuple[list[str], list[str]]:
    """(step ids, tokens that are no id or range)."""
    ids, bad = [], []
    for token in (t.strip() for t in text.split(",")):
        if token in ("", "-", "—"):
            continue
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", token)
        if m and int(m.group(1)) <= int(m.group(2)):
            ids += [str(n) for n in range(int(m.group(1)), int(m.group(2)) + 1)]
        elif token.isdigit():
            ids.append(str(int(token)))
        else:
            bad.append(token)
    return ids, bad


def resource(token: str) -> str:
    """One Touches resource as compared: no backticks, no whitespace, case-folded (`` `@VM ` `` is `@vm`)."""
    return "".join(token.replace("`", "").split()).casefold()


def parse_touches(text: str, step: str = "") -> list[str]:
    touches = []
    for t in map(resource, text.split(",")):
        if t not in ("", "-", "—") and t not in touches:
            touches.append(t)
    if MILESTONE.match(step) and "@land" not in touches:
        touches.append("@land")
    return touches


def kind(status: str) -> str:
    s = status.lower().lstrip("*_ ")
    for k in ("done", "running", "blocked"):
        if s.startswith(k):
            return k
    return "open"


def capacity(text: str) -> dict[str, int]:
    """Room per resource: 1, `@vm` 2, and what a `Capacity: @x=3, ...` line says: above the first section, or (a
    plan in the record format, whose front matter has no such key) in `## Steps` above the step table."""
    room = dict(DEFAULT_CAPACITY)
    record = text.startswith("---\n")
    for line in text.splitlines():
        if line.lstrip().startswith("|") if record else line.startswith("## "):
            break
        if line.startswith("Capacity:"):
            for part in line.split(":", 1)[1].split(","):
                name, _, n = part.partition("=")
                n = n.replace("`", "").strip()
                if resource(name) and n.isdigit():
                    room[resource(name)] = int(n)
    return room


def enrich(step: dict, cells: list[str], cols: dict[str, int]) -> None:
    """Add a parallel row's needs, touches and who to its step dict."""
    cell = lambda name: cells[cols[name]] if name in cols else ""  # noqa: E731
    step["needs"], step["bad_needs"] = parse_needs(cell("needs"))
    step["touches"] = parse_touches(cell("touches"), step["step"])
    step["who"] = cell("who")


def problems(steps: list[dict]) -> list[str]:
    """Ids that are no integer or used twice, Needs no row has, and cycles."""
    out, ids, seen = [], [s["number"] for s in steps], set()
    for s in steps:
        if not s["number"].isdigit():
            out.append(f"step id '{s['number']}' is no integer: a parallel plan's ids are integers, never renumbered")
        elif s["number"] in seen:
            out.append(f"step id '{s['number']}' is used twice")
        seen.add(s["number"])
        if s["bad_needs"]:
            out.append(f"step {s['number']}: Needs '{', '.join(s['bad_needs'])}' are no step ids or ranges")
        missing = [n for n in s["needs"] if n not in ids]
        if missing:
            out.append(f"step {s['number']} needs step(s) {', '.join(missing)}, which no row has")
    needs = {s["number"]: [n for n in s["needs"] if n in ids] for s in steps}
    state: dict[str, int] = {}

    def visit(n: str, path: list[str]) -> list[str] | None:
        state[n] = 1
        for m in needs.get(n, []):
            if state.get(m) == 1:
                return path + [n, m]
            if not state.get(m) and (cycle := visit(m, path + [n])):
                return cycle
        state[n] = 2
        return None

    for s in steps:
        if not state.get(s["number"]) and (cycle := visit(s["number"], [])):
            start = cycle.index(cycle[-1])
            out.append(f"the Needs form a cycle: {' -> '.join(cycle[start:])}")
            break
    return out


def holds(step: dict) -> bool:
    """A step that holds its Touches and its Who: running, or blocked after it was assigned."""
    k = kind(step["status"])
    return k == "running" or (k == "blocked" and bool(step.get("who", "").strip()))


def schedule(steps: list[dict], room: dict[str, int], limit: int | None = None) -> tuple[list[dict], list[dict]]:
    """(ready, waiting): ready steps picked greedily in table order, each open one left over with why it waits."""
    done = {s["number"] for s in steps if kind(s["status"]) == "done"}
    open_milestones = {s["milestone"] for s in steps if s.get("milestone") and kind(s["status"]) != "done"}
    used: dict[str, int] = {}
    for s in steps:
        if holds(s):
            for t in s["touches"]:
                used[t] = used.get(t, 0) + 1
    ready, waiting = [], []
    for s in steps:
        if kind(s["status"]) != "open":
            continue
        open_needs = [n for n in s["needs"] if n not in done]
        busy = [t for t in s["touches"] if used.get(t, 0) >= room.get(t, 1)]
        if s["after_landing"]:
            why = "checked after the landing"
        elif s.get("after_milestone") in open_milestones:
            why = f"waits for Milestone {s['after_milestone']} in the barn"
        elif open_needs:
            why = f"needs step(s) {', '.join(open_needs)}"
        elif busy:
            why = f"touches {', '.join(busy)}, in use"
        elif limit is not None and len(ready) >= limit:
            why = f"the limit of {limit} is reached"
        else:
            ready.append(s)
            for t in s["touches"]:
                used[t] = used.get(t, 0) + 1
            continue
        waiting.append({"number": s["number"], "step": s["step"], "why": why})
    return ready, waiting


def check_who(who: str) -> str:
    """`lead`, subagent or user. `slot NN` (a servant session, gone with plan 0016) is refused; a row that already
    names one is still read (enrich, holds)."""
    who = " ".join(who.split()).lower()
    if SLOT.match(who):
        raise ParallelError(f"{who}: steps no longer go to servant sessions in worktrees; run the step as a "
                            "subagent: `plan.py assign <step> subagent`, then `plan.py prompt <step>` prints its Agent "
                            "call")
    if not WHO.match(who):
        raise ParallelError(f"who '{who}' is none of lead, subagent, user")
    return who


def read_marker(root: Path) -> dict | None:
    """The servant marker LEAD (the git dir's, else plans/LEAD) as {slot, plan, step, steps, finished}: `slot` the
    foreman's field, `step` the steps joined by commas (a sub-plan servant's: its sub-plan `02-readers`), `steps` the
    CLI's list; None when there is none. The field stays a servant's when `hal2-cli-plans servant show` is missing or
    gives none (D6, no fallback parse): {slot: "", plan: "", step: "", steps: [], unread: True}, so the write refusal
    never depends on the CLI."""
    if not pointers.exists(root, pointers.LEAD):
        return None
    found = servant_state.of(root) if servant_state else None
    if found is None:
        return {"slot": "", "plan": "", "step": "", "steps": [], "unread": True}
    names = servant_state.step_names(found)
    return {"slot": str(found["foreman"]), "plan": str(found["plan"]),
            "step": subplan_of_steps(root, str(found["plan"]), names) or ",".join(names),
            "steps": found["steps"], "finished": bool(found.get("finished"))}


def subplan_of_steps(root: Path, plan: str, names: list[str]) -> str | None:
    """`02-readers` when the servant's steps are one sub-plan of a schema 2 plan: the object names them `02.01`, `02.02`
    (all of sub-plan 02; the folder is found in the plan's `subplans/`) or, when the plan is not found, the sub-plan
    itself (`02-readers`). None for the legacy form (step numbers, masterplan rows)."""
    if len(names) == 1 and SUBPLAN_DIR.fullmatch(names[0]):
        return names[0]
    prefixes = {m.group(1) for n in names if (m := SUBPLAN_REF.fullmatch(n))}
    if not names or len(prefixes) != 1 or not all(SUBPLAN_REF.fullmatch(n) for n in names):
        return None
    number = next(iter(prefixes))
    for folder in (planread.plan_dir(root, plan), *sorted(Path(root).glob(f"plans/{plan}-*"))):
        for sub in sorted((folder / "subplans").glob(f"{number}-*")):
            if SUBPLAN_DIR.fullmatch(sub.name):
                return sub.name
    return None


def worktree_of(path: Path) -> Path | None:
    """The checkout `path` lies in (`git rev-parse --show-toplevel`), None outside git."""
    out = git(path, "rev-parse", "--show-toplevel")
    return Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None


def subservant_marker(root: Path, cwd: Path) -> dict | None:
    """The marker of the `--root` checkout, else of the cwd's: a servant passing --root <foreman> is one too.

    The cwd's checkout is the cwd or a folder above it, so where none of them holds a marker git is not asked (one
    process less per call); only $GIT_WORK_TREE or $GIT_DIR can put the checkout elsewhere."""
    if marker := read_marker(root):
        return marker
    here = cwd.resolve()
    if not any(pointers.exists(d, pointers.LEAD) for d in (here, *here.parents)) and \
            not (os.environ.get("GIT_WORK_TREE") or os.environ.get("GIT_DIR")):
        return None
    top = worktree_of(cwd)
    return read_marker(top) if top and top.resolve() != root.resolve() else None


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
