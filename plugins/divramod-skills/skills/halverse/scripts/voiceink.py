#!/usr/bin/env python3
"""halverse voiceink: one call of `hal2-cli-voiceink <sync|status|restore|export> --json`, reported in short plain words (plan 0273, D9, D15).

The CLI (apps/hal2-cli-voiceink) does the work and owns the JSON contract (D15). This script keeps its exit codes: 0
done, 2 usage, 3 no store, 4 unknown schema, 5 store unavailable, 6 write failed (backup put back), 7 no backup. The CLI
said so itself before plan 0318; since then it answers in the common table (3 not found, 4 refused, 5 busy, 1 failed),
with the error `{code, exit, message, hint, details}` on stderr and its old code in `details.reason` (a store's state
`busy`, `app-running`, `failed` in `details.why`); this module reads both and tells the codes above. It only runs
it and words the answer; `export` writes VoiceInk's import file and opens no store (plan 0276, D20). The one writer is
the CLI; nothing here opens VoiceInk's store. Python stdlib only.
"""
import json
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

import cli as halverse_cli

CLI = "hal2-cli-voiceink"
CLI_ENV = "HAL2_CLI_VOICEINK"  # a path overriding the lookup on PATH (tests, a field's build)
INSTALL = "cargo install --path apps/hal2-cli-voiceink   (run in the hal2 repository's code/rust folder)"
TIMEOUT = 120
LIST_MAX = 25  # words listed per line of the report; the rest is counted

REASONS = {
    "other-word": "the wrong form already points to another word",
    "overlap": "it overlaps another entry (a whole-word part of it, or it contains one)",
    "in-replacement": "it occurs in an entry's replacement text (also its own word, differing only by case)",
    "unsafe-character": "the word holds a $ or a backslash, which VoiceInk reads as a pattern",
    "empty": "it is empty",
    "comma": "it holds a comma, which VoiceInk reads as two forms",
}

ADVICE = {
    "usage": "The call was wrong. Run `hal2-cli-voiceink --help` for its flags.",
    "no-store": "VoiceInk's store was not found: VoiceInk is not installed, was never opened, or this is not a Mac "
                "(VoiceInk exists on macOS only). Install VoiceInk, open it once, then call /hv voiceink again.",
    "unknown-schema": "VoiceInk's store has a schema this tool does not know, so VoiceInk was probably updated. "
                      "Nothing was written. Until the sync knows that version, `/hv voiceink export` writes the words "
                      "as a file that VoiceInk's \"Import Dictionary\" reads. Tell the farmer or the halverse plan's "
                      "foreman; the sync is verified only against the versions named below.",
    "unwritable": "The import file could not be written. See that its folder exists and can be written, or name "
                  "another file: `/hv voiceink export --out <file>`.",
    "no-backup": "There is no backup to restore. A backup exists only after a sync that changed something "
                 "(`/hv voiceink restore --list` shows them).",
}


def usage_advice(detail: Dict[str, Any]) -> str:
    """By D21's `detail`: `{file, path}` is a source file that cannot be read, anything else a wrong call."""
    if detail.get("file") or detail.get("path"):
        return ("The %s file %s cannot be read, so nothing was compared and nothing was written. See that the file "
                "exists and can be read, then call /hv voiceink again."
                % (detail.get("file") or "source", detail.get("path") or "named in the CLI's message"))
    return ADVICE["usage"]


def unavailable_advice(detail: Dict[str, Any]) -> str:
    """By D21's `detail.reason`: a sync never needs VoiceInk quit (`busy`), only a restore does (`app-running`)."""
    reason = detail.get("reason")
    if reason == "app-running":
        return ("VoiceInk is running, and a backup is only put back while it is not. Quit VoiceInk (Cmd+Q in VoiceInk), "
                "then call /hv voiceink restore again. Nothing was changed.")
    if reason == "busy":
        return ("VoiceInk's store is busy: another program holds its lock right now. Nothing was written. Call "
                "/hv voiceink again in a moment; VoiceInk does not have to be quit for a sync.")
    return ("VoiceInk's store could not be read or written now. Nothing was written. Call /hv voiceink again; if it "
            "fails again, send the CLI's message below to the farmer.")


