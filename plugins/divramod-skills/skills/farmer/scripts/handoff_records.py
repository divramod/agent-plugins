"""The handoff against the role's open records (hal2 plan 0611 step 7, design.md §5, D9): a handoff that leaves an open
record unnamed, or says one is done while it is open, or goes against an open order, is refused by `handoff --clear`
and warned about by `act` (handoff.records_problems). Generic: a role without registered record kinds passes untouched;
the words that go against a record type are the role's (`role_records.register_contra`).

* mentioned: the record's id `R<n>` stands in handoff.md as a word (an id match is exact, free text is judgment);
* contradiction: the part of a sentence from `R<n>` to the next id says done|closed|dropped|fixed|landed|held back
  while the record is open (unless negated: "not fixed"), or a sentence goes against an open record by its type's rule.
"""

import re

DONE = re.compile(r"\b(?:done|closed|dropped|fixed|landed|held back|resolved|finished)\b", re.I)
NEGATOR = re.compile(r"\b(?:never|no|not|nobody|nor|without|don'?t|do not|must not|cannot|still|until|unless)\b", re.I)
ID = re.compile(r"\bR\d+\b")


def sentences(text: str) -> list[str]:
    """The handoff's sentences: split at line ends and after `.` `!` `?` (a bullet is one line)."""
    return [s.strip() for part in text.splitlines() for s in re.split(r"(?<=[.!?])\s+", part) if s.strip()]


def _says_done(part: str) -> bool:
    """`part` (from one id to the next) says done, not negated before the word."""
    return any(not NEGATOR.search(re.split(r"[;:.]", part[:m.start()])[-1][-40:]) for m in DONE.finditer(part))


def problems(text: str, open_: list[dict], contra: dict) -> list[str]:
    """What is wrong with `text` against the open records, one line each (empty: fine)."""
    out = [f"{r['id']} ({r['type']} {r['slot']}) is open and not named: {r['what'][:80]}"
           for r in open_ if not re.search(rf"\b{re.escape(r['id'])}\b", text)]
    ids = {r["id"] for r in open_}
    for sentence in sentences(text):
        marks = [m for m in ID.finditer(sentence) if m.group(0) in ids]
        for m, nxt in zip(marks, marks[1:] + [None]):
            if _says_done(sentence[m.end():nxt.start() if nxt else len(sentence)]):
                out.append(f"{m.group(0)} is open, but the handoff says it is done: {sentence[:120]}")
        for r in open_:
            rule = contra.get(r["type"])
            if rule and rule(r, sentence):
                out.append(f"the handoff goes against {r['id']} ({r['type']} {r.get('rule', r['slot'])}): {sentence[:120]}")
    return out
