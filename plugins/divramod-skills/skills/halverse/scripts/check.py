#!/usr/bin/env python3
"""`halverse.py check [--json]`: the CLI's check of the halverse files, worded (plan 0276, D37).

One call of `hal2-cli-halverse check --json` (the errors, the notes) and one of `terms --json` (which term is untranslated
in which language: a word, a description or a row of the ontology is the English fallback). The report gives counts and
at most 25 lines each. The CLI is the one checker; nothing here reads a file. Python stdlib only.
"""
import json
from typing import Any, Dict, List, Tuple

import cli

LIMIT = 25  # lines per part of the report; the rest is counted
LANGUAGES = (("de", "German"), ("nl", "Dutch"), ("pt-PT", "Portuguese"))


def path_of(files: Dict[str, Any], item: Dict[str, Any]) -> str:
    """The file a problem is in: a companion's path where it has a language, else the English file's."""
    name = item.get("file", "")
    lang = item.get("lang")
    own = ((files.get("companions") or {}).get(lang) or {}).get(name) if lang else None
    return own or files.get(name) or name


def problem_line(files: Dict[str, Any], item: Dict[str, Any]) -> str:
    where = path_of(files, item) + (":%d" % item["line"] if item.get("line") else "")
    return "  - %s: %s (%s)" % (where, item.get("message", ""), item.get("rule", "?"))


def untranslated(terms: Dict[str, Any]) -> Dict[str, List[str]]:
    """Per language, the terms whose word, description or ontology row is the English one (`languages.<l>.untranslated`)."""
    found: Dict[str, List[str]] = {lang: [] for lang, _ in LANGUAGES}
    for term in terms.get("terms", []):
        for lang in found:
            if ((term.get("languages") or {}).get(lang) or {}).get("untranslated"):
                found[lang].append(term["term"])
    return found


def report(check: Dict[str, Any], terms: Dict[str, Any]) -> str:
    files = check.get("files") or {}
    problems = check.get("problems") or []
    errors = [p for p in problems if p.get("severity") != "note"]
    notes = [p for p in problems if p.get("severity") == "note"]
    out = ["halverse check: " + ("ok, " if check.get("ok") else "") + "%d errors, %d notes" % (len(errors), len(notes))]
    for title, items in (("errors", errors), ("notes", notes)):
        if items:
            out += ["", "%s (%d):" % (title, len(items))] + cli.lines([problem_line(files, p) for p in items], LIMIT)
    total = len(terms.get("terms", []))
    out += ["", "untranslated (the English text stands), of %d terms:" % total]
    missing = untranslated(terms)
    for lang, label in LANGUAGES:
        names = missing[lang]
        shown = ", ".join(names[:LIMIT]) + (" and %d more" % (len(names) - LIMIT) if len(names) > LIMIT else "")
        out.append("  %s: %s" % (label, "%d, %s" % (len(names), shown) if names else "none"))
    return "\n".join(out)


def run(as_json: bool = False) -> Tuple[str, int]:
    """(the report, the exit code): the CLI's 0 or 1 (an error found), 2 the CLI missing or a file it cannot read (named)."""
    try:
        check = cli.call(["check"], ok=(0, 1))
        terms = cli.call(["terms"])
    except cli.CliError as err:
        return err.text, err.code
    if as_json:
        return json.dumps(dict(check, untranslated=untranslated(terms)), indent=2, ensure_ascii=False), 0 if check.get("ok") else 1
    return report(check, terms), 0 if check.get("ok") else 1
