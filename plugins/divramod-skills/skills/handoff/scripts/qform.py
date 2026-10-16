"""The Q form of a questions file's open agent questions (hal2 plan 0329): exactly three option lines a) b) c), each
on its own line, the first marked "(Recommended)" (~/AGENTS.md, "Questions to the user").

hal2 owns the rule (`hal2-cli-plans questions check --json`, `$HAL2_CLI_PLANS`, else on PATH); the skills call it
and degrade without it (decision D7 of plan 0329): `form_problems` is the fallback, the same rule with the same
split of inline options (D3: only the ordered sequence ` a) `, ` b) `, ` c) `, once each). `questions.py --check`
uses the CLI when present; q's `q.py` loads this module by path for its own fallback (D9).
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

ENV = "HAL2_CLI_PLANS"
NAME = "hal2-cli-plans"
OPTION = re.compile(r"^\s+([a-c])\) ?(.*)$")
INLINE = "its options a) b) c) are inline in the question; the Q form puts each on its own line"


def split_inline(text: str) -> tuple[str, list[str]] | None:
    """The question text and its three options when ` a) `, ` b) ` and ` c) ` each stand exactly once, in that
    order, after some question text and with no ` d) ` after them; otherwise None (nothing is guessed, D3)."""
    at = []
    for marker in (" a) ", " b) ", " c) "):
        i = text.find(marker)
        if i < 0 or text.find(marker, i + 1) >= 0:
            return None
        at.append(i)
    a, b, c = at
    if not a < b < c or " d) " in text[c:]:
        return None
    head = text[:a].strip()
    options = [text[a + 4:b].strip(), text[b + 4:c].strip(), text[c + 4:].strip()]
    return (head, options) if head and all(options) else None


def lines_of(question: str) -> tuple[str, list[str], bool]:
    """The question text, its option lines (`  a) ...` as written) and whether they were inline in the text."""
    lines = (question or "").split("\n")
    options = [ln for ln in lines if OPTION.match(ln)]
    if options:
        return "\n".join(ln for ln in lines if not OPTION.match(ln)), options, False
    split = split_inline(" ".join(lines))
    if split:
        return split[0], [f"  {'abc'[i]}) {o}" for i, o in enumerate(split[1])], True
    return question or "", [], False


def binary() -> str | None:
    """The CLI: `$HAL2_CLI_PLANS` when it names a file, else `hal2-cli-plans` on PATH; None when neither."""
    named = os.environ.get(ENV, "").strip()
    if named:
        return named if Path(named).expanduser().is_file() else None
    return shutil.which(NAME)


def cli_problems(path: Path) -> list[str] | None:
    """The CLI's problems of the store (`Q<n>: <message>` lines), or None without a CLI that has `questions check`."""
    cli = binary()
    if cli is None:
        return None
    out = subprocess.run([str(Path(cli).expanduser()), "questions", "check", "--json", "--store", str(path)],
                         capture_output=True, text=True)
    try:
        found = json.loads(out.stdout)["problems"] if out.returncode in (0, 1) else None
    except (json.JSONDecodeError, KeyError):
        return None
    if found is None:
        return None
    return [f"Q{p['n']}: {p['message']}" if p.get("n") else p["message"] for p in found]


def form_problems(entries: list[dict], raw: dict[int, dict]) -> list[str]:
    """The fallback rule over `questions.parse` entries and `questions.raw_entries` text: one line per open agent
    entry that is not in the Q form (an answered or dropped one is history and never reported)."""
    problems = []
    for e in entries:
        if e["state"] != "open" or e["by"] != "agent" or e["n"] not in raw:
            continue
        lines = raw[e["n"]]["question"].splitlines()
        options = [m for m in (OPTION.match(ln) for ln in lines[1:]) if m]
        if not options and split_inline(" ".join(lines)):
            problems.append(f"Q{e['n']}: {INLINE}")
        elif [m.group(1) for m in options] != ["a", "b", "c"]:
            problems.append(f"Q{e['n']}: {len(options)} option lines; the Q form needs exactly three, a) b) c), "
                            "each on its own line")
        elif "(Recommended)" not in options[0].group(2):
            problems.append(f"Q{e['n']}: option a) is not marked \"(Recommended)\"; the Q form recommends the first")
        elif any("(Recommended)" in m.group(2) for m in options[1:]):
            problems.append(f"Q{e['n']}: only option a) may be marked \"(Recommended)\"")
    return problems
