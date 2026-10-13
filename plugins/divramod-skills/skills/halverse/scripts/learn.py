#!/usr/bin/env python3
"""Count the user's old words against their farm words (plan 0270, D4, D6, D7, D8).

Pure: no file is read here except `pairs.json`; the prompts come in as `Message`s (or plain strings). Stores and
sends nothing. Python stdlib only.
"""
import json
import os
import re
import textwrap
from typing import Dict, Iterable, List, NamedTuple, Optional, Tuple

PAIRS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pairs.json")
EXAMPLE_WIDTH = 100
TABLE_WIDTH = 100
# A whole word: not inside a longer or hyphenated one (screenshot, one-shot), not a slash command (/mtm).
_BEFORE = r"(?<!\w)(?<!\w-)(?<!^/)(?<!\s/)"
_AFTER = r"(?!-?\w)"
_OLD, _AMBIGUOUS, _NEW = 0, 1, 2  # the order of preference for one stretch of text


class Pair(NamedTuple):
    new: str
    since: str
    command: Optional[str]
    practise: bool
    old_label: str
    old: Tuple[str, ...]
    new_forms: Tuple[str, ...]
    ambiguous: Tuple[Tuple[str, str], ...]  # (regex, note)
    note: str


class PairSet(NamedTuple):
    pairs: List[Pair]
    keep_names: List[str]


class Stat:
    """The counts of one pair."""

    def __init__(self, pair: Pair):
        self.pair = pair
        self.old = 0
        self.new = 0
        self.ambiguous: Dict[str, int] = {}  # the ambiguous form (as typed, lower case) -> uses
        self.example: Optional[Tuple[str, str]] = None  # (sortable time, the example line)

    @property
    def ambiguous_count(self) -> int:
        return sum(self.ambiguous.values())

    @property
    def share(self) -> Optional[float]:
        total = self.old + self.new
        return self.new / total if total else None

    @property
    def used(self) -> bool:
        return bool(self.old or self.new or self.ambiguous)


def load_pairs(path: Optional[str] = None) -> PairSet:
    with open(path or PAIRS_FILE, encoding="utf-8") as handle:
        data = json.load(handle)
    pairs = [Pair(p["new"], p["since"], p.get("command"), bool(p.get("practise", True)), p.get("old_label", ""),
                  tuple(p["old"]), tuple(p["new_forms"]),
                  tuple((a["form"], a["note"]) for a in p.get("ambiguous", [])), p.get("note", ""))
             for p in data["pairs"]]
    return PairSet(pairs, list(data.get("keep_names", [])))


def _compile(forms: Iterable[str]) -> Optional["re.Pattern[str]"]:
    forms = list(forms)
    if not forms:
        return None
    return re.compile(_BEFORE + "(?:" + "|".join(forms) + ")" + _AFTER, re.I | re.M)


def _candidates(text: str, pairs: List[Pair]) -> List[Tuple[int, int, int, int]]:
    """(start, end, pair index, kind) of every match of every form."""
    found = []
    for i, pair in enumerate(pairs):
        for kind, forms in ((_OLD, pair.old), (_AMBIGUOUS, [a[0] for a in pair.ambiguous]), (_NEW, pair.new_forms)):
            rx = _compile(forms)
            if rx:
                found.extend((m.start(), m.end(), i, kind) for m in rx.finditer(text))
    return found


def matches(text: str, pairs: List[Pair]) -> List[Tuple[int, int, int, int]]:
    """The uses in one text: the longest match of a stretch wins, an old form beats an ambiguous one beats a new one."""
    chosen: List[Tuple[int, int, int, int]] = []
    for cand in sorted(_candidates(text, pairs), key=lambda c: (c[0] - c[1], c[3], c[0])):
        if all(cand[1] <= c[0] or cand[0] >= c[1] for c in chosen):
            chosen.append(cand)
    return sorted(chosen)


