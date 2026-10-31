"""The workqueue's quiet mode (plan 0516 D4) as the important-interrupt skill drives it: stop turns it on, done turns
it off again, but only when the interrupt turned it on (a quiet the user set before stays). The CLI is
$HAL2_CLI_WORKQUEUE, else hal2-cli-workqueue on PATH; a missing CLI or a failing call is reported and never stops the
interrupt. The undo is a recorded action, so resume.py's `done` runs it with the other undos."""
import json
import os
import re
import shutil

NAME = "hal2-cli-workqueue"
ON_TEXT = "set workqueue quiet on"


def find_cli() -> str | None:
    """The CLI's path ($HAL2_CLI_WORKQUEUE, a path or a name, else hal2-cli-workqueue), None when not installed."""
    return shutil.which(os.environ.get("HAL2_CLI_WORKQUEUE") or NAME)


def parse(out: str) -> str | None:
    """'on' or 'off' from `quiet`'s output: JSON ({"quiet": true|"on"}) or text ('quiet: on'); None if unreadable."""
    try:
        val = json.loads(out)
        val = val.get("quiet", val.get("mode")) if isinstance(val, dict) else val
        if isinstance(val, bool):
            return "on" if val else "off"
        if isinstance(val, str) and val.lower() in ("on", "off"):
            return val.lower()
    except ValueError:
        pass
    m = re.search(r"\bquiet\b\D{0,20}?\b(on|off)\b", out, re.I) or re.search(r"\b(on|off)\b", out, re.I)
    return m.group(1).lower() if m else None


def state(d, cli: str) -> str | None:
    code, out, _ = d.sys.run([cli, "quiet"], timeout=15)
    return parse(out) if code == 0 else None


def turn_on(d, dry: bool) -> tuple:
    """(kinds of what was done, the note for the record's important_interrupt block). Nothing is raised."""
    cli = find_cli()
    if cli is None:
        d.out(f"{NAME} not found: workqueue quiet mode not set (the machine is quieted without it)")
        return [], {"cli": None, "set": False}
    if dry:
        d.out(f"would {ON_TEXT}: {cli} quiet on (left as it is when already on)")
        return ["quiet"], {}
    was = state(d, cli)
    if was == "on":
        d.out("workqueue quiet already on: left as it is (done will not turn it off)")
        return [], {"cli": cli, "was": "on", "set": False}
    code, _, err = d.sys.run([cli, "quiet", "on"], timeout=30)
    if code != 0:
        d.out(f"workqueue quiet on failed (exit {code}{': ' + err.strip() if err.strip() else ''}): the "
              "interrupt goes on without it")
        return [], {"cli": cli, "was": was, "set": False, "error": code}
    d.rec.add_actions([{"text": ON_TEXT, "do": [cli, "quiet", "on"], "undo": [cli, "quiet", "off"]}])
    d.out(f"{ON_TEXT}: holds freeze across farms, heavy jobs at background priority (done turns it off)")
    return ["quiet"], {"cli": cli, "was": was, "set": True}
