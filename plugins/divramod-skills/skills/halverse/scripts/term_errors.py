#!/usr/bin/env python3
"""A refusal of `hal2-cli-halverse term ...`, worded (plan 0276, D15, D53, D54).

The CLI's error is `{code, message, detail}` and its exit code says the kind: 2 a wrong call or a file that cannot be
read, 3 refused (nothing written), 4 a file changed meanwhile or the lock is held, 5 the write did not go through. Per
code one advice, then the CLI's own message and what its detail names: the field, the file and the line that refused,
the problems a write would cause, the lines of a refused dry run, what was undone, and what an interrupted earlier write
left or had put back. Python stdlib only.
"""
from typing import Any, Dict, List

import cli
import term_report
import voiceink

AGAIN = "Change the document and run the proposal again."
ADVICE = {
    "usage": "The call was wrong: a fault of this skill's script or of its arguments, not of the files. Nothing was written.",
    "unreadable": "A file cannot be read (named below), so nothing was compared and nothing was written. See that it "
                  "exists and can be read, then call again.",
    "invalid-draft": "The document is refused, field by field (below). Nothing was written. " + AGAIN,
    "missing-field": "The document lacks a field this call needs (named below). Nothing was written. " + AGAIN,
    "no-section": "The glossary has no section of that title. Name the section as the English glossary's `## ` heading "
                  "writes it. Nothing was written.",
    "no-entry": "The glossary has no entry of that term, so there is nothing to change or retire (`/hv ontology <term>` "
                "finds how a term is written, `/hv add` adds a new one). Nothing was written.",
    "term-exists": "The term heads a glossary entry already (the line below): it cannot be added again. `/hv change "
                   "<term>` changes it. Nothing was written.",
    "section-differs": "The entry stands in another section than the document names, and a change does not move an "
                       "entry. Leave `section` out or name the entry's own. Nothing was written.",
    "unreadable-entry": "The entry or row at the place below is written in a way the writer cannot change safely. It "
                        "must be put right by hand first (`/hv check` names what is wrong). Nothing was written.",
    "no-ontology-section": "The ontology has no section of that title (the title without its parenthesis). Nothing was "
                           "written. " + AGAIN,
    "no-table": "That section of the ontology has no table the row fits; where it has several, the document names one "
                "by its `header`. Nothing was written. " + AGAIN,
    "no-place": "The ontology has no row or bullet of that term in that section. Leave `ontology` out, or name the "
                "place as it stands. Nothing was written.",
    "place-exists": "The ontology has that row or bullet already (the line below). Nothing was written. " + AGAIN,
    "draft-unfit": "A field does not fit the file it goes into (below). Nothing was written. " + AGAIN,
    "shared-row": "The ontology's row is shared by several terms and the document would change more than this term's "
                  "part (the place below). Give this term's part of a cell that pairs and leave the other cells as "
                  "they stand. Nothing was written.",
    "unpaired-row": "A row of a word table names several English words and not as many words beside them (the place "
                    "below), so the writer cannot tell which is this term's. The row must be put right by hand first. "
                    "Nothing was written.",
    "no-short-form": "The glossary has no such short form (`/hv short` lists them). Nothing was written.",
    "short-form-in-other-table": "That short form stands in the other table already: a word's short form cannot become "
                                 "a farm's, nor a farm's a word's. Remove it first (`/hv short rm <short>`) or choose "
                                 "another. Nothing was written.",
    "spoken-form-refused": "The short form cannot be spoken to VoiceInk (the rule below): one letter is never a heard "
                           "form, nor is a term, a word or another word's form. Set it without `--spoken` or choose "
                           "another. Nothing was written.",
    "short-form-stands": "A short form still stands for the term (below), so it cannot go without a successor. Name "
                         "the successor (`/hv retire <term> by <term>`) or remove the short form first (`/hv short rm "
                         "<short>`). Nothing was written.",
    "planner-fault": "The writer could not plan the change: a fault of hal2, not of the document. Nothing was written. "
                     "Send the CLI's message below to the farmer.",
    "refused": "Nothing was written: the files would get errors they do not have now, or the change would touch "
               "something the request does not name (the problems below).",
    "not-utf8": "A file is not UTF-8 text (named below), so the writer does not touch it. Nothing was written.",
    "changed-meanwhile": "A file was saved by someone else while the write ran (named below), so the write stopped "
                         "and undid itself. Make the proposal again on the files as they are now, and ask again.",
    "locked": "Another write of the halverse files holds the lock (another session's `/hv`). Nothing was written. Call "
              "again in a moment with the same proposal number.",
    "failed": "The write did not go through. Below is what was put back and what was not; the next call first undoes "
              "what an interrupted write left. Tell the farmer if a file was left or could not be put back.",
}
RULES = {"changed-unnamed": "the change would alter something the request does not name: a fault of the writer's "
                            "plan, send it to the farmer"}