def example_line(line: str, start: int, end: int, new_word: str, width: int = EXAMPLE_WIDTH) -> str:
    """The user's line with the match replaced by the new word, cut to `width` characters around it."""
    snippet = line[:start] + new_word + line[end:]
    if len(snippet) <= width:
        return snippet.strip()
    centre = start + len(new_word) // 2
    first = max(0, min(centre - width // 2, len(snippet) - width))
    piece = snippet[first:first + width]
    if first > 0:
        piece = "…" + piece[1:]
    if first + width < len(snippet):
        piece = piece[:-1] + "…"
    return piece.strip()


def _line_of(text: str, start: int, end: int) -> Tuple[str, int, int]:
    begin = text.rfind("\n", 0, start) + 1
    stop = text.find("\n", end)
    stop = len(text) if stop < 0 else stop
    return text[begin:stop], start - begin, end - begin


def _named_both(found: List[Tuple[int, int, int, int]]) -> set:
    """The pairs a message names with an old and a new word: a definition or a question about them, not a use."""
    old = {i for _, _, i, kind in found if kind == _OLD}
    new = {i for _, _, i, kind in found if kind == _NEW}
    return old & new


def count(messages: Iterable[object], pairs: List[Pair]) -> List[Stat]:
    """The counts per pair; a message is a `Message` (text, timestamp) or a plain string."""
    stats = [Stat(p) for p in pairs]
    for message in messages:
        text = getattr(message, "text", message)
        stamp = getattr(message, "timestamp", None)
        key = stamp.isoformat() if stamp is not None else ""
        found = matches(str(text), pairs)
        named_both = _named_both(found)
        for start, end, index, kind in found:
            stat = stats[index]
            if index in named_both and kind != _AMBIGUOUS:
                continue  # the message talks about the pair itself ("mtm is now harvest"): it counts neither word
            if kind == _OLD:
                stat.old += 1
                if stat.example is None or key >= stat.example[0]:
                    line, s, e = _line_of(str(text), start, end)
                    stat.example = (key, example_line(line, s, e, stat.pair.new))
            elif kind == _NEW:
                stat.new += 1
            else:
                form = " ".join(str(text)[start:end].lower().split())
                stat.ambiguous[form] = stat.ambiguous.get(form, 0) + 1
    return stats


def ranked(stats: List[Stat]) -> List[Stat]:
    """The used pairs, most old-word uses first (ties: more ambiguous uses, then the word)."""
    return sorted((s for s in stats if s.used), key=lambda s: (-s.old, -s.ambiguous_count, s.pair.new))


def practise(stats: List[Stat], limit: int = 3) -> List[Stat]:
    """The words to practise (D7): most old uses, ties by the lower share; a pair that stays or is unused is left out."""
    return sorted((s for s in stats if s.pair.practise and s.old > 0),
                  key=lambda s: (-s.old, s.share if s.share is not None else 0.0, s.pair.new))[:limit]


def _percent(stat: Stat) -> str:
    return "-" if stat.share is None else "%d%%" % round(stat.share * 100)


def table(stats: List[Stat]) -> str:
    """The text table: old word, new word, old uses, new uses, share of the new word, ambiguous; the example under its row.

    At most TABLE_WIDTH columns, so it reads in a terminal 100 columns wide: the example (one line of the user's own)
    sits indented under its row instead of beside it.
    """
    head = ("old word", "new word", "old", "new", "share", "ambig.")
    rows = [(s.pair.old_label, s.pair.new, str(s.old), str(s.new), _percent(s), str(s.ambiguous_count)) for s in ranked(stats)]
    widths = [max(len(r[i]) for r in [head] + rows) for i in range(len(head))]
    out = ["  ".join(head[i].ljust(widths[i]) for i in range(len(head))).rstrip()]
    for stat, row in zip(ranked(stats), rows):
        out.append("  ".join(row[i].ljust(widths[i]) for i in range(len(head))).rstrip())
        if stat.example:
            out += textwrap.wrap("e.g. " + stat.example[1], TABLE_WIDTH, initial_indent="  ", subsequent_indent="       ")
    return "\n".join(out)


def wrap(line: str) -> str:
    """A text line wrapped to TABLE_WIDTH columns, its continuation indented."""
    return "\n".join(textwrap.wrap(line, TABLE_WIDTH, subsequent_indent="  ", break_long_words=False)) or line


def ambiguous_lines(stats: List[Stat]) -> List[str]:
    """Per pair and ambiguous rule one line: the forms used with their counts and why they are not guessed."""
    lines = []
    for stat in ranked(stats):
        by_rule: Dict[str, List[Tuple[str, int]]] = {}
        for form, uses in sorted(stat.ambiguous.items(), key=lambda kv: (-kv[1], kv[0])):
            rule = next((i for i, (rx, _) in enumerate(stat.pair.ambiguous) if re.fullmatch(rx, form, re.I)), -1)
            by_rule.setdefault(stat.pair.ambiguous[rule][1] if rule >= 0 else "", []).append((form, uses))
        for why, forms in by_rule.items():
            lines.append("ambiguous for %s: %s (%s)" % (stat.pair.new, ", ".join('"%s" %d' % f for f in forms), why))
        if stat.pair.note:
            lines.append("note for %s: %s" % (stat.pair.new, stat.pair.note))
    return lines


def coverage_warnings(pairset: PairSet, words: Iterable[object], headings: Iterable[Tuple[str, str]]) -> List[str]:
    """A farm word of the ontology or a glossary heading without a pair (D8, D9); `words` are `sources.FarmWord`s."""
    news = {p.new.lower() for p in pairset.pairs}
    keep = {k.lower() for k in pairset.keep_names}
    warnings = []
    for word in words:
        name = getattr(word, "word")
        if getattr(word, "in_force") and name.lower() not in news and name.lower() not in keep:
            warnings.append('farm word "%s" (ontology: %s) has no pair in pairs.json' % (name, getattr(word, "section")))
    for old, new in headings:
        if new.lower() not in news and new.lower() not in keep:
            warnings.append('glossary heading "%s, %s" has no pair in pairs.json' % (old, new))
    return warnings
