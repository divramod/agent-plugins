#!/usr/bin/env python3
"""`halverse.py add|change|retire|short`: one call of `hal2-cli-halverse term ... --json` each (plan 0276, D15, D18, D22).

The CLI's writer is the one writer of the nine halverse files (the glossary, the ontology, their companions,
DICTATION.md) and of the sync into VoiceInk; this module makes the calls and nothing here opens one of the files for
writing. A term's document goes to the CLI on its stdin (`--from -`).

- `check`: `term check <word>...`, with the current repository's own glossary.
- `propose`: the dry run of an add, a change or a retire. It prints the lines per file and a proposal number, made of
  the request (the document's bytes, or the retire's words) and of the lines shown.
- `write`: the writing call, made only with the number of that request's proposal (`--confirmed <number>`, which the
  skill passes after the user's yes). Without it, or with the number of another request, no call is made (exit 6); lines
  that differ from the shown ones are said in the report.
- `short_set`, `short_rm`: a short form is written at once (D22); `short_list` reads.

Python stdlib only.
"""
import hashlib
import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cli
import term_errors
import term_report

UNCONFIRMED = 6  # this script's own exit code: no writing call was made
Request = Tuple[List[str], Optional[str]]  # the CLI's arguments after `term`, and the document for its stdin


def repo_glossary(start: Optional[str] = None) -> Optional[str]:
    """The current repository's own GLOSSARY.md: of the nearest folder upward that holds `.git`, when it has one."""
    folder = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.exists(os.path.join(folder, ".git")):
            path = os.path.join(folder, "GLOSSARY.md")
            return path if os.path.isfile(path) else None
        parent = os.path.dirname(folder)
        if parent == folder:
            return None
        folder = parent


def answer(data: Dict[str, Any], as_json: bool, text: str, extra: Optional[Dict[str, Any]] = None) -> str:
    return json.dumps(dict(data, **(extra or {})), indent=2, ensure_ascii=False) if as_json else text


def check(words: Sequence[str], glossaries: Optional[Sequence[str]] = None, as_json: bool = False) -> Tuple[str, int]:
    """The fit's deterministic part: each word free, or what holds it. `glossaries`: repository glossaries to compare
    with too; None takes the current repository's."""
    if glossaries is None:
        own = repo_glossary()
        glossaries = [own] if own else []
    args = ["term", "check"] + list(words)
    for path in glossaries:
        args += ["--repo-glossary", path]
    try:
        data = cli.call(args)
    except cli.CliError as err:
        return term_errors.text(err), err.code
    return answer(data, as_json, term_report.fit(data)), 0


def show(term: str) -> Tuple[str, int]:
    """A term as the files have it, as data: its entry, its four languages, its places, its short forms."""
    try:
        data = cli.call(["terms"])
    except cli.CliError as err:
        return err.text, err.code
    want = " ".join(term.lower().split())
    for item in data.get("terms") or []:
        if want in [str(name).lower() for name in [item.get("term")] + list(item.get("synonyms") or [])]:
            return json.dumps(item, indent=2, ensure_ascii=False), 0
    return "The halverse files have no term \"%s\" (`/hv ontology %s` names the closest ones)." % (term, term), 1


def read_document(source: str) -> str:
    """The document of `--from <file>`, or of stdin for `-`. Raises CliError (exit 2) when it cannot be read."""
    try:
        if source == "-":
            return sys.stdin.read()
        with open(source, encoding="utf-8") as handle:
            return handle.read()
    except (OSError, ValueError) as exc:
        raise cli.CliError("The term's document %s cannot be read: %s" % (source, exc), 2)


def document_request(kind: str, source: str) -> Request:
    return ["term", kind, "--from", "-"], read_document(source)


def retire_request(term: str, successor: Optional[str]) -> Request:
    return ["term", "retire", term] + (["--by", successor] if successor else []), None


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:8]


def request_key(request: Request) -> str:
    return _hash([request[0], request[1]])


def lines_key(files: Any) -> str:
    """The lines a call writes, without their line numbers (an edit above moves them and changes nothing else)."""
    return _hash([[item.get("file"), item.get("lang"), [change.get("lines") or [] for change in item.get("changes") or []]]
                  for item in files or []])


def number_of(request: Request, files: Any) -> str:
    return "%s-%s" % (request_key(request), lines_key(files))


def propose(request: Request, write_call: str, as_json: bool = False) -> Tuple[str, int]:
    """The dry run: nothing is written and no store is opened; the lines per file and the proposal number."""
    args, document = request
    try:
        data = cli.call(args + ["--dry-run"], stdin=document)
    except cli.CliError as err:
        return term_errors.text(err), err.code
    number = number_of(request, data.get("files"))
    call = "%s --confirmed %s" % (write_call, number)
    return answer(data, as_json, term_report.proposal(data, number, call), {"proposal": number}), 0


def write(request: Request, confirmed: Optional[str], as_json: bool = False) -> Tuple[str, int]:
    """The one writing call, made only with the number of this request's proposal."""
    if not confirmed:
        return ("No writing call was made: a write needs `--confirmed <proposal number>`, the number the proposal "
                "printed, passed only after the user said yes to the lines it showed. Run the proposal, ask in the Q "
                "form, then write."), UNCONFIRMED
    if confirmed.split("-")[0] != request_key(request):
        return ("No writing call was made: the proposal number %s is not this request's. The document (or the words "
                "of the call) changed since the proposal the user confirmed. Run the proposal again, show its lines "
                "and ask again." % confirmed), UNCONFIRMED
    args, document = request
    try:
        data = cli.call(args, stdin=document)
    except cli.CliError as err:
        return term_errors.text(err), err.code
    differs = bool(data.get("written")) and number_of(request, data.get("files")) != confirmed
    return answer(data, as_json, term_report.written(data, differs), {"differs_from_proposal": differs}), 0


def short_list(as_json: bool = False) -> Tuple[str, int]:
    try:
        data = cli.call(["term", "short", "list"])
    except cli.CliError as err:
        return term_errors.text(err), err.code
    return answer(data, as_json, term_report.short_forms(data)), 0


def short_set(short: str, word: str, farm: bool = False, spoken: bool = False, as_json: bool = False) -> Tuple[str, int]:
    """A short form for a word (`farm`: for a farm, the project folder's name; `spoken`: also a heard form, D10)."""
    args = ["term", "short", "set", short, word] + (["--farm"] if farm else []) + (["--spoken"] if spoken else [])
    return _short(args, as_json)


def short_rm(short: str, as_json: bool = False) -> Tuple[str, int]:
    return _short(["term", "short", "rm", short], as_json)


def _short(args: List[str], as_json: bool) -> Tuple[str, int]:
    try:
        data = cli.call(args)
    except cli.CliError as err:
        return term_errors.text(err), err.code
    return answer(data, as_json, term_report.written(data)), 0
