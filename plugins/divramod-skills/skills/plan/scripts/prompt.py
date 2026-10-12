"""The step prompt: `plan.py prompt <n>` prints the Agent call that runs one step in one subagent (plan 0016 step 3;
plan 0015 D12, plan 0016 D6, D9). The coordinator passes it to the Agent tool as it is.

The call: `description` "Plan <NNNN> row <n>: <short title>" (`... row <n> part <k>: ...` for a retry), `model` (the
row's, as the Agent tool's alias), `effort` (the row's), `run_in_background: true` and `prompt`, the text below.
"""
import re
import subprocess
from pathlib import Path

import session
import sizing

TITLE_WORDS = 6
TASK = re.compile(r"^## Task[ \t]*\n(.*?)(?=^## |\Z)", re.M | re.S)
PLACEHOLDER = re.compile(r"^<what to change\b.*>$", re.S)
DONE_WHEN = re.compile(r"^(Done when|Size):.*$", re.M)


class PromptError(Exception):
    pass


def short_title(step: str) -> str:
    """The Step cell's first clause (up to `: `, `;`, `,`, ` (` or a dash), backticks dropped, at most a few words; a
    one-word clause (`grill: the autogrill sets ...`) keeps the clause after it."""
    text = " ".join(step.replace("`", "").split())
    parts = re.split(r"(:\s|;\s*|,\s*|\s\(|\s[—–-]\s)", text, maxsplit=2)
    title = parts[0]
    if len(title.split()) == 1 and len(parts) >= 3 and parts[2].strip():
        title += parts[1].rstrip() + " " + re.split(r":\s|;|,|\s\(|\s[—–-]\s", parts[2])[0]
    words = title.split()[:TITLE_WORDS]
    return " ".join(words).rstrip(".:;,") or step.strip()


def alias(model: str) -> str:
    """A step's model as the Agent tool takes it: `haiku`, `sonnet`, `opus` or `fable` (`opus[1m]` and
    `claude-opus-5-5` are `opus`)."""
    name = session.family(model)
    if name not in sizing.MODELS:
        raise PromptError(f"model '{model}' is none of {', '.join(sizing.MODELS)} (the Agent tool's aliases): set the "
                          "row's Model or pass --model")
    return name


def task_written(step_file: Path) -> bool:
    """The step file has a `## Task` with text of its own (not the template's `<what to change ...>`; its `Size:` and
    `Done when:` lines do not count)."""
    if not step_file.is_file():
        return False
    found = TASK.search(step_file.read_text())
    if not found:
        return False
    body = DONE_WHEN.sub("", found.group(1)).strip()
    return bool(body) and not PLACEHOLDER.match(body)


def repo_name(root: Path) -> str:
    """The repository's name: its main checkout's folder (a slot `<repo>/30` is `<repo>`), else the root's."""
    out = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=root,
                         capture_output=True, text=True)
    common = Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None
    return common.parent.name if common and common.name == ".git" else root.name


def text(root: Path, plan: Path, row: dict, others: list[dict], part: int | None) -> str:
    """The subagent's prompt (D9): where it works, what it reads first, the rules, the final reply."""
    n, number = row["number"], plan.parent.name[:4]
    rel = lambda p: str(p.relative_to(root))  # noqa: E731
    step_file = plan.parent / "steps" / f"{n}.md"
    reads = [f"the plan {rel(plan)} (its row {n} and its Context)", f"your task {rel(step_file)}"]
    if (plan.parent / "decisions.md").is_file():
        reads.append(f"the plan's decisions {rel(plan.parent / 'decisions.md')} (decided: never re-decide them)")
    rules = next((name for name in ("AGENTS.md", "CLAUDE.md") if (root / name).is_file()), "")
    later = "; ".join(f"{s['number']} {short_title(s['step'])}" for s in others) or "none"
    retry = (f" This is part {part} of the step: an earlier subagent's work is in the worktree and in the step "
             "file's Approach and Notes; continue from it.") if part else ""
    done_when = row["done_when"] or "the step file's done-when"
    return "\n\n".join([
        f"You are the subagent for step {n} of plan {number} in the {repo_name(root)} repository. Work only in the "
        f"git worktree {root}.{retry}",
        "Read first: " + "; ".join(reads) + (f". The repo's rules: {rules}." if rules else "."),
        "Rules: edit files, but never commit, push, land or change git state, and never edit plan.md (the "
        "coordinator reviews and commits). First write your step file's `## Approach`; at the end its `## Notes` "
        "(what changed, the checks and results, what you decided). Stay inside your step (the other open steps: "
        f"{later}). Run the step's done-when ({done_when}) and the tests of what you changed until green. Never "
        "print the whole environment (`env`, `printenv`, `set`, `export -p`): it holds secrets; read one variable "
        "by name when you need it.",
        "Final reply, at most 15 lines: the files changed, the done-when's result, follow-ups for later steps.",
    ])


def call(root: Path, plan: Path, row: dict, others: list[dict], columns: dict | None, part: int | None = None,
         model: str = "", effort: str = "") -> dict:
    """The Agent call for step `row` of `plan` (`columns`: a record plan's step table columns, None for a legacy
    plan); `model`/`effort` override the row's (an escalation). Refused when the step file has no written `## Task`
    or a record plan's row fails `plan-steps-sized`."""
    n = row["number"]
    step_file = plan.parent / "steps" / f"{n}.md"
    if not task_written(step_file):
        raise PromptError(f"{step_file.relative_to(root)} has no written `## Task`: write the step's task first "
                          f"(`plan.py status {n} next` scaffolds the file)")
    if columns is not None:
        missing = [sizing.TITLES[k] for k in sizing.SIZED if k not in columns]
        if missing:
            raise PromptError(f"the step table has no column {', '.join(missing)}: run `plan.py migrate` "
                              f"({sizing.RULE})")
        why = [w for k in sizing.SIZED if (w := sizing.cell_problem(k, row[k], row["window"]))]
        if why:
            raise PromptError(f"step {n}: {'; '.join(why)}: fix the row (plan.py check names it) ({sizing.RULE})")
    if effort and effort not in sizing.EFFORTS:
        raise PromptError(f"--effort '{effort}' is none of {', '.join(sizing.EFFORTS)}")
    out = {"description": f"Plan {plan.parent.name[:4]} row {n}{f' part {part}' if part else ''}: "
                          f"{short_title(row['step'])}"}
    if model or row["model"]:
        out["model"] = alias(model or row["model"])
    effort = effort or sizing.clean(row["effort"])
    if effort:
        if effort not in sizing.EFFORTS:
            raise PromptError(f"effort '{effort}' is none of {', '.join(sizing.EFFORTS)}: fix `Run:` or pass --effort")
        out["effort"] = effort
    out["run_in_background"] = True
    out["prompt"] = text(root, plan, row, others, part)
    return out
