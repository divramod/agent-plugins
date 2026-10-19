"""Reflection and edit proposals, the loop's two model steps, and the rejected-edit buffer (plan 0390 step 3). Stdlib.

Research 0100 (SkillOpt's reflect and update, P3-P5): the reflection reads the incumbent SKILL.md and the failed TRAIN
rollouts (each eval's prompt, the run's final text, its tool calls, its failed checks) and names what in the skill
made them fail; the edit prompt turns that reflection, plus the edit sets the gate already rejected (with their score
margin), into one bounded edit set (edits.py's schema and limits). Validation tasks never reach a prompt:
`reflection_prompt` raises on any failure whose eval is not `split: train`. Each step is one tool-less call (llm.py),
checked against and charged to the run's ledger.

A failure is `{"eval": <eval case>, "result": <rollout result>, "judged": <judge.judge_eval(...)>}`; only failed ones
are shown (a judged score below 1, or a rollout error), at most `max_failures`.

`RejectedBuffer(path)` is `rejected.jsonl` in the run folder: one line per edit set that failed the gate,
{at, edits, margin, ...the caller's fields (epoch, candidate, scores)}; `recent(n)` feeds the edit prompt.
"""

import datetime as dt
import json
import re
from pathlib import Path

import edits as edits_mod
import llm

MAX_FAILURES = 8
FINAL_LIMIT = 1500
INPUT_LIMIT = 300
MAX_CALLS = 12
RECENT_REJECTED = 5
FENCE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.S)
SCHEMA = ('[{"op": "add" | "delete" | "replace", "anchor": "<exact text, occurring once in SKILL.md>", '
          '"text": "<new text; ignored for delete>"}]')

REFLECT_HEAD = """You improve an agent skill: the SKILL.md below tells a coding agent how to do one kind of task.
The agent ran training tasks with this skill and failed the checks listed under each task.
Diagnose why: for each failure name the part of the SKILL.md (quote it) that misled the agent, or the instruction
it lacks, and say what change of the skill would fix it. Prefer general rules over answers to these tasks; never
write a task's expected output into the skill. Group failures with one cause. Answer in plain text, at most 400
words; do not write the edits yet."""

EDIT_HEAD = """You edit an agent skill. Turn the reflection below into one edit set for the SKILL.md.
Limits: at most {max_edits} edits; each anchor is exact text of the current SKILL.md and occurs there exactly once;
`add` inserts its text after the anchor, `delete` removes the anchor, `replace` puts its text in place of it; never
change the front matter's `name:` line; the edited SKILL.md has at most {cap} characters (now {size}).
Fix the causes the reflection names with the fewest, most general edits; never hard-code a task's answer."""

TAIL = "Reply only with the edit set as a JSON list in one ```json block, no other text."


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _cut(text, limit):
    text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + " [cut]"


def is_failed(failure):
    judged = failure.get("judged") or {}
    return bool((failure.get("result") or {}).get("error") or judged.get("error")) or float(
        judged.get("score") or 0) < 1


def _check_text(check):
    shown = {key: value for key, value in check.items() if key not in ("passed",)}
    return json.dumps(shown, ensure_ascii=False)


def failure_block(number, failure):
    """One failed train rollout as prompt text."""
    case, result, judged = failure.get("eval") or {}, failure.get("result") or {}, failure.get("judged") or {}
    calls = result.get("tool_calls") or []
    lines = [f"### Task {number} ({case.get('id')})", "Prompt:", _cut(str(case.get("prompt") or ""), FINAL_LIMIT),
             "Tool calls:"]
    lines += [f"- {call.get('name')} {_cut(call.get('input'), INPUT_LIMIT)}" for call in calls[:MAX_CALLS]] or ["- none"]
    if len(calls) > MAX_CALLS:
        lines.append(f"- ... {len(calls) - MAX_CALLS} more")
    lines += ["Final answer:", _cut(str(result.get("final_text") or ""), FINAL_LIMIT) or "(empty)"]
    error = result.get("error") or judged.get("error")
    if error:
        lines.append(f"Run error: {_cut(str(error), INPUT_LIMIT)}")
    failed = [check for check in judged.get("checks") or [] if not check.get("passed")]
    lines += ["Failed checks:"] + ([f"- {_check_text(check)}" for check in failed] or ["- (the run failed)"])
    return "\n".join(lines)


