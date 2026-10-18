#!/usr/bin/env python3
"""lookout's generic e-mail check (plan 0311 step 6, design.md "Check contract", D5).

Calls `hal2-cli-email` as an external command (never gws), prints one JSON line per new mail and exits by the
contract: 0 nothing new, 10 new mail, 75 not checkable now (CLI missing, not logged in, offline), else broken.

    email.py [--query Q] [--address A] [--account S] [--limit N] [--no-sync]
             [--known-from "CMD"] [--first-hours H] [--overlap-min M]

The binary is `$LOOKOUT_EMAIL_CLI` (a command line, shlex-split), else `hal2-cli-email`. The since-state is
`$LOOKOUT_STATE/email-since.json`, the only file this check writes. Stdlib only.
"""
import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone

QUIET, FOUND, UNCHECKABLE, BROKEN = 0, 10, 75, 1
STATE_FILE = "email-since.json"
AUTH_WORDS = ("auth", "login", "password", "credential", "secret", "denied", "unauthor")
OFFLINE_WORDS = ("connect", "network", "resolve", "timed out", "timeout", "offline", "unreachable", "dns")


class Uncheckable(Exception):
    def __init__(self, cause, detail):
        super().__init__(detail)
        self.cause, self.detail = cause, detail


class Broken(Exception):
    pass


def now():
    return datetime.now(timezone.utc)


def iso(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(text):
    try:
        moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def cli_argv():
    return shlex.split(os.environ.get("LOOKOUT_EMAIL_CLI") or "hal2-cli-email")


def run_cli(args):
    """Run the CLI with `--json`; return its stdout. 75 for a missing CLI or login/network trouble."""
    try:
        done = subprocess.run(cli_argv() + args + ["--json"], capture_output=True, text=True, timeout=240)
    except FileNotFoundError:
        raise Uncheckable("missing", "hal2-cli-email is not installed (set LOOKOUT_EMAIL_CLI)")
    except subprocess.TimeoutExpired:
        raise Uncheckable("offline", "hal2-cli-email timed out")
    if done.returncode == 0:
        return done.stdout
    err = (done.stderr or done.stdout).strip()[-500:]
    low = err.lower()
    if any(w in low for w in AUTH_WORDS):
        raise Uncheckable("auth", err)
    if any(w in low for w in OFFLINE_WORDS):
        raise Uncheckable("offline", err)
    raise Broken(f"hal2-cli-email {' '.join(args[:2])} exited {done.returncode}: {err}")


def read_since(state_dir, first_hours):
    """Where to search from: the saved last run, else LOOKOUT_SINCE, else `first_hours` ago."""
    saved = None
    if state_dir:
        try:
            with open(os.path.join(state_dir, STATE_FILE), encoding="utf-8") as fh:
                saved = parse_time(json.load(fh).get("since"))
        except (OSError, ValueError, AttributeError):
            saved = None
    return saved or parse_time(os.environ.get("LOOKOUT_SINCE", "")) or now() - timedelta(hours=first_hours)


def write_since(state_dir, moment):
    os.makedirs(state_dir, exist_ok=True)
    path = os.path.join(state_dir, STATE_FILE)
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        json.dump({"since": iso(moment)}, fh)
    os.replace(path + ".tmp", path)


def known_keys(command):
    """Message ids another command already knows (one per line, or a JSON list), e.g. the CRM's."""
    if not command:
        return set()
    try:
        done = subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as err:
        raise Broken(f"--known-from failed: {err}")
    if done.returncode != 0:
        raise Broken(f"--known-from exited {done.returncode}: {done.stderr.strip()[-300:]}")
    text = done.stdout.strip()
    try:
        data = json.loads(text) if text.startswith("[") else None
    except ValueError:
        data = None
    items = data if isinstance(data, list) else text.splitlines()
    return {str(i).strip() for i in items if str(i).strip()}


def event(mail):
    who = mail.get("from_name") or ""
    sender = f"{who} <{mail['from']}>" if who and mail.get("from") else mail.get("from") or who or "unknown"
    keep = ("account", "folder", "from", "from_name", "date", "direction", "thread_id", "subject", "attachments", "ref")
    data = {k: mail[k] for k in keep if k in mail}
    data["message_id"] = mail["message_id"]
    data["snippet"] = str(mail.get("snippet", ""))[:300]
    return {"id": f"email-{mail['message_id']}", "summary": f"{sender}: {mail.get('subject', '')}", "data": data}


def parse_mails(text):
    try:
        mails = json.loads(text)
    except ValueError as err:
        raise Broken(f"hal2-cli-email printed no JSON: {err}")
    if not isinstance(mails, list):
        raise Broken("hal2-cli-email messages search --json is not a list")
    return [m for m in mails if isinstance(m, dict) and m.get("message_id")]


def check(opts, state_dir, dry_run):
    started = now()
    since = read_since(state_dir, opts.first_hours)
    if not opts.no_sync:
        run_cli(["sync"] + ([opts.account] if opts.account else []))
    args = ["messages", "search", "--since", iso(since)]
    for flag, value in (("--query", opts.query), ("--address", opts.address), ("--account", opts.account),
                        ("--limit", opts.limit)):
        if value:
            args += [flag, str(value)]
    mails = parse_mails(run_cli(args))
    skip = known_keys(opts.known_from)
    events = [event(m) for m in mails if m["message_id"] not in skip]
    if state_dir and not dry_run:
        write_since(state_dir, started - timedelta(minutes=opts.overlap_min))
    return events


def main(argv=None):
    ap = argparse.ArgumentParser(description="lookout e-mail check")
    ap.add_argument("--query")
    ap.add_argument("--address")
    ap.add_argument("--account")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--no-sync", action="store_true", help="search the local store only")
    ap.add_argument("--known-from", help="command printing message ids to drop (one per line or a JSON list)")
    ap.add_argument("--first-hours", type=float, default=24, help="how far back the very first run looks")
    ap.add_argument("--overlap-min", type=float, default=15, help="re-read this much before the last run")
    opts = ap.parse_args(argv)
    try:
        events = check(opts, os.environ.get("LOOKOUT_STATE"), os.environ.get("LOOKOUT_DRY_RUN") == "1")
    except Uncheckable as err:
        print(json.dumps({"cause": err.cause, "detail": err.detail}))
        return UNCHECKABLE
    except Broken as err:
        print(err, file=sys.stderr)
        return BROKEN
    if not events:
        print("no new mail")
        return QUIET
    for item in events:
        print(json.dumps(item, ensure_ascii=False))
    return FOUND


if __name__ == "__main__":
    sys.exit(main())
