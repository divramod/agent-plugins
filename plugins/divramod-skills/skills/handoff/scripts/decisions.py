#!/usr/bin/env python3
"""The decisions this checkout holds, and the farmer's decision check (skills plans 0008, 0012).

  decisions.py [--farmer-repo <repo>] [--json]
  decisions.py --check

Lists the decisions a session continuing with `/handoff c` has: HANDOFF.md's Decisions (the index of every user
decision in force), then the current plan's Decisions and Pre-authorized (the plan `plans/CURRENT_PLAN` names, else
the one HANDOFF.md links; an item holding one of the index's quotes is left out) and HANDOFF.md's Open. Prints the farmer
HANDOFF.md names (`Farmer: <session> (<repo>)`, written by /handoff for a servant), the slot id the farmer knows
(`<slot>`, or `<repo>/<slot>` when the farmer belongs to another repository) and the message to send it:

  decision check <slot>: I have these decisions: (1) ... (2) .... Did I forget one?

In a parallel plan's subservant slot (skills plan 0013: `plans/LEAD` holds `<lead-slot> <plan> <step>`) it adds
`lead` ({slot, plan, step}) to the JSON and a `lead:` line to the text: `/handoff c` there continues that one step
only, never the plan and never a landing. A malformed marker still marks the slot: `lead` is {bad: true, error,
text} and the text says `lead: broken marker ...`.

`--check` validates HANDOFF.md's Decisions section after /handoff wrote it: the section exists (`- none` when the
work holds no user decision) and every line is `- <YYYY-MM-DD> "<the user's words>" (<who relayed it>) · home: <plan |
INTENT.md | .adr/<file>.md | a relative path>[ · ended <YYYY-MM-DD>: <why>]`, its home file exists and holds the
quote (when the quote is distinctive). It prints `ok` or one problem per line.

A plan in the record format (where.py: form `record`; hal2 plan 0206) has no Decisions section in its handoff: its
index is the plan's ledger `decisions.md`. The list is then the ledger's entries that are in force or promoted, the
plan's Pre-authorized and the handoff's Watch out, and `--check` is the plan-folder check of that plan (the plan
skill's `plan.py check <folder>`: the four records' form and their links).

A legacy line's home `plan` is the plan's plan.md or its decisions.md. A home that is a generated file (an
`INTENT.md` whose decision log is generated from the decision records) holds no quote: the line names the decision
record (`.adr/<slug>.md`) or the plan instead.

Exit 0 printed (or `--check` ok), 1 `--check` found problems, 2 git missing.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import where

ITEM_CHARS = 240
GENERATED_LOG = "<!-- generated: decision-log -->"
FARMER = re.compile(r"^Farmer:\s*`?([^\s`(]+)`?(?:\s*\(([^)]+)\))?", re.M)
PLAN_LINK = re.compile(r"\]\(((?:\./)?plans/[^)\s]+/plan\.md)\)")
QUOTED = re.compile(r'"([^"]+)"|“([^”]+)”')
DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})\b")
HOME = re.compile(r"\bhome:\s*(.+?)\s*(?:·\s*ended\b.*)?$", re.I)
ENDED = re.compile(r"·\s*ended\b(.*)$", re.I)
MD_PATH = re.compile(r"\(([^)\s]+\.md)\)|(?<![\w/])((?:\.?[\w-]+/)*[\w.-]+\.md)\b")
STOP = {"with", "that", "this", "from", "into", "have", "after", "before", "when", "then", "than", "them", "they",
        "their", "there", "what", "which", "where", "every", "each", "also", "only", "should", "would", "could", "must",
        "will", "were", "been", "being", "does", "done", "make", "made", "user", "slot", "plan", "step", "steps",
        "decided", "decision", "decisions", "farmer", "servant", "skill"}
RUN = 8  # a long quote is found by 8 consecutive words holding 2 key words


def git(*args: str, cwd: str | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True).stdout.strip()


def section(text: str, title: str) -> list[str]:
    """The bullets of a `## <title>` section, each joined into one line; placeholders (`- <...>`) left out."""
    m = re.search(rf"^## {re.escape(title)}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    items: list[str] = []
    for line in (m.group(1) if m else "").splitlines():
        if re.match(r"^\s{0,1}[-*] ", line):
            items.append(line.strip()[2:].strip())
        elif items and line.startswith("  ") and line.strip():
            items[-1] += " " + line.strip()
    return [i for i in items if i and not i.startswith("<")]


def flat(text: str) -> list[str]:
    """Lower-case alphanumeric words: case, whitespace and punctuation do not matter."""
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def key_words(ws: list[str]) -> set[str]:
    return {w for w in ws if len(w) >= 4 and w not in STOP}


def found(quote: str, text: str) -> bool | None:
    """Does `text` hold the user's quote? A quote of 4-8 words with a key word occurs whole; a longer one by a run of 8
    consecutive words holding 2 key words. None when the quote is too short to tell (fewer than 4 words, no key word)."""
    q, hay = flat(quote), f" {' '.join(flat(text))} "
    if len(q) < 4 or not key_words(q):
        return None
    if len(q) <= RUN:
        return f" {' '.join(q)} " in hay
    runs = (q[i:i + RUN] for i in range(len(q) - RUN + 1))
    return any(len(key_words(r)) >= 2 and f" {' '.join(r)} " in hay for r in runs)


def quoted(item: str) -> list[str]:
    return [(a or b).strip() for a, b in QUOTED.findall(item)]


def home_file(root: Path, home: str, plan: Path | None) -> Path | None:
    """The file a Decisions line's `home:` names: `plan` is the current plan, else the first `.md` path in it."""
    if re.match(r"plan\b(?!s/)", home, re.I):
        return plan
    m = MD_PATH.search(home)
    return root / (m.group(1) or m.group(2)) if m else None


