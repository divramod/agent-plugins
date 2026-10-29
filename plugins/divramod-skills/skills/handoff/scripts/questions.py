#!/usr/bin/env python3
"""The questions and answers of the current work: the file /handoff keeps so a clear loses none.

  questions.py [--json]      the open questions (the first thing after a clear), then `<n> answered`
  questions.py --path        the questions file of this checkout
  questions.py --check       validate the file's entries

The file is the plan's `plans/<NNNN>-<slug>/questions.md` (the plan the `CURRENT_PLAN` pointer names, else the one
HANDOFF.md links), committed with the plan, so the user reads every question and its answer afterwards. Work without
a plan keeps it at `plans/questions.md`. One entry per question, both directions: what the agent asked the user and
what the user asked (or told) the agent that was not yet answered in words:

  ## Q<n> · <YYYY-MM-DD> · <agent | user> · <open | answered <YYYY-MM-DD> | dropped <YYYY-MM-DD>>

  **Q:** <the question; the user's own words quoted>
  **A:** <the answer; the user's own words quoted when the user gave it>
  **Decision:** D<n>      (a plan in the record format, when the answer is a decision: the entry of decisions.md,
                           which names this question with `**From:** Q<n>`)

An open entry has no `**A:**` line (or an empty one). `--check` prints `ok` or one problem per line: a heading that
does not match, a number used twice, no `**Q:**`, an answered entry without an answer, an open one with one, and
(plan 0329) an open question of the agent that is not in the Q form (exactly three option lines a) b) c), the first
"(Recommended)"): by `hal2-cli-plans questions check --json` when it is installed (`$HAL2_CLI_PLANS`), else by
qform.py's fallback rule.

Exit 0 printed (or `--check` ok; no file counts as no questions), 1 `--check` found problems.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import qform

HEAD = re.compile(r"^## Q(\d+) · (\d{4}-\d{2}-\d{2}) · (agent|user) · "
                  r"(open|answered \d{4}-\d{2}-\d{2}|dropped \d{4}-\d{2}-\d{2})\s*$")
PLAN_LINK = re.compile(r"\]\(((?:\./)?plans/[^)\s]+)/plan\.md\)")


def root_of() -> Path:
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], text=True, capture_output=True).stdout.strip()
    return Path(top or ".")


def questions_file(root: Path) -> Path:
    """The current plan's questions.md; `plans/questions.md` for work without a plan. In the store home (hal2 plan
    0409) the copy in the edit folder that where.py renders."""
    try:
        import where  # the plan skill's planhome, through where.py's path to it
    except ImportError:
        where = None
    if where is not None and where.planhome.home(root) is not None:
        found = where.locate(root)["questions"]
        return Path(found) if Path(found).is_absolute() else root / found
    if where is not None:
        name = where.pointers.read(root, "CURRENT_PLAN")  # the git dir's, else the old one in `plans/`
    else:
        current = root / "plans" / "CURRENT_PLAN"
        name = current.read_text().strip() if current.is_file() else ""
    if name and (root / "plans" / name / "plan.md").is_file():
        return root / "plans" / name / "questions.md"
    handoff = root / "HANDOFF.md"
    m = PLAN_LINK.search(handoff.read_text()) if handoff.is_file() else None
    if m and (root / m.group(1) / "plan.md").is_file():
        return root / m.group(1) / "questions.md"
    return root / "plans" / "questions.md"


def shown(path: Path, root: Path) -> Path:
    """`path` below `root`, or as it is (the store home's copy lies outside the tree)."""
    return path.relative_to(root) if path.is_relative_to(root) else path


def field(body: str, name: str) -> str:
    """The text of a `**<name>:**` line and the lines that continue it."""
    m = re.search(rf"^\*\*{name}:\*\*[ \t]*(.*?)(?=^\*\*[A-Za-z]+:\*\*|\Z)", body, re.M | re.S)
    return " ".join(m.group(1).split()) if m else ""


def parse(text: str) -> tuple[list[dict], list[str]]:
    entries: list[dict] = []
    problems: list[str] = []
    parts = re.split(r"^(## .*)$", text, flags=re.M)
    for head, body in zip(parts[1::2], parts[2::2]):
        m = HEAD.match(head)
        if not m:
            problems.append(f"heading does not match `## Q<n> · <date> · agent|user · open|answered <date>`: {head}")
            continue
        entries.append({"n": int(m.group(1)), "asked": m.group(2), "by": m.group(3),
                        "state": m.group(4).split()[0], "q": field(body, "Q"), "a": field(body, "A")})
    return entries, problems


def raw_entries(text: str) -> dict[int, dict]:
    """Per entry number the `**Q:**` text as written (lines and option lines kept, `question`) and the date the
    entry was answered or dropped (`closed`, empty when open); the `/q` skill prints entries as they stand."""
    out: dict[int, dict] = {}
    parts = re.split(r"^(## .*)$", text, flags=re.M)
    for head, body in zip(parts[1::2], parts[2::2]):
        m = HEAD.match(head)
        if not m:
            continue
        q = re.search(r"^\*\*Q:\*\*[ \t]*(.*?)(?=^\*\*[A-Za-z]+:\*\*|\Z)", body, re.M | re.S)
        lines = [ln.rstrip() for ln in (q.group(1) if q else "").strip().splitlines()]
        state = m.group(4).split()
        out[int(m.group(1))] = {"question": "\n".join(lines), "closed": state[1] if len(state) > 1 else ""}
    return out


def check(entries: list[dict], problems: list[str]) -> list[str]:
    seen: set[int] = set()
    for e in entries:
        if e["n"] in seen:
            problems.append(f"Q{e['n']}: the number is used twice")
        seen.add(e["n"])
        if not e["q"]:
            problems.append(f"Q{e['n']}: no **Q:** line")
        if e["state"] == "answered" and not e["a"]:
            problems.append(f"Q{e['n']}: answered, but no **A:** line")
        if e["state"] == "open" and e["a"]:
            problems.append(f"Q{e['n']}: open, but it has an answer (set `answered <date>`)")
    return problems


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--path", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    root = root_of()
    path = questions_file(root)
    if args.path:
        print(shown(path, root))
        return 0
    entries, problems = parse(path.read_text()) if path.is_file() else ([], [])
    if args.check:
        problems = check(entries, problems)
        if path.is_file():
            # hal2 owns the Q-form rule (qform.py): its answer includes the checks above; without it the fallback.
            from_cli = qform.cli_problems(path)
            problems = from_cli if from_cli is not None else problems + qform.form_problems(
                entries, raw_entries(path.read_text()))
        print("\n".join(problems) if problems else "ok")
        return 1 if problems else 0
    open_ = [e for e in entries if e["state"] == "open"]
    if args.json:
        print(json.dumps({"file": str(shown(path, root)), "open": open_,
                          "answered": len(entries) - len(open_), "next": max([e["n"] for e in entries], default=0) + 1}))
        return 0
    for e in open_:
        print(f"Q{e['n']} ({e['by']}, {e['asked']}): {e['q']}")
    print(f"{len(open_)} open, {len(entries) - len(open_)} answered or dropped ({shown(path, root)})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
