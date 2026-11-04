#!/usr/bin/env python3
"""lookout's network check (hal2 plan 0581 D3, D10): Telegram for the network watch's red stretches nobody saw.

`hal2-cli-machine net check` runs every 5 minutes on a machine, keeps its DNS and GitHub HTTPS checks and raises one
hal9k notification per red stretch; when that notification timed out or could not be shown, the user is away and
the stretch is marked `away`. This check reads `hal2-cli-machine net status --json` and prints one find per away
stretch (red, and recovered once it ended), each with a stable id, so lookout's own dedupe sends each once (NW3).
Exit by the contract: 0 nothing to tell, 10 found, 75 not checkable now (the CLI missing, or the watch not running
for 15 minutes: `stale`), else broken. The binary is `$LOOKOUT_NETWORK_CLI` (a command line), else `hal2-cli-machine`.
Writes nothing; never repairs anything. Stdlib only.
"""
import json
import os
import shlex
import subprocess
import sys

QUIET, FOUND, UNCHECKABLE, BROKEN = 0, 10, 75, 1


def cli_argv():
    return shlex.split(os.environ.get("LOOKOUT_NETWORK_CLI") or "hal2-cli-machine")


def status():
    """The watch's document, or an exit code with its reason."""
    try:
        done = subprocess.run(cli_argv() + ["net", "status", "--json"], capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        return None, UNCHECKABLE, "missing: hal2-cli-machine is not installed (set LOOKOUT_NETWORK_CLI)"
    except subprocess.TimeoutExpired:
        return None, UNCHECKABLE, "offline: hal2-cli-machine net status timed out"
    if done.returncode != 0:
        return None, BROKEN, f"net status exited {done.returncode}: {(done.stderr or '').strip()[-300:]}"
    try:
        doc = json.loads(done.stdout)
    except ValueError as err:
        return None, BROKEN, f"net status printed no JSON: {err}"
    if not isinstance(doc, dict) or doc.get("schema") != 1:
        return None, BROKEN, f"net status schema {doc.get('schema') if isinstance(doc, dict) else '?'}, this check knows 1"
    return doc, QUIET, ""


def finds(doc):
    """One find per away stretch: its red, and its recovery once it ended."""
    node = doc.get("node") or "this machine"
    found = []
    for ep in doc.get("episodes") or []:
        if ep.get("away") is not True:
            continue
        since, title = ep.get("since", ""), ep.get("title") or ep.get("check", "")
        key = f"network-{node}-{since}"
        data = {"node": node, "check": ep.get("check"), "since": since, "until": ep.get("until")}
        found.append({"id": f"{key}-red", "summary": f"{node}: {title} fails since {since}: {ep.get('detail', '')}"[:200],
                      "data": data})
        if ep.get("until"):
            found.append({"id": f"{key}-recovered",
                          "summary": f"{node}: {title} works again since {ep['until']} (red since {since})"[:200],
                          "data": data})
    return found


def main():
    doc, code, why = status()
    if doc is None:
        print(why, file=sys.stderr)
        return code
    found = finds(doc)
    for item in found:
        print(json.dumps(item, ensure_ascii=False))
    if found:
        return FOUND
    if doc.get("stale"):
        print(f"stale: the network watch on {doc.get('node')} has not run since {doc.get('checked_at') or 'ever'}",
              file=sys.stderr)
        return UNCHECKABLE
    return QUIET


if __name__ == "__main__":
    sys.exit(main())