def check_record(root: Path, at: dict) -> list[str]:
    """The problems of the plan folder whose ledger is the decisions index: hal2's records checker over it (the plan
    skill's checker.py, as `plan.py check <folder>`); without the checker one advisory line, no problem."""
    folder = str(Path(at["plan"]).parent) + "/"
    try:
        found = where.checker.check(repo=root)
    except where.checker.CheckerError as error:
        return [str(error)]
    if found is None:
        print(where.checker.NOT_INSTALLED)
        problems = []
    else:
        problems = [where.checker.line(p) for p in found["problems"] if p["path"].startswith(folder)]
    if not (root / at["file"]).is_file():
        problems.append(f"{at['file']}: missing (where.py --stamp writes it)")
    return problems


def holds(quotes: list[str], files: list[Path]) -> bool:
    """Is a quote in one of the files, or too short to tell in all of them?"""
    texts = [f.read_text() for f in files if f.is_file()]
    return not all(found(q, text) is False for q in quotes for text in texts) if texts else False


def check(root: Path) -> list[str]:
    """The problems of the decisions index (HANDOFF.md's Decisions section; a record plan: its folder); empty when
    it is complete."""
    at = where.locate(root)
    if at["form"] == "record":
        return check_record(root, at)
    path = root / "HANDOFF.md"
    if not path.exists():
        return ["no HANDOFF.md"]
    handoff = path.read_text()
    if not re.search(r"^## Decisions\s*$", handoff, re.M):
        return ["HANDOFF.md has no `## Decisions` section (write `- none` when the work holds no user decision)"]
    items = section(handoff, "Decisions")
    if not items:
        return ["`## Decisions` is empty: list every user decision in force, or `- none`"]
    plan, problems = plan_file(root, handoff), []
    for n, item in enumerate(items, 1):
        if re.fullmatch(r"none\.?", item, re.I):
            continue
        say = lambda why: problems.append(f"Decisions line {n}: {why}: {short(item)}")  # noqa: E731
        if not DATE.match(item):
            say("starts with no date (YYYY-MM-DD)")
        quotes = quoted(item.split("home:")[0])
        if not quotes:
            say('quotes no user\'s words ("...")')
        ended = ENDED.search(item)
        if ended and not re.match(r"\s*\d{4}-\d{2}-\d{2}", ended.group(1)):
            say("`ended` without a date")
        m = HOME.search(item)
        if not m:
            say("names no home (`· home: plan | INTENT.md | <path>.md`)")
            continue
        f = home_file(root, m.group(1), plan)
        if f is None or not f.exists():
            say(f"its home {m.group(1)!r} is no existing file" + (" (no current plan)" if f is None else ""))
        elif GENERATED_LOG in f.read_text() and quotes and not holds(quotes, [f]):
            say(f"its home {f.relative_to(root)} has a generated decision log, which holds no quote: name the "
                "decision record (.adr/<slug>.md) or the plan that holds the user's words")
        elif quotes and not holds(quotes, [f, f.parent / "decisions.md"] if f == plan else [f]):
            say(f"its home {f.relative_to(root)} does not hold the quote (record it there with the user's words)")
    return problems


def plan_file(root: Path, handoff: str) -> Path | None:
    cur = root / "plans" / "CURRENT_PLAN"
    slug = cur.read_text().strip() if cur.exists() else ""
    if slug and (root / "plans" / slug / "plan.md").exists():
        return root / "plans" / slug / "plan.md"
    m = PLAN_LINK.search(handoff)
    return root / m.group(1) if m and (root / m.group(1)).exists() else None


def lead_of(root: Path) -> dict | None:
    """The subservant marker plans/LEAD: {slot, plan, step}; a malformed one {bad: True, error, text}: the slot is
    still a subservant (bad but marked, as the farmer reads it); None without the file."""
    f = root / "plans" / "LEAD"
    if not f.is_file():
        return None
    try:
        text = f.read_text().strip()
    except OSError as e:
        text = f"<unreadable: {e}>"
    parts = text.split()
    if len(parts) < 3 or not re.fullmatch(r"\d\d", parts[0]):
        return {"bad": True, "text": text, "error": f"plans/LEAD is not `<lead-slot> <plan> <step>`: '{text}'"}
    return {"slot": parts[0], "plan": parts[1], "step": parts[2]}


