#!/usr/bin/env python3
"""halverse: one call of `hal2-cli-halverse <command> --json`, its JSON read (plan 0276, D37).

The CLI (apps/hal2-cli-halverse) is the one parser of the user's halverse files (plan 0271 D5) and owns the JSON
contract. Its exits (plan 0318, the common table of hal2_core::cli): 0 done, 1 `check` found a problem that fails (the
report is then the error's `details` on stderr) or a write failed, 2 usage or a file that cannot be read, 3 not found,
4 refused, 5 busy. Before plan 0318 a `term` call said 3 refused, 4 changed meanwhile or locked, 5 failed, and its error
`{code, message, detail}` stood on stdout. This script keeps its own exits for `term` calls (2 usage or unreadable,
3 refused or not found, 4 changed meanwhile or locked, 5 failed), whichever shape the CLI answers in; the error is
`{code, message, detail}` with the CLI's writer code (the contract's `details.reason`). The files' overrides `HALVERSE_GLOSSARY`, `HALVERSE_ONTOLOGY` and `HALVERSE_DICTATION` are the CLI's own: the environment
goes on to it unchanged. This module only runs it. Python stdlib only.
"""
import json
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Sequence

CLI = "hal2-cli-halverse"
CLI_ENV = "HAL2_CLI_HALVERSE"  # a path overriding the lookup on PATH (tests, a field's build)
INSTALL = "cargo install --path apps/hal2-cli-halverse   (run in the hal2 repository's code/rust folder)"
TIMEOUT = 60


class CliError(Exception):
    """The CLI is missing, gave no answer or refused; `text` says it for the user, `code` is the script's exit code.

    `error` is the CLI's own `{code, message, detail}` where it gave one: a caller words it with its detail."""

    def __init__(self, text: str, code: int, error: Optional[Dict[str, Any]] = None):
        super().__init__(text)
        self.text = text
        self.code = code
        self.error = error


def normalize_error(error: Any) -> Optional[Dict[str, Any]]:
    """The CLI's error as `{code, message, detail}`: the old object as it is, the contract's `{code, exit, message, hint,
    details}` (plan 0318) with the writer's own code from `details.reason` (`usage` for a wrong call) and the details
    without it. `exit` is kept for the contract's shape only."""
    if not isinstance(error, dict):
        return None
    if "details" not in error and "exit" not in error:
        return error
    details = error.get("details") if isinstance(error.get("details"), dict) else {}
    return {"code": details.get("reason") or error.get("code", "?"), "message": error.get("message", ""),
            "detail": {k: v for k, v in details.items() if k != "reason"}, "exit": error.get("exit")}


def skill_exit(returncode: int, error: Optional[Dict[str, Any]], args: Sequence[str]) -> int:
    """The script's exit code: the CLI's own, but a `term` call that answered in the contract's shape is told in the
    codes this skill documents (2 usage or unreadable, 3 refused or not found, 4 changed meanwhile or locked, 5 failed)."""
    if not (error and error.get("exit") is not None and args and args[0] == "term"):
        return returncode or 1
    code = error.get("code")
    if code in ("usage", "unreadable"):
        return 2
    return {"changed-meanwhile": 4, "locked": 4, "failed": 5}.get(code, 3)


def find_cli() -> Optional[str]:
    override = os.environ.get(CLI_ENV)
    if override:
        return override if os.path.isfile(override) and os.access(override, os.X_OK) else None
    return shutil.which(CLI)


def missing_text() -> str:
    return ("hal2-cli-halverse is not installed (or not on PATH).\n"
            "Install it from the hal2 repository's code/rust folder:\n  %s\n"
            "Then call the command again." % INSTALL)


def _error_text(data: Optional[Dict[str, Any]], code: int, raw: str) -> str:
    err = normalize_error((data or {}).get("error"))
    if not isinstance(err, dict):
        return "hal2-cli-halverse failed with exit code %d and an output this skill cannot read:\n%s" % (code, raw[:600])
    detail = err.get("detail") or {}
    if err.get("code") == "unreadable" and (detail.get("path") or detail.get("file")):
        return ("The %s file %s cannot be read, so nothing was compared. See that the file exists and can be read, "
                "then call the command again." % (detail.get("file") or "source", detail.get("path") or "named below"))
    return "hal2-cli-halverse stopped with the error \"%s\": %s" % (err.get("code", "?"), err.get("message", ""))


def call(args: Sequence[str], ok: Sequence[int] = (0,), stdin: Optional[str] = None) -> Dict[str, Any]:
    """The CLI's JSON for `args` (`--json` is added; `stdin` is a term's document for `--from -`).

    Raises CliError: exit 2 when it is not installed, else its exit code, with the CLI's error object."""
    cli = find_cli()
    if cli is None:
        raise CliError(missing_text(), 2)
    feed = {"stdin": subprocess.DEVNULL} if stdin is None else {"input": stdin}  # never the caller's own stdin
    try:
        done = subprocess.run([cli] + list(args) + ["--json"], capture_output=True, text=True, encoding="utf-8",
                              timeout=TIMEOUT, **feed)
    except subprocess.TimeoutExpired:
        raise CliError("hal2-cli-halverse gave no answer within %d seconds." % TIMEOUT, 1)
    except OSError as exc:
        raise CliError("hal2-cli-halverse could not be run: %s" % exc, 2)
    raw = done.stdout.strip() or done.stderr.strip()
    try:
        data = json.loads(done.stdout) if done.stdout.strip() else json.loads(done.stderr)
    except ValueError:
        data = None
    data = data if isinstance(data, dict) else None
    if data is not None and done.returncode in ok and isinstance(data.get("error"), dict):
        # A `check` that found a problem: the report is in the error's details (plan 0318), nothing on stdout.
        report = data["error"].get("details")
        if isinstance(report, dict) and "problems" in report:
            return report
    if done.returncode not in ok or data is None or "error" in data:
        err = normalize_error((data or {}).get("error"))
        raise CliError(_error_text(data, done.returncode, raw), skill_exit(done.returncode, err, args),
                       err if isinstance(err, dict) else None)
    return data


def lines(items: List[str], limit: int) -> List[str]:
    """At most `limit` lines, the rest counted in the last."""
    return items[:limit] + (["  ... and %d more" % (len(items) - limit)] if len(items) > limit else [])