def where(detail: Dict[str, Any]) -> str:
    """The file and line a detail names: `path:line`, or the file's name and language where it gives no path."""
    if detail.get("path"):
        return "%s%s" % (detail["path"], ":%s" % detail["line"] if detail.get("line") else "")
    lang = term_report.LANGUAGES.get(detail.get("lang") or "")
    name = term_report.FILES.get(detail.get("file"), str(detail.get("file"))) + (" (%s)" % lang if lang else "")
    return "%s%s" % (name, ", line %s" % detail["line"] if detail.get("line") else "")


def problem_line(item: Dict[str, Any]) -> str:
    rule = item.get("rule", "?")
    return "  - %s: %s (%s%s)" % (where(item), item.get("message", ""), rule, "; " + RULES[rule] if rule in RULES else "")


def undone_lines(undone: Dict[str, Any]) -> List[str]:
    out = []
    for key, text in (("put_back", "put back, as before the write"),
                      ("left", "LEFT as they are: someone saved them since, and they still hold a part of the write"),
                      ("failed", "could NOT be put back: the next call tries again before anything else")):
        if undone.get(key):
            out.append("  %s: %s" % (text, voiceink.words(undone[key])))
    if undone.get("journal"):
        out.append("  the writer's journal could not be removed (%s); the next call removes it" % undone["journal"])
    return out or ["  no file had been replaced: the files are as they were"]


def place_lines(detail: Dict[str, Any]) -> List[str]:
    """What a planner's refusal names: a field, a term, a short form, a place in a file."""
    out = ["  - `%s` %s" % (r.get("field", "?"), r.get("reason", "")) for r in detail.get("reasons") or []]
    if detail.get("field"):
        out.append("  field `%s`%s" % (detail["field"], ": " + detail["why"] if detail.get("why") else ""))
    named = ["%s \"%s\"" % (label, detail[key]) for key, label in
             (("term", "term"), ("short", "short form"), ("form", "form"), ("table", "table"), ("rule", "rule")) if detail.get(key)]
    if named:
        out.append("  " + ", ".join(named))
    if detail.get("file") or detail.get("path") or detail.get("line"):
        out.append("  at %s" % (where(detail) if detail.get("file") or detail.get("path") else "line %s" % detail["line"]))
    if detail.get("waited_ms") is not None:
        out.append("  waited %s ms for the lock" % detail["waited_ms"])
    return out


def detail_lines(detail: Dict[str, Any]) -> List[str]:
    out = place_lines(detail)
    problems = detail.get("problems") or []
    if problems:
        out += ["problems the write would cause (%d):" % len(problems)] + cli.lines([problem_line(p) for p in problems], 25)
    if detail.get("files"):
        out += ["the lines that would cause them:"] + ["  " + line for line in term_report.files_lines(detail["files"], False)]
    if isinstance(detail.get("undone"), dict):
        out += ["the undo:"] + undone_lines(detail["undone"])
    if detail.get("recovered"):
        out.append("Before this error an earlier write that did not end was undone; put back: " + voiceink.words(detail["recovered"]))
    if detail.get("unrecovered"):
        out.append("An earlier write did not end; these files still hold its text, and the next write puts them back "
                   "first: " + voiceink.words(detail["unrecovered"]))
    return out


def text(err: cli.CliError) -> str:
    """The error for the user: the advice for its code, the CLI's message, what its detail names."""
    error = err.error
    if not isinstance(error, dict):
        return err.text  # the CLI is missing, gave no answer or one that cannot be read
    code = error.get("code", "?")
    detail = error.get("detail") if isinstance(error.get("detail"), dict) else {}
    out = ["halverse term: %s (exit %d)" % (code, err.code),
           ADVICE.get(code, "hal2-cli-halverse stopped with an error this skill has no advice for. Nothing is known to be written.")]
    if error.get("message"):
        out.append("CLI message: %s" % error["message"])
    return "\n".join(out + detail_lines(detail))
