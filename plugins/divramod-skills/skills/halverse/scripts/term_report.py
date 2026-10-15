#!/usr/bin/env python3
"""The answers of `hal2-cli-halverse term ... --json`, worded (plan 0276, D15, D18, D22, D36).

A fit (`term check`), a proposal (a dry run: the exact lines per file, with the lines that give way), the report of a
write (every file changed with its lines, the backup, the check's counts, what VoiceInk got or why not) and the list of
short forms. Nothing here calls a program or writes a file; a proposal reads the lines that give way from the file the
CLI named, to show them. Python stdlib only.
"""
from typing import Any, Dict, List, Optional

import check
import cli
import voiceink

LIMIT = 25  # words or problems listed; the rest is counted
SESSIONS = ("Sessions that already run read the glossary at their start: they learn this after a clear "
            "(or when they are started again).")
KINDS = {
    "term": "heads a glossary entry",
    "synonym": "is a synonym in a glossary entry's head line",
    "avoid": "is an `_Avoid_` word of a glossary entry (a word not to use)",
    "word": "is an entry's word of another language",
    "ontology-term": "is a term of the ontology",
    "table-word": "is a word of an ontology word table",
    "short-form": "is a short form",
    "dictation-word": "is a word of DICTATION.md",
    "heard-form": "is a heard form of DICTATION.md (what the speech model writes for another word)",
    "orphan-head": "heads a companion's entry that no English entry has",
    "ontology-mention": "is named in the ontology's prose (a draft or todo name; read the line)",
    "repository-term": "heads an entry of a repository's own glossary",
    "repository-avoid": "is an `_Avoid_` word of a repository's own glossary",
}
FILES = {"glossary": "the glossary", "ontology": "the ontology", "dictation": "DICTATION.md"}
LANGUAGES = {"de": "German", "nl": "Dutch", "pt-PT": "Portuguese", "en": "English"}


def clash_line(files: Dict[str, Any], clash: Dict[str, Any]) -> str:
    where = clash.get("repository") or check.path_of(files, clash)
    lang = LANGUAGES.get(clash.get("word_lang") or "", "")
    section = ", section \"%s\"" % clash["section"] if clash.get("section") else ""
    return "    - \"%s\"%s %s: %s:%s%s" % (clash.get("word", "?"), " (%s)" % lang if lang else "",
                                         KINDS.get(clash.get("kind"), "is held as %s" % clash.get("kind")),
                                         where, clash.get("line", "?"), section)


def fit(data: Dict[str, Any]) -> str:
    """`term check`: per word free, or each thing that holds it with its file and line."""
    files, words = data.get("files") or {}, data.get("fit") or []
    repositories = data.get("repositories") or []
    out = ["halverse term check: %d word%s against the glossary, the ontology, DICTATION.md and their companions%s"
           % (len(words), "" if len(words) == 1 else "s",
              ", and the repository glossary %s" % ", ".join(str(r) for r in repositories) if repositories
              else " (no repository glossary)")]
    for word in words:
        clashes = word.get("clashes") or []
        if word.get("free"):
            out.append("  %s: free" % word.get("word", "?"))
            continue
        out.append("  %s: taken, %d clash%s" % (word.get("word", "?"), len(clashes), "" if len(clashes) == 1 else "es"))
        out += [clash_line(files, clash) for clash in clashes]
    return "\n".join(out)


def old_lines(path: str, first: int, last: int) -> Optional[List[str]]:
    """The lines `first..=last` of the file as it lies, to show what gives way; None when it cannot be read."""
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except (OSError, ValueError):
        return None
    return lines[first - 1:last] if 0 < first <= last <= len(lines) else None


def change_lines(path: str, change: Dict[str, Any], show_old: bool) -> List[str]:
    """One change: `line..=last` give way to `lines` (an insert: `last` is `line - 1`; a removal: no `lines`)."""
    first, last, new = change.get("line", 0), change.get("last", 0), change.get("lines") or []
    count = last - first + 1
    if count <= 0:
        head = "  insert before line %d:" % first
    elif new:
        head = "  replace line%s %s:" % ("" if count == 1 else "s", first if count == 1 else "%d-%d" % (first, last))
    else:
        head = "  remove line%s %s%s" % ("" if count == 1 else "s", first if count == 1 else "%d-%d" % (first, last),
                                         ":" if show_old else "")
    out = [head]
    if count > 0 and show_old:
        old = old_lines(path, first, last)
        out += ["    - " + line for line in old] if old is not None else ["    (the old lines could not be read)"]
    return out + ["    + " + line for line in new]


def files_lines(files: List[Dict[str, Any]], show_old: bool) -> List[str]:
    """Every file with its changes: its path, what it is, then the lines."""
    out: List[str] = []
    for item in files:
        what = FILES.get(item.get("file"), str(item.get("file")))
        lang = LANGUAGES.get(item.get("lang") or "")
        out.append("%s (%s%s)" % (item.get("path", "?"), what, ", " + lang if lang else ""))
        for change in item.get("changes") or []:
            out += change_lines(item.get("path", ""), change, show_old)
    return out


