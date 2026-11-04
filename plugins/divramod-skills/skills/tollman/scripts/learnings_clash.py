#!/usr/bin/env python3
"""The tollman's handoff against its learnings (hal2 plan 0610 step 8, D20). Field 79 found the tollman's `handoff.md`
saying "never unhitch" and "never --by-user myself" while learnings printed after it (L31, L241) said the opposite:
the model followed whatever it read last. A small table of contradiction pairs, matched on the in-force lines only:

* `unhitch`   do / never: `unhitch`, `re-hitch` ordered against forbidden;
* `by-user`   do / never: the flag `--by-user` ordered against forbidden;
* `frozen`    a formed train stays frozen (a later hitch waits for the next train) against a later hitch joins it.

`check` compares the handoff's sentences with the in-force entries (the archive is out: `learnings.read` skips it, a
`dropped` entry is skipped here); `hard` compares one entry with the user's hard rules (D5 hitch-is-forever: never
unhitch; D1 and D17: a hitched wagon rides, a later hitch joins the open train). `learnings.py rules` marks such an
entry, `tollman.py handoff --clear` refuses and `tollman.py act` warns, each naming the lines.

    learnings_clash.py [--repo <dir>]     the report for the tollman's handoff.md (exit 1 on a clash)
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path

NEGATOR = re.compile(r"\b(?:never|no|not|nobody|nor|without|don'?t|do not|must not|mustn'?t|cannot)\b", re.I)
QUALIFIED = re.compile(r"\b(?:unless|except)\b|\bonly (?:the user|with|when the user|on the user)", re.I)
USER_WORD = re.compile(r"\bthe user'?s? (?:own )?(?:word|words|command|order)\b|\bthe user (?:decided|said|says|ordered)\b"
                       r"|--by-user", re.I)
WINDOW = 40  # characters before a match searched for the negator, back to the last `;` `.` or `:`


@dataclass(frozen=True)
class Topic:
    name: str
    do: re.Pattern  # the action, or one side of the pair
    other: str  # the stance of the other side ("never" for an action topic, "join" for frozen)
    negation: bool  # an action topic: a negated match is "never"
    user_word_neutral: bool = False  # a "do" next to the user's own words is no order


TOPICS = (
    Topic("unhitch", re.compile(r"\b(?:un|re-?)hitch\b", re.I), "never", True, True),
    Topic("by-user", re.compile(r"--by-user\b", re.I), "never", True),
    Topic("frozen", re.compile(r"\bstays? frozen\b|\bfrozen train\b|\bfrozen\b[^.;]*\bnext train\b"
                               r"|\bnext train\b[^.;]*\bfrozen\b", re.I), "join", False),
)
JOIN = re.compile(r"\bjoins? (?:the |an? )?(?:open |standing |formed |frozen )?train\b|\bjoin the open train\b"
                  r"|\btakes? (?:all|every)[^.;]*\binto the train\b", re.I)
# the user's hard rules: topic -> the stance an entry may take (D5, then D1 with D17)
HARD = {"unhitch": ("never", "D5 hitch-is-forever: a hitched wagon is never unhitched"),
        "frozen": ("join", "D1/D17 every wagon rides: a later hitch joins the open train")}
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z`(\"'])")
ITEM = re.compile(r"^\s*(?:[-*]\s|\d+[a-z]?\.\s)")


def _negated(sentence: str, at: int) -> bool:
    before = sentence[max(0, at - WINDOW):at]
    before = re.split(r"[;.:]", before)[-1]
    return bool(NEGATOR.search(before))


def stances(sentence: str) -> dict[str, set[str]]:
    """{topic: stances} of one sentence (a stance is "do", the other side's name, or "never")."""
    found: dict[str, set[str]] = {}
    for t in TOPICS:
        for m in t.do.finditer(sentence):
            if t.negation:
                s = t.other if _negated(sentence, m.start()) else "do"
                if s == "never" and QUALIFIED.search(sentence):
                    continue  # "never ... unless the user says": a condition, not a flat never
                if s == "do" and t.user_word_neutral and USER_WORD.search(sentence):
                    continue
            else:
                s = "frozen"
            found.setdefault(t.name, set()).add(s)
        if t.name == "frozen" and JOIN.search(sentence):
            found.setdefault("frozen", set()).add("join")
    return found


def sentences(text: str) -> list[tuple[int, str]]:
    """(first line number, sentence) of the text: wrapped lines of a bullet joined, then split into sentences."""
    items, cur = [], None
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            cur = None
        elif cur is None or ITEM.match(line):
            cur = [n, ITEM.sub("", line, count=1).strip()]
            items.append(cur)
        else:
            cur[1] += " " + line.strip()
    return [(n, s) for n, body in items for s in SENTENCE.split(body)]


@dataclass(frozen=True)
class Clash:
    topic: str
    line: int
    sentence: str
    entry: int
    slug: str


PAIRS = ({"do", "never"}, {"frozen", "join"})


def _opposite(mine: set[str], theirs: set[str]) -> bool:
    return any({a, b} in PAIRS for a in mine for b in theirs)


def _text(e) -> str:
    return e.rule or e.case


def _live(entries):
    return [e for e in entries if e.status != "dropped"]


def check(handoff: str, entries) -> list[Clash]:
    """A handoff sentence against an in-force entry with the opposite stance on a topic."""
    marks = [(e, n, s, stances(s)) for e in _live(entries) for n, s in sentences(_text(e))]
    out = []
    for line, sentence in sentences(handoff):
        for topic, mine in stances(sentence).items():
            for e, _, _, theirs in marks:
                if topic in theirs and _opposite(mine, theirs[topic]):
                    out.append(Clash(topic, line, sentence, e.n, e.slug))
    return sorted(set(out), key=lambda c: (c.line, c.entry))


def hard(entry) -> list[str]:
    """The user's hard rules an entry's text goes against (D5, D1 with D17), one phrase each."""
    out = []
    for _, sentence in sentences(_text(entry)):
        for topic, mine in stances(sentence).items():
            want = HARD.get(topic)
            if want and _opposite(mine, {want[0]}) and want[1] not in out:
                out.append(want[1])
    return out


def report(clashes: list[Clash], limit: int = 4) -> str:
    """The clashes grouped by handoff sentence, the entries named (the first `limit`, then a count)."""
    lines = []
    for line, sentence in sorted({(c.line, c.sentence) for c in clashes}):
        mine = sorted({(c.entry, c.slug) for c in clashes if (c.line, c.sentence) == (line, sentence)})
        topic = next(c.topic for c in clashes if (c.line, c.sentence) == (line, sentence))
        names = ", ".join(f"L{n} {slug}" for n, slug in mine[:limit])
        more = f" and {len(mine) - limit} more" if len(mine) > limit else ""
        lines.append(f"  handoff.md:{line} [{topic}] \"{sentence[:100]}\" against {names}{more}")
    return "\n".join(lines)


def guard(handoff_file: Path, learnings_dir: Path) -> str:
    """"" without a clash, else the report that names the handoff lines and the in-force learnings they clash with."""
    import learnings
    if not handoff_file.is_file():
        return ""
    found = check(handoff_file.read_text(), learnings.read(learnings_dir))
    if not found:
        return ""
    return ("handoff.md contradicts in-force learnings (printed after it, the model follows what it reads last): "
            "fix the handoff or archive the learning (learnings.py archive), then write it again\n" + report(found))


def main(argv=None) -> int:
    import argparse
    import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
    import handoff
    import mtm_scan
    import tollman
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default=".")
    args = ap.parse_args(argv)
    main_dir = mtm_scan.main_checkout(args.repo)
    f = handoff.path(main_dir, tollman.WIRING)
    text = guard(f, f.parent)
    print(text or "handoff.md agrees with the in-force learnings")
    return 1 if text else 0


if __name__ == "__main__":
    sys.exit(main())
