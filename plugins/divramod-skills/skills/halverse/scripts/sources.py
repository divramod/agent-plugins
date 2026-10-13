#!/usr/bin/env python3
"""The user's two source files, read at call time and never copied (plan 0270, D3, D8).

`~/.claude/GLOSSARY.md` and `~/.claude/HALVERSE-ONTOLOGY.md` (roots from `HALVERSE_GLOSSARY` and
`HALVERSE_ONTOLOGY`). Parses the farm words of the ontology's tables (Activities and Places) with their status and the
glossary headings of the form `**old**, **new**`. Only reads. Python stdlib only.
"""
import os
import re
from typing import List, NamedTuple, Optional, Tuple

GLOSSARY_ENV = "HALVERSE_GLOSSARY"
ONTOLOGY_ENV = "HALVERSE_ONTOLOGY"


class FarmWord(NamedTuple):
    word: str
    stands_for: str
    status: str
    section: str

    @property
    def in_force(self) -> bool:
        return self.status.lower().startswith("in force")


def glossary_path() -> str:
    return os.environ.get(GLOSSARY_ENV) or os.path.expanduser("~/.claude/GLOSSARY.md")


def ontology_path() -> str:
    return os.environ.get(ONTOLOGY_ENV) or os.path.expanduser("~/.claude/HALVERSE-ONTOLOGY.md")


def read_text(path: str) -> Optional[str]:
    """The file's text, None when it is missing or unreadable."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def _cells(line: str) -> List[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _words(cell: str) -> List[str]:
    return [w.strip().strip("`").strip() for w in cell.split(",") if w.strip().strip("`").strip()]


def farm_words(ontology: Optional[str]) -> List[FarmWord]:
    """Every word of a `Farm word` column; a table without a Status column is in force."""
    found: List[FarmWord] = []
    section, header = "", None
    for line in (ontology or "").splitlines():
        if line.startswith("#"):
            section, header = line.lstrip("#").strip(), None
        elif not line.startswith("|"):
            header = None
        elif header is None:
            cells = [c.lower() for c in _cells(line)]
            header = cells if cells and cells[0] == "farm word" else []
        elif header and not re.fullmatch(r"[\s|:-]+", line):
            cells = _cells(line)
            status = cells[header.index("status")] if "status" in header and len(cells) > header.index("status") else "in force"
            stands = cells[1] if len(cells) > 1 else ""
            found.extend(FarmWord(w, stands, status, section) for w in _words(cells[0]))
    return found


_HEADING = re.compile(r"^(?:\*\*[^*]+\*\*(?:, )?)+:$")


def glossary_pairs(glossary: Optional[str]) -> List[Tuple[str, str]]:
    """The (old, new) of every glossary heading with two or more bold terms: `**shot**, **seed**:`."""
    found: List[Tuple[str, str]] = []
    for line in (glossary or "").splitlines():
        if _HEADING.match(line.strip()):
            terms = re.findall(r"\*\*([^*]+)\*\*", line)
            found.extend((terms[0], new) for new in terms[1:])
    return found


class Section(NamedTuple):
    title: str  # the heading without its parenthesis
    note: str  # the heading's parenthesis: "in force, synonyms"
    rows: List[dict]  # the rows of its tables, keyed by the lower-case column name
    lines: List[str]  # its other lines: bullets (with continuation lines joined) and prose


def ontology_sections(ontology: Optional[str]) -> List[Section]:
    """The `##` sections of the ontology as data: table rows and the other lines, nothing interpreted."""
    out: List[Section] = []
    header: Optional[List[str]] = None
    for line in (ontology or "").splitlines():
        if line.startswith("## "):
            title = line[3:].strip()
            m = re.match(r"(.*?)\s*\((.*)\)\s*$", title)
            out.append(Section(m.group(1) if m else title, m.group(2) if m else "", [], []))
            header = None
        elif not out or line.startswith("#"):
            continue
        elif line.startswith("|"):
            if header is None:
                header = [c.lower() for c in _cells(line)]
            elif not re.fullmatch(r"[\s|:-]+", line):
                out[-1].rows.append(dict(zip(header, _cells(line))))
        else:
            header = None
            text = line.strip()
            if not text:
                continue
            if line.startswith("  ") and out[-1].lines and out[-1].lines[-1].startswith("- "):
                out[-1].lines[-1] += " " + text
            else:
                out[-1].lines.append(text)
    return out


class Entry(NamedTuple):
    terms: List[str]
    text: str


def glossary_entries(glossary: Optional[str]) -> List[Entry]:
    """Every glossary entry: its bold terms (`**shot**, **seed**:`) and its paragraph up to the blank line."""
    found: List[Entry] = []
    lines = (glossary or "").splitlines()
    for i, line in enumerate(lines):
        if _HEADING.match(line.strip()):
            body: List[str] = []
            for nxt in lines[i + 1:]:
                if not nxt.strip():
                    break
                body.append(nxt.strip())
            found.append(Entry(re.findall(r"\*\*([^*]+)\*\*", line), " ".join(body)))
    return found


def _norm(term: str) -> str:
    return term.strip().strip("\"'`").lower()


def glossary_entry(glossary: Optional[str], term: str) -> Optional[Entry]:
    """The entry that has `term` among its terms, the second of a pair too."""
    return next((e for e in glossary_entries(glossary) if _norm(term) in [_norm(t) for t in e.terms]), None)


def ontology_mentions(ontology: Optional[str], term: str) -> List[Tuple[str, str]]:
    """(section, line or table row) of every place in the ontology that names `term` as a whole word."""
    pattern = re.compile(r"(?<![\w-])" + re.escape(_norm(term)) + r"(?![\w-])", re.IGNORECASE)
    found: List[Tuple[str, str]] = []
    for sec in ontology_sections(ontology):
        found.extend((sec.title, " | ".join(r.values())) for r in sec.rows if pattern.search(" | ".join(r.values())))
        found.extend((sec.title, l) for l in sec.lines if pattern.search(l))
    return found


def all_terms(glossary: Optional[str], ontology: Optional[str]) -> List[str]:
    """Every known term: the glossary's and the ontology's farm words."""
    terms = [t for e in glossary_entries(glossary) for t in e.terms]
    return sorted(set(terms) | {w.word for w in farm_words(ontology)})
