#!/usr/bin/env python3
"""`halverse.py ontology [<term>]`: shapes the output only (plan 0270, D3, D15).

All parsing of the user's two source files is in sources.py; this module calls it and prints. Without a term: the
ontology's sections as data. With a term: its glossary entry, the ontology lines naming it and its pair of
`pairs.json` (old word, command). Python stdlib only.
"""
import difflib
import json
import re
from typing import Optional, Tuple

import learn
import sources


def _status(section: sources.Section, row: Optional[dict]) -> str:
    return (row or {}).get("status") or section.note


def overview(glossary: Optional[str], ontology: Optional[str]) -> dict:
    sections = []
    for sec in sources.ontology_sections(ontology):
        sections.append({"title": sec.title, "status": sec.note,
                         "rows": [dict(r, status=_status(sec, r)) for r in sec.rows], "lines": sec.lines})
    return {"sections": sections, "glossary_terms": [e.terms for e in sources.glossary_entries(glossary)]}


def pair_of(term: str) -> Optional[dict]:
    want = sources._norm(term)
    for p in learn.load_pairs().pairs:
        if want == p.new or any(re.fullmatch(f, want, re.IGNORECASE) for f in p.old + p.new_forms):
            return {"new": p.new, "old": p.old_label, "command": p.command, "since": p.since}
    return None


def lookup(glossary: Optional[str], ontology: Optional[str], term: str) -> Tuple[dict, bool]:
    """(the data about the term, whether anything is known of it)."""
    entry = sources.glossary_entry(glossary, term)
    mentions = sources.ontology_mentions(ontology, term)
    pair = pair_of(term)
    data = {"term": term,
            "glossary": {"terms": entry.terms, "text": entry.text} if entry else None,
            "ontology": [{"section": s, "line": l} for s, l in mentions], "pair": pair}
    if not (entry or mentions or pair):
        data["closest"] = difflib.get_close_matches(sources._norm(term), [t.lower() for t in sources.all_terms(glossary, ontology)], 5, 0.5)
    return data, bool(entry or mentions or pair)


def render_overview(data: dict) -> str:
    out = ["halverse ontology: %d sections" % len(data["sections"])]
    for sec in data["sections"]:
        out += ["", "## %s%s" % (sec["title"], " (%s)" % sec["status"] if sec["status"] else "")]
        for r in sec["rows"]:
            cells = " | ".join(str(v) for k, v in r.items() if k != "status")
            out.append("- %s%s" % (cells, " [%s]" % r["status"] if r["status"] else ""))
        out += ["- " + l.lstrip("- ") for l in sec["lines"]]
    return "\n".join(out)


def render_term(data: dict) -> str:
    out = ["halverse ontology: %s" % data["term"]]
    if data["glossary"]:
        out += ["", "glossary (%s): %s" % (", ".join(data["glossary"]["terms"]), data["glossary"]["text"])]
    for m in data["ontology"]:
        out.append("ontology, %s: %s" % (m["section"], m["line"]))
    if data["pair"]:
        p = data["pair"]
        out.append("old word: %s; farm word: %s since %s; command: %s" % (p["old"], p["new"], p["since"], p["command"] or "none"))
    return "\n".join(out)


def run(term: Optional[str], as_json: bool) -> Tuple[str, int]:
    """(the output, the exit code): 2 a missing source file (named), 1 an unknown term."""
    texts = {"glossary": sources.read_text(sources.glossary_path()), "ontology": sources.read_text(sources.ontology_path())}
    paths = {"glossary": sources.glossary_path(), "ontology": sources.ontology_path()}
    missing = [paths[k] for k, v in texts.items() if v is None]
    if missing:
        return "halverse: missing source file: " + ", ".join(missing), 2
    if term is None:
        data = overview(texts["glossary"], texts["ontology"])
        return (json.dumps(data, indent=2, ensure_ascii=False) if as_json else render_overview(data)), 0
    data, known = lookup(texts["glossary"], texts["ontology"], term)
    if as_json:
        return json.dumps(data, indent=2, ensure_ascii=False), 0 if known else 1
    if known:
        return render_term(data), 0
    close = data.get("closest") or []
    return 'halverse: unknown term "%s"%s' % (term, "; closest: " + ", ".join(close) if close else ""), 1