def remark_lines(data: Dict[str, Any]) -> List[str]:
    out = ["note: " + str(remark) for remark in data.get("remarks") or []]
    if data.get("recovered"):
        out.append("An earlier write that did not end was undone first; put back: " + voiceink.words(data["recovered"]))
    return out


def proposal(data: Dict[str, Any], number: str, write_call: str) -> str:
    """A dry run: nothing is written; the lines per file and the number the writing call must carry."""
    files = data.get("files") or []
    if not files:
        return "\n".join(["halverse proposal: nothing to write, the files say this already. Ask nothing, write nothing."]
                         + remark_lines(data))
    count = sum(len(item.get("changes") or []) for item in files)
    out = ["halverse proposal (a dry run, nothing is written): %d file%s, %d change%s"
           % (len(files), "" if len(files) == 1 else "s", count, "" if count == 1 else "s"), ""]
    out += files_lines(files, show_old=True)
    counts = data.get("check") or {}
    out += ["", "check of the files as they would be: %s errors, %s notes (no new error, or the dry run would refuse)"
            % (counts.get("errors", "?"), counts.get("notes", "?"))]
    out += remark_lines(data)
    out += ["", "proposal number: %s" % number,
            "Show these lines to the user in the Q form (write as shown, change something, do not write).",
            "Only on the user's yes: %s" % write_call]
    return "\n".join(out)


def voiceink_lines(sync: Dict[str, Any]) -> List[str]:
    """What VoiceInk got or why not (D36): the state, the words, and that the files stand whatever it says."""
    state, report = sync.get("state", "?"), sync.get("report") or {}
    plan = report.get("plan") or {}
    voc, rep = plan.get("vocabulary") or {}, plan.get("replacements") or {}
    if state == "synced":
        out = ["VoiceInk: synced, %d vocabulary words and %d replacements added, %d extended"
               % (len(voc.get("added") or []), len(rep.get("added") or []), len(rep.get("extended") or []))]
        if voc.get("added"):
            out.append("  vocabulary: " + voiceink.words(voc["added"], LIMIT))
        out += ["  + %s <- %s" % (r.get("word", "?"), voiceink.heard(r.get("heard"))) for r in (rep.get("added") or [])[:LIMIT]]
        out += ["  ~ %s <- %s (forms added)" % (r.get("word", "?"), voiceink.heard(r.get("heard_added")))
                for r in (rep.get("extended") or [])[:LIMIT]]
        if report.get("backup"):
            out.append("  backup of VoiceInk's store: %s (undo: /hv voiceink restore)" % report["backup"])
        return out
    if state == "nothing-to-add":
        return ["VoiceInk: nothing to add, it has the words already"]
    if state == "skipped":
        return ["VoiceInk: not synced" + (": %s" % sync["message"] if sync.get("message") else "")]
    out = ["VoiceInk: NOT synced (%s)" % state]
    out += ["  " + line for line in voiceink.state_advice(state, sync.get("message"))]
    return out + ["  The halverse files are written whatever VoiceInk says; `/hv voiceink` repeats the sync."]


def written(data: Dict[str, Any], differs: bool = False) -> str:
    """The report of a write: every file changed with its lines, the backup, the check's counts, VoiceInk."""
    files = data.get("files") or []
    if not data.get("written"):
        out = ["halverse write: nothing written, the files said this already"]
    else:
        out = ["halverse write: written, %d file%s" % (len(files), "" if len(files) == 1 else "s"), ""]
        out += files_lines(files, show_old=False)
    if differs:
        out += ["", "WARNING: these lines differ from the proposal the user confirmed: a file was changed between the "
                "proposal and the write. Show the user the lines above; the backup below holds the files as they were."]
    counts = data.get("check") or {}
    out += ["", "backup of the nine files as they were: %s" % (data.get("backup") or "none (nothing was written)"),
            "check of the files now: %s errors, %s notes (`/hv check` lists them)"
            % (counts.get("errors", "?"), counts.get("notes", "?"))]
    out += voiceink_lines(data.get("voiceink") or {}) + remark_lines(data)
    return "\n".join(out + ([SESSIONS] if data.get("written") else []))


def short_forms(data: Dict[str, Any]) -> str:
    """`term short list`: a line per short form, the words' first, then the farms'."""
    rows = data.get("short_forms") or []
    if not rows:
        return "halverse short forms: none yet (`/hv short <short> = <word>` sets one)"
    width = max(len(str(row.get("short", ""))) for row in rows)
    out = ["halverse short forms: %d" % len(rows)]
    for kind, title in (("word", "words"), ("farm", "farms (a project folder's name)")):
        own = [row for row in rows if row.get("kind") == kind]
        if own:
            out += ["", title + ":"] + cli.lines(["  %-*s  %s" % (width, row.get("short", "?"), row.get("stands_for", "?"))
                                                 for row in own], 200)
    return "\n".join(out)