def write_failed_advice(detail: Dict[str, Any]) -> str:
    """What the write left behind, by D17's detail: rolled back, backup put back, or committed with the backup not put back."""
    if detail.get("restored") is True:
        return ("The write failed and the backup was put back, so VoiceInk's store is as it was. Nothing changed. "
                "Call /hv voiceink again; if it fails again, send the CLI's message below to the farmer.")
    if detail.get("written") is False:
        return ("The write failed and was rolled back: nothing was written, VoiceInk's store is as it was. "
                "Call /hv voiceink again; if it fails again, send the CLI's message below to the farmer.")
    backup = detail.get("backup")
    return ("The write may have reached VoiceInk's store and the backup was NOT put back (it is only put back while "
            "VoiceInk is not running). The backup%s holds the store as it was. Quit VoiceInk (Cmd+Q in VoiceInk), "
            "then call `/hv voiceink restore` to put it back, and tell the farmer." % (" " + str(backup) if backup else ""))


def state_advice(state: str, message: Optional[str]) -> List[str]:
    """A failed sync as another command reports it (`hal2-cli-halverse term`: `voiceink.state` is this CLI's error
    code, `message` its text, and there is no detail): the advice for that code, then the CLI's message."""
    if state == "write-failed":
        out = ["The write into VoiceInk's store failed. The CLI's message below says whether anything was written and "
               "whether the backup was put back; if the store is not as it was, quit VoiceInk and call "
               "`/hv voiceink restore`."]
    elif state == "store-unavailable":
        out = [unavailable_advice({})]
    else:
        out = [ADVICE.get(state, "hal2-cli-voiceink stopped with the error \"%s\"." % state)]
    return out + (["CLI message: %s" % message] if message else [])


def find_cli() -> Optional[str]:
    override = os.environ.get(CLI_ENV)
    if override:
        return override if os.path.isfile(override) and os.access(override, os.X_OK) else None
    return shutil.which(CLI)


def missing_cli() -> Tuple[str, int]:
    return ("hal2-cli-voiceink is not installed (or not on PATH).\n"
            "Install it from the hal2 repository's code/rust folder:\n  %s\n"
            "Then call /hv voiceink again." % INSTALL), 2


