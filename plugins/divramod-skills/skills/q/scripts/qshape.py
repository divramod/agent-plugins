"""q-only helpers of q.py: the warning line, the structural form-problem test and the fallback's JSON entry. The
Q form itself (the one inline split, D3) lives in handoff's `qform.py`, which q.py loads and passes in (D9)."""

import re


def form_problem(form, e: dict) -> str | None:
    """Why an open agent entry is not in the Q form, if it is not (the CLI's `questions check` says the same)."""
    if e["state"] != "open" or e["by"] != "agent":
        return None
    _, options, inline = form.lines_of(e["question"])
    if inline:
        return form.INLINE
    if len(options) != 3:
        return f"{len(options)} option lines; the Q form needs exactly three, a) b) c), each on its own line"
    return None


def warning(problems: list[tuple[int, str]]) -> str:
    """One line for all problems, the entries grouped by their reason: `warning: Q31, Q32: <reason>`."""
    groups: dict[str, list[str]] = {}
    for n, reason in problems:
        groups.setdefault(reason, []).append(f"Q{n}")
    return "warning: " + "; ".join(f"{', '.join(ns)}: {reason}" for reason, ns in groups.items())


def is_form_problem(n: int | None, entries: list[dict]) -> bool:
    """Whether the CLI's check problem for entry `n` is only a malformed option form, told structurally from the
    entries of `list --json`: the number is unique, the entry is an open agent entry with a question and no answer.
    Anything else (a heading that did not parse, a number twice, no question, an answer on an open entry) breaks
    the store."""
    mine = [e for e in entries if e.get("n") == n]
    if n is None or len(mine) != 1:
        return False
    e = mine[0]
    return e["state"] == "open" and e["by"] == "agent" and bool(e["question"]) and not e["answer"]


def decisions(text: str) -> dict[int, int]:
    """The `**Decision:** D<n>` of each entry number, for the entries that have one."""
    out: dict[int, int] = {}
    parts = re.split(r"^## Q(\d+) ", text, flags=re.M)
    for n, body in zip(parts[1::2], parts[2::2]):
        m = re.search(r"^\*\*Decision:\*\*[ \t]*D(\d+)", body, re.M)
        if m:
            out[int(n)] = int(m.group(1))
    return out


def json_entry(form, e: dict, decision: int | None) -> dict:
    """An entry as `hal2-cli-plans questions list --json` has it, so both paths agree: `question` without its
    options, `options` without the `a) ` prefix, `answer`, `decision`, `inline`, and `date` once closed."""
    text, lines, inline = form.lines_of(e["question"])
    out = {"n": e["n"], "asked": e["asked"], "by": e["by"], "state": e["state"]}
    if e["state"] != "open":
        out["date"] = e["closed"]
    return {**out, "question": " ".join(text.split()), "options": [form.OPTION.match(ln).group(2).strip() for ln in lines],
            "answer": e["a"], "decision": decision, "inline": inline}
