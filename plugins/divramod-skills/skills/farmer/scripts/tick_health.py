"""A tick that fails is never silent (hal2 plan 0530 D4): the failing streak of a role's rounds, for the farmer and the
tollman alike. `role_cli.run_tick` calls `failed` when its round raised and `succeeded` when it did not; a dry run
calls neither.

State: `tick-health.json` in the role's state folder, a snapshot `{schema: 1, at, failures, error, notified}`
(`schemas/tick-health.schema.json` of each role, declared in its manifest.toml): `at` the last round's time
(roletime, UTC `Z`), `failures` the failed rounds in a row, `error` the last one's line `<Type>: <message>` ("" when
none), `notified` whether this streak's notice went out. Written through a temp file in the same folder and a rename
(role-folder-formats rule 8).

At the 2nd failure in a row, once per streak: one desktop notice "<role> tick failing: <error line>" (notice.py) and
the same line at the top of the role's `summaries/latest.md`. A good round after a notified streak writes "<role> tick
recovered after <n> failed rounds" there (no notice). Nothing here raises: an IO error is one line on stderr.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import notice
import roletime

FILE = "tick-health.json"
SCHEMA = 1
NOTIFY_AT = 2  # the failed rounds in a row that send the notice
LINE_LIMIT = 200


def path(state: Path) -> Path:
    return Path(state) / FILE


def read(state: Path) -> dict:
    """The snapshot, or a clean one when it is missing or unreadable."""
    clean = {"schema": SCHEMA, "at": "", "failures": 0, "error": "", "notified": False}
    try:
        data = json.loads(path(state).read_text())
    except (OSError, ValueError):
        return clean
    if not isinstance(data, dict):
        return clean
    failures = data.get("failures")
    return {**clean, "at": str(data.get("at") or ""),
            "failures": failures if isinstance(failures, int) and failures >= 0 else 0,
            "error": str(data.get("error") or ""), "notified": data.get("notified") is True}


def write(state: Path, data: dict) -> None:
    """Replace the snapshot atomically: a temp file in the same folder, then a rename."""
    state = Path(state)
    fd, tmp = tempfile.mkstemp(prefix=f".{FILE}.", dir=state)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(data) + "\n")
        os.replace(tmp, path(state))
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def error_line(exc: BaseException) -> str:
    """`<Type>: <message>` on one line (the message's last line when it has several)."""
    lines = [x.strip() for x in str(exc).splitlines() if x.strip()]
    return notice.one_line(f"{type(exc).__name__}: {lines[-1]}" if lines else type(exc).__name__, LINE_LIMIT)


def mark(summaries, line: str) -> None:
    """Put `line` at the top of summaries/latest.md (below a front matter, should one ever lead it); `summaries` is
    the folder or a callable giving it (created when missing). Never raises."""
    try:
        d = Path(summaries() if callable(summaries) else summaries)
        d.mkdir(parents=True, exist_ok=True)
        latest = d / "latest.md"
        text = latest.read_text() if latest.exists() else ""
        head, body = "", text
        if text.startswith("---\n") and "\n---\n" in text[4:]:
            end = text.index("\n---\n", 4) + 5
            head, body = text[:end], text[end:]
        latest.write_text(f"{head}{line}\n\n{body}")
    except Exception as exc:
        print(f"tick health: latest.md not written: {type(exc).__name__}: {exc}", file=sys.stderr)


def _save(state: Path, data: dict) -> None:
    try:
        write(state, data)
    except Exception as exc:
        print(f"tick health: {FILE} not written: {type(exc).__name__}: {exc}", file=sys.stderr)


def failed(state: Path, summaries, role: str, exc: BaseException, send=None, clock=None) -> dict:
    """Count a failed round; at the NOTIFY_AT-th in a row, not yet notified: the notice and the latest.md line.
    Returns the new snapshot plus `notice` (the sender's result) when one was sent. `send(title, body)` defaults to
    notice.send."""
    before = read(state)
    data = {"schema": SCHEMA, "at": roletime.now(clock), "failures": before["failures"] + 1,
            "error": error_line(exc), "notified": before["notified"]}
    sent = None
    if data["failures"] >= NOTIFY_AT and not data["notified"]:
        line = notice.one_line(f"{role} tick failing: {data['error']}", LINE_LIMIT)
        try:
            sent = (send or notice.send)(f"hal2 {role}", line)
        except Exception as e:  # an injected sender too must never take the round down
            sent = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        mark(summaries, line)
        data["notified"] = True
        if not (sent or {}).get("ok"):
            print(f"tick health: notice not shown: {(sent or {}).get('error')}", file=sys.stderr)
    _save(state, data)
    return data | ({"notice": sent} if sent is not None else {})


def succeeded(state: Path, summaries, role: str, clock=None) -> dict:
    """A good round ends the streak; after a notified one, the recovery line goes into latest.md (no notice)."""
    before = read(state)
    if before["notified"]:
        mark(summaries, f"{role} tick recovered after {before['failures']} failed rounds")
    data = {"schema": SCHEMA, "at": roletime.now(clock), "failures": 0, "error": "", "notified": False}
    _save(state, data)
    return data
