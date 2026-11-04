"""hal2-daemon's quiet pollers (plan 0584 D11, D12) as the important-interrupt skill drives them: stop holds the quiet
target `pollers` (`hal2-cli-machine quiet hold pollers`), so the daemon wakes no CI machine, starts no runner clone
and reads no git status, instead of freezing hal2-daemon; done releases it, but only when the interrupt held it (a
hold set before stays). The CLI is $HAL2_CLI_MACHINE, else hal2-cli-machine on PATH. A missing CLI or a failing call
is reported, never fatal: the caller then freezes hal2-daemon as before, so the VMs it stops stay down. The release
is a recorded action, so resume.py's `done` runs it with the other undos."""
import json
import os
import shutil

NAME = "hal2-cli-machine"
TARGET = "pollers"
ON_TEXT = "hold hal2 pollers"


def find_cli() -> str | None:
    """The CLI's path ($HAL2_CLI_MACHINE, a path or a name, else hal2-cli-machine), None when not installed."""
    return shutil.which(os.environ.get("HAL2_CLI_MACHINE") or NAME)


def held(d, cli: str) -> bool | None:
    """Whether `pollers` is held now (`quiet status --json`'s holds); None when unreadable."""
    code, out, _ = d.sys.run([cli, "quiet", "status", "--json"], timeout=15)
    if code != 0:
        return None
    try:
        holds = json.loads(out).get("holds", [])
    except (ValueError, AttributeError):
        return None
    return any(isinstance(h, dict) and h.get("target") == TARGET for h in holds)


def turn_on(d, dry: bool, why: str) -> tuple:
    """(kinds of what was done, the record's note, whether the pollers are quiet so hal2-daemon need not freeze).
    Nothing is raised."""
    cli = find_cli()
    if cli is None:
        d.out(f"{NAME} not found: hal2-daemon's pollers not held (hal2-daemon is frozen instead)")
        return [], {"cli": None, "set": False}, False
    hold = [cli, "quiet", "hold", TARGET, "--reason", why]
    if dry:
        d.out(f"would {ON_TEXT}: {' '.join(hold)} (left as it is when already held)")
        return ["pollers"], {}, True
    if held(d, cli):
        d.out("hal2-daemon's pollers already held: left as they are (done will not release them)")
        return [], {"cli": cli, "was": "held", "set": False}, True
    code, _, err = d.sys.run(hold, timeout=30)
    if code != 0:
        d.out(f"{ON_TEXT} failed (exit {code}{': ' + err.strip() if err.strip() else ''}): hal2-daemon is frozen "
              "instead")
        return [], {"cli": cli, "set": False, "error": code}, False
    d.rec.add_actions([{"text": ON_TEXT, "kind": "pollers", "do": hold, "undo": [cli, "quiet", "release", TARGET]}])
    d.out(f"{ON_TEXT}: no CI wake, no runner clone, no git status until done releases them")
    return ["pollers"], {"cli": cli, "set": True}, True