def call(args: List[str]) -> Tuple[Optional[Dict[str, Any]], int, str]:
    """(parsed JSON or None, the CLI's exit code, its raw output). The CLI must exist."""
    cli = find_cli()
    try:
        done = subprocess.run([cli] + args + ["--json"], capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, 1, "no answer within %d seconds" % TIMEOUT
    raw = done.stdout.strip() or done.stderr.strip()
    try:
        data = json.loads(done.stdout) if done.stdout.strip() else json.loads(done.stderr)
    except ValueError:
        data = None
    return (data if isinstance(data, dict) else None), done.returncode, raw


# The script's exit code per error code, for an answer in the contract's shape (the old shape carried its own).
SCRIPT_EXIT = {"usage": 2, "unreadable": 2, "unwritable": 2, "no-store": 3, "unknown-schema": 4, "store-unavailable": 5,
               "write-failed": 6, "no-backup": 7}


def script_exit(data: Optional[Dict[str, Any]], code: int) -> int:
    """The exit code to tell: the CLI's, or for the contract's error the one `SCRIPT_EXIT` names for its old code."""
    err = halverse_cli.normalize_error((data or {}).get("error"))
    if err and err.get("exit") is not None:
        return SCRIPT_EXIT.get(err.get("code"), code or 1)
    return code


def words(items: Any, limit: int = LIST_MAX) -> str:
    items = [str(i) for i in (items or [])]
    shown = ", ".join(items[:limit])
    return shown + (" and %d more" % (len(items) - limit) if len(items) > limit else "")


def heard(value: Any) -> str:
    return words(value) if isinstance(value, list) else str(value)


def problem(item: Any) -> str:
    """One problem of the source files as the halverse CLI gives it: `{file, line, message, rule, severity}`."""
    if isinstance(item, dict) and item.get("message"):
        where = " ".join(str(p) for p in (item.get("file"), "line %s" % item["line"] if item.get("line") else None) if p)
        return "%s%s" % (where + ": " if where else "", item["message"])
    return item if isinstance(item, str) else json.dumps(item, ensure_ascii=False, sort_keys=True)


def problem_lines(problems: List[Any]) -> List[str]:
    """Errors leave their rows out; notes (`severity: note`) are for the files' author and leave the sync as it is."""
    notes = [p for p in problems if isinstance(p, dict) and p.get("severity") == "note"]
    errors = [p for p in problems if p not in notes]
    out = []
    if errors:
        out.append("problems in the source files (%d), their rows were left out:" % len(errors))
        out += ["  - " + problem(p) for p in errors[:LIST_MAX]]
    if notes:
        out.append("notes on the source files (%d), nothing to do for the sync:" % len(notes))
        out += ["  - " + problem(p) for p in notes[:LIST_MAX]]
    return out


def problem_counts(problems: List[Any]) -> List[str]:
    """One line for a call that only reads the word list: how many problems the source files have, not each."""
    notes = [p for p in problems if isinstance(p, dict) and p.get("severity") == "note"]
    errors = len(problems) - len(notes)
    if not problems:
        return []
    return ["the source files have %d error%s%s and %d note%s: `/hv check` lists them"
            % (errors, "" if errors == 1 else "s", " (their rows are left out)" if errors else "", len(notes),
               "" if len(notes) == 1 else "s")]


def left_out_lines(voc: Dict[str, Any]) -> List[str]:
    return ["  left out: \"%s\" (%s)" % (r.get("word", ""), REASONS.get(r.get("reason"), str(r.get("reason"))))
            for r in (voc.get("refused") or []) if isinstance(r, dict)]


def refused_lines(refused: List[Dict[str, Any]]) -> List[str]:
    out = ["refused (%d), not written:" % len(refused)]
    for r in refused:
        why = REASONS.get(r.get("reason"), str(r.get("reason")))
        detail = r.get("detail")
        out.append("  - \"%s\" for \"%s\": %s%s" % (heard(r.get("heard", "")), r.get("word", "?"), why,
                                                    " (%s)" % problem(detail) if detail else ""))
    return out


def error_text(data: Optional[Dict[str, Any]], code: int, raw: str) -> str:
    err = halverse_cli.normalize_error((data or {}).get("error")) if data else None
    if not isinstance(err, dict):
        return "hal2-cli-voiceink failed with exit code %d and an output this skill cannot read:\n%s" % (code, raw[:600])
    kind = err.get("code", "?")
    detail = err.get("detail") or {}
    if kind == "store-unavailable" and "why" in detail:  # the contract's shape: `reason` is the code, the state `why`
        detail = dict(detail, reason=detail["why"])
    if kind == "write-failed":
        out = [write_failed_advice(detail)]
    elif kind == "store-unavailable":
        out = [unavailable_advice(detail)]
    elif kind in ("usage", "unreadable"):
        out = [usage_advice(detail)]
    else:
        out = [ADVICE.get(kind, "hal2-cli-voiceink stopped with the error \"%s\"." % kind)]
    if kind == "unknown-schema":
        versions = detail.get("versions_verified") or detail.get("verified")
        out.append("Verified VoiceInk versions: %s." % (words(versions) if versions else "named in the CLI's message"))
        if detail.get("found") or detail.get("version"):
            out.append("This store: %s." % (detail.get("found") or detail.get("version")))
    if err.get("message"):
        out.append("CLI message: %s" % err["message"])
    return "\n".join(out)


def sync_report(data: Dict[str, Any]) -> str:
    voc, rep = data.get("vocabulary") or {}, data.get("replacements") or {}
    added, ext, refused = rep.get("added") or [], rep.get("extended") or [], rep.get("refused") or []
    if data.get("dry_run"):
        head = "VoiceInk sync, dry run: nothing written" + (", this would change the store" if data.get("changed") else ", nothing to add")
    else:
        head = "VoiceInk sync: " + ("written" if data.get("changed") else "nothing to add, nothing written")
    out = [head, ""]
    out.append("vocabulary: %d added, %d there already" % (len(voc.get("added") or []), voc.get("present") or 0))
    if voc.get("added"):
        out.append("  added: " + words(voc["added"]))
    out += left_out_lines(voc)
    out.append("replacements: %d added, %d extended, %d there already" % (len(added), len(ext), rep.get("present") or 0))
    out += ["  + %s <- %s" % (r.get("word", "?"), heard(r.get("heard"))) for r in added[:LIST_MAX]]
    out += ["  ~ %s <- %s (forms added)" % (r.get("word", "?"), heard(r.get("heard_added"))) for r in ext[:LIST_MAX]]
    if len(added) + len(ext) > LIST_MAX:
        out.append("  ... the rest is counted above, `/hv voiceink --json` lists all")
    if refused:
        out += refused_lines(refused)
    out += problem_lines(data.get("problems") or [])
    if data.get("backup"):
        out += ["", "backup: %s" % data["backup"], "undo: /hv voiceink restore"]
    elif data.get("changed") is False:
        out += ["", "no backup made: nothing was written"]
    return "\n".join(out)


def status_report(data: Dict[str, Any]) -> str:
    store, voc, rep = data.get("store") or {}, data.get("vocabulary") or {}, data.get("replacements") or {}
    missing, refused = rep.get("missing") or [], rep.get("refused") or []
    out = ["VoiceInk status (nothing written)", ""]
    out.append("store: %s (%s)" % (store.get("path", "?"), "found" if store.get("found") else "not found"))
    out.append("schema: " + ("known" if store.get("schema_ok") else "NOT verified, a sync would refuse")
               + ("; verified versions: " + words(store.get("versions_verified")) if store.get("versions_verified") else ""))
    out.append("vocabulary: %d wanted, %d there, %d missing" % (voc.get("wanted") or 0, voc.get("present") or 0, len(voc.get("missing") or [])))
    if voc.get("missing"):
        out.append("  missing: " + words(voc["missing"]))
    out += left_out_lines(voc)
    out.append("replacements: %d wanted, %d there, %d missing" % (rep.get("wanted") or 0, rep.get("present") or 0, len(missing)))
    out += ["  + %s <- %s" % (r.get("word", "?"), heard(r.get("heard"))) for r in missing[:LIST_MAX]]
    if len(missing) > LIST_MAX:
        out.append("  ... and %d more" % (len(missing) - LIST_MAX))
    if refused:
        out += refused_lines(refused)
    out += problem_lines(data.get("problems") or [])
    todo = len(voc.get("missing") or []) + len(missing)
    out += ["", "/hv voiceink adds the missing ones." if todo else "Nothing to add: VoiceInk has everything wanted."]
    return "\n".join(out)


def restore_report(data: Dict[str, Any]) -> str:
    if "backups" in data:
        rows = data["backups"] or []
        if not rows:
            return "no backups yet (a sync that changes something makes one)"
        return "\n".join(["backups, newest first (/hv voiceink restore <path> puts one back):"]
                         + ["  %s  %s  %s bytes" % (b.get("created", "?"), b.get("path", "?"), b.get("bytes", "?")) for b in rows])
    before = "\nthe store as it was before the restore is kept: %s" % data["before"] if data.get("before") else ""
    return "restored %s\ninto %s%s\nOpen VoiceInk again." % (data.get("restored", "?"), data.get("store", "?"), before)


def export_report(data: Dict[str, Any]) -> str:
    out = ["VoiceInk's import file is written: %s" % data.get("file", "?"),
           "it holds %s vocabulary words and %s replacements; VoiceInk's store was not opened"
           % (data.get("vocabulary", "?"), data.get("replacements", "?")),
           "Import it in VoiceInk with its own \"Import Dictionary\" (only a VoiceInk that has that command reads it)."]
    return "\n".join(out + problem_counts(data.get("problems") or []))


def run(action: str, as_json: bool = False, dry_run: bool = False, backup: Optional[str] = None,
        list_backups: bool = False, out: Optional[str] = None) -> Tuple[str, int]:
    """The report and the script's exit code: the CLI's own on an error, 2 when the CLI is not installed."""
    if find_cli() is None:
        return missing_cli()
    args = [action]
    if action == "sync" and dry_run:
        args.append("--dry-run")
    if action == "restore":
        args += ["--list"] if list_backups else ([backup] if backup else [])
    if action == "export" and out:
        args += ["--out", out]
    data, code, raw = call(args)
    if code != 0:
        return error_text(data, code, raw), script_exit(data, code)
    if data is None:
        return "hal2-cli-voiceink answered without JSON:\n%s" % raw[:600], 1
    if as_json:
        return json.dumps(data, indent=2, ensure_ascii=False), 0
    report = {"sync": sync_report, "status": status_report, "restore": restore_report, "export": export_report}[action]
    return report(data), 0