def lead_line(lead: dict) -> str:
    if lead.get("bad"):
        return (f"lead: broken marker ({lead['error']}): still a subservant, never the plan, never a landing; ask "
                "the lead to rewrite plans/LEAD")
    return (f"lead: slot {lead['slot']}, plan {lead['plan']}, step {lead['step']}: a subservant, continue that one "
            "step only (never the plan, never a landing)")


def short(item: str) -> str:
    return item if len(item) <= ITEM_CHARS else item[:ITEM_CHARS - 1].rstrip() + "…"


LEDGER_HEAD = re.compile(r"^(D\d+) · (\d{4}-\d{2}-\d{2}) · (\w+) · (in-force|promoted)$")


def ledger(text: str) -> list[str]:
    """The entries of a decisions ledger that bind the work: in force or promoted, each as one line."""
    out, envelope = [], where.envelope
    for head, body in envelope.entries(envelope.split(text)[1]):
        m = LEDGER_HEAD.match(head.strip())
        if m:
            words = envelope.field(body, "Words")
            out.append(f"{m.group(1)} {m.group(2)} ({m.group(3)}, {m.group(4)}): {envelope.field(body, 'D')}"
                       + (f" Words: {words}" if words else ""))
    return out


def collect(root: Path, main_name: str, farmer_repo: str | None) -> dict:
    at = where.locate(root)
    handoff_path = root / at["file"]
    handoff = handoff_path.read_text() if handoff_path.exists() else ""
    plan = root / at["plan"] if at["plan"] else plan_file(root, handoff)
    plan_text = plan.read_text() if plan else ""
    if at["form"] == "record":
        entries = root / at["decisions"]
        have = [("decisions.md", d) for d in (ledger(entries.read_text()) if entries.is_file() else [])]
        have += [("plan Pre-authorized", d) for d in section(plan_text, "Pre-authorized")]
        have += [("handoff.md Watch out", d) for d in section(handoff, "Watch out")]
    else:
        index = [d for d in section(handoff, "Decisions") if not re.fullmatch(r"none\.?", d, re.I)]
        said = [q for d in index for q in quoted(d.split("home:")[0])]
        indexed = lambda d: any(found(q, d) for q in said)  # noqa: E731
        have = [("HANDOFF.md Decisions", d) for d in index]
        have += [("plan Decisions", d) for d in section(plan_text, "Decisions") if not indexed(d)]
        have += [("plan Pre-authorized", d) for d in section(plan_text, "Pre-authorized") if not indexed(d)]
        have += [("HANDOFF.md Open", d) for d in section(handoff, "Open")]
    m = FARMER.search(handoff)
    farmer, repo = (m.group(1), (m.group(2) or "").strip()) if m else (None, "")
    repo = farmer_repo or repo or main_name
    slot = root.name if repo == main_name else f"{main_name}/{root.name}"
    listed = " ".join(f"({n}) {short(d)}" for n, (_, d) in enumerate(have, 1)).rstrip(".") or "none"
    return {"root": str(root), "plan": str(plan.relative_to(root)) if plan else None, "lead": lead_of(root),
            "farmer": farmer,
            "farmer_repo": repo, "slot": slot, "decisions": [{"from": s, "text": d} for s, d in have],
            "message": f"decision check {slot}: I have these decisions: {listed}. Did I forget one?"}


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--farmer-repo", help="the repository the farmer serves (default: HANDOFF.md's Farmer line, "
                                         "else this one)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--check", action="store_true", help="validate HANDOFF.md's Decisions section")
    args = p.parse_args(argv)
    if not shutil.which("git"):
        print("decisions.py: git is missing; run install-prerequisites.sh", file=sys.stderr)
        return 2
    root = Path(git("rev-parse", "--show-toplevel") or ".").resolve()
    common = git("rev-parse", "--path-format=absolute", "--git-common-dir")
    main_name = Path(common).parent.name if common else root.name
    if args.check:
        problems = check(root)
        print("\n".join(problems) or "ok")
        return 1 if problems else 0
    r = collect(root, main_name, args.farmer_repo)
    if args.json:
        print(json.dumps(r, indent=1))
        return 0
    print(f"plan: {r['plan'] or 'none'}")
    if r["lead"]:
        print(lead_line(r["lead"]))
    for n, d in enumerate(r["decisions"], 1):
        print(f"{n:3}. [{d['from']}] {short(d['text'])}")
    print(f"farmer: {r['farmer'] or 'none named in HANDOFF.md: ListAgents, the session in the farmer slot of ' + r['farmer_repo']}"
          f" (repo {r['farmer_repo']}, slot id {r['slot']})")
    print(f"message: {r['message']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