def reflection_prompt(skill_md, failures, max_failures=MAX_FAILURES):
    """The reflection prompt from failed TRAIN rollouts; ValueError on a non-train eval or no failure."""
    for failure in failures:
        split = (failure.get("eval") or {}).get("split")
        if split != "train":
            raise ValueError(f"reflection sees only train rollouts, got split {split!r}")
    shown = [failure for failure in failures if is_failed(failure)][:max_failures]
    if not shown:
        raise ValueError("no failed train rollout to reflect on")
    blocks = [failure_block(n, failure) for n, failure in enumerate(shown, 1)]
    return "\n\n".join([REFLECT_HEAD, "## SKILL.md", skill_md, "## Failed train rollouts"] + blocks)


def _sets(title, entries):
    if not entries:
        return []
    lines = [title]
    for entry in entries:
        margin = entry.get("margin")
        note = f" (validation margin {margin:+.3f})" if isinstance(margin, (int, float)) else ""
        lines.append(f"-{note} {json.dumps(entry.get('edits'), ensure_ascii=False)}")
    return ["\n".join(lines)]


def edit_prompt(skill_md, reflection, rejected=(), proposed=(), max_edits=edits_mod.MAX_EDITS,
                max_growth=edits_mod.MAX_GROWTH):
    """The edit prompt: reflection, rejected sets with their margins, sets already proposed, schema, limits."""
    head = EDIT_HEAD.format(max_edits=max_edits, cap=edits_mod.size_cap(skill_md, max_growth), size=len(skill_md))
    parts = [head, "## SKILL.md", skill_md, "## Reflection", reflection.strip()]
    parts += _sets("## Rejected edit sets (they did not beat the current skill on held-out tasks; do not repeat "
                   "them)", list(rejected))
    parts += _sets("## Already proposed this round (propose a different edit set)",
                   [{"edits": item} for item in proposed])
    parts += ["## Edit set schema", SCHEMA, TAIL]
    return "\n\n".join(parts)


def extract_edits(reply):
    """The edit list in a model reply: bare JSON, a fenced block, or the outermost [...]; EditError if none."""
    text = (reply or "").strip()
    tries = [text] + FENCE.findall(text)
    if "[" in text and "]" in text:
        tries.append(text[text.index("["):text.rindex("]") + 1])
    for candidate in tries:
        try:
            return edits_mod.parse_edits(json.loads(candidate))
        except (ValueError, edits_mod.EditError):
            continue
    raise edits_mod.EditError("no edit set (JSON list) in the reply")


def reflect(skill_md, failures, *, ledger, model=llm.DEFAULT_MODEL, **kw):
    """One reflection call: the llm.call dict (`text` is the reflection)."""
    return llm.call(reflection_prompt(skill_md, failures), ledger=ledger, kind="reflect", model=model, **kw)


def propose(skill_md, reflection, *, ledger, rejected=(), proposed=(), model=llm.DEFAULT_MODEL,
            max_edits=edits_mod.MAX_EDITS, max_growth=edits_mod.MAX_GROWTH, **kw):
    """One edit-set call: the llm.call dict plus `edits` (a list, or None with `error` set when unparsable)."""
    prompt = edit_prompt(skill_md, reflection, rejected, proposed, max_edits, max_growth)
    out = llm.call(prompt, ledger=ledger, kind="edit", model=model, **kw)
    out["edits"] = None
    if out["error"] is None:
        try:
            out["edits"] = extract_edits(out["text"])
        except edits_mod.EditError as exc:
            out["error"] = f"parse: {exc}"
    return out


class RejectedBuffer:
    """The run's rejected edit sets (module doc); reopening reloads them."""

    def __init__(self, path):
        self.path = Path(path)
        self.entries = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict):
                    self.entries.append(entry)

    def add(self, edit_set, margin, **fields):
        entry = {"at": _now(), "edits": edit_set, "margin": margin}
        entry.update(fields)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self.entries.append(entry)
        return entry

    def recent(self, n=RECENT_REJECTED):
        return self.entries[-n:] if n else []

    def __len__(self):
        return len(self.entries)
