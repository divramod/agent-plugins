#!/usr/bin/env python3
"""The user's halverse files as `hal2-cli-halverse` reads them (plan 0270 D3, D8; plan 0276 D37).

`load()` runs `terms --json` and `ontology --json` (cli.py); the CLI is the one parser, nothing here reads a file. The
seven functions take what `load()` returns and give the farm words of the ontology's `Farm word` tables with their
status, the glossary headings with two or more terms, the ontology's sections as data, the glossary's entries, one
entry, the ontology lines naming a term and every known term. Only reads. Python stdlib only.
"""
import re
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

import cli


class Loaded(NamedTuple):
    terms: Dict[str, Any]  # `terms --json`
    ontology: Dict[str, Any]  # `ontology --json`


def load() -> Loaded:
    """Both answers of the CLI; raises cli.CliError (not installed, a file it cannot read)."""
    return Loaded(cli.call(["terms"]), cli.call(["ontology"]))


class FarmWord(NamedTuple):
    word: str
    stands_for: str
    status: str
    section: str

    @property
    def in_force(self) -> bool:
        return self.status.lower().startswith("in force")


def _title(section: Dict[str, Any]) -> str:
    return "%s (%s)" % (section["title"], section["note"]) if section.get("note") else section["title"]


def farm_words(data: Loaded) -> List[FarmWord]:
    """Every word of a `Farm word` column; a table without a Status column is in force."""
    found: List[FarmWord] = []
    for section in data.ontology.get("sections", []):
        for table in section.get("tables", []):
            header = table["header"]
            if not header or header[0] != "farm word":
                continue
            for row in table["rows"]:
                cells = row["cells"]
                status = cells[header.index("status")] if "status" in header and len(cells) > header.index("status") else "in force"
                stands = cells[1] if len(cells) > 1 else ""
                found.extend(FarmWord(w, stands, status, _title(section)) for w in _words(cells[0]))
    return found


def _words(cell: str) -> List[str]:
    return [w.strip().strip("`").strip() for w in cell.split(",") if w.strip().strip("`").strip()]


def glossary_pairs(data: Loaded) -> List[Tuple[str, str]]:
    """The (old, new) of every glossary entry with two or more heads: `**shot**, **seed**:` is ("shot", "seed")."""
    return [(t["term"], new) for t in data.terms.get("terms", []) if t.get("glossary") for new in t["synonyms"]]


class Section(NamedTuple):
    title: str  # the heading without its parenthesis
    note: str  # the heading's parenthesis: "in force, synonyms"
    rows: List[dict]  # the rows of its tables, keyed by the lower-case column name
    lines: List[str]  # its other lines: bullets (continuation lines joined) and prose


def ontology_sections(data: Loaded) -> List[Section]:
    """The `##` sections of the ontology as data: table rows and the other lines, nothing interpreted."""
    return [Section(s["title"], s.get("note") or "",
                    [dict(zip(t["header"], r["cells"])) for t in s["tables"] for r in t["rows"]],
                    [line["text"] for line in s["lines"]])
            for s in data.ontology.get("sections", [])]


class Entry(NamedTuple):
    terms: List[str]
    text: str  # the definition: the `_Avoid_` and `_de_:` lines are fields of the CLI's terms of their own


def glossary_entries(data: Loaded) -> List[Entry]:
    """Every glossary entry: its heads (`**shot**, **seed**:`) and its definition."""
    return [Entry([t["term"]] + list(t["synonyms"]), t["definition"]) for t in data.terms.get("terms", []) if t.get("glossary")]


def _norm(term: str) -> str:
    return term.strip().strip("\"'`").lower()


def glossary_entry(data: Loaded, term: str) -> Optional[Entry]:
    """The entry that has `term` among its heads, the second of a pair too."""
    return next((e for e in glossary_entries(data) if _norm(term) in [_norm(t) for t in e.terms]), None)


def ontology_mentions(data: Loaded, term: str) -> List[Tuple[str, str]]:
    """(section, line or table row) of every place in the ontology that names `term` as a whole word."""
    pattern = re.compile(r"(?<![\w-])" + re.escape(_norm(term)) + r"(?![\w-])", re.IGNORECASE)
    found: List[Tuple[str, str]] = []
    for sec in ontology_sections(data):
        found.extend((sec.title, " | ".join(r.values())) for r in sec.rows if pattern.search(" | ".join(r.values())))
        found.extend((sec.title, text) for text in sec.lines if pattern.search(text))
    return found


def all_terms(data: Loaded) -> List[str]:
    """Every known term: the CLI's terms with their synonyms, and the ontology's farm words."""
    terms = {t["term"] for t in data.terms.get("terms", [])} | {s for t in data.terms.get("terms", []) for s in t["synonyms"]}
    return sorted(terms | {w.word for w in farm_words(data)})
