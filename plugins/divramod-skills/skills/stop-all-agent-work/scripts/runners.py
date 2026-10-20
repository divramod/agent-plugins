"""The self-hosted GitHub Actions runners quiet.py meets: which processes are runners or below one, the runner
LaunchAgents, and the record entries that restart them (plan 0397 gap 12)."""
import os
import re
from pathlib import Path

RUNNER_PROC = re.compile(r"Runner\.(Listener|Worker)\b|/actions-runner[^ ]*/(run|runsvc)\.sh")


def related(cmds) -> bool:
    """One of a process chain's command lines (the process and its parents) is a runner's."""
    return any(RUNNER_PROC.search(cmd) for cmd in cmds)


def services(listing: str, launch_agents: Path) -> list:
    """The loaded runner LaunchAgents of `launchctl list`'s output: [(label, plist)]."""
    loaded = {line.split("\t")[2] for line in listing.splitlines()[1:] if len(line.split("\t")) == 3}
    return [(label, str(launch_agents / f"{label}.plist")) for label in sorted(loaded)
            if label.startswith("actions.runner.")]


def restarts(found: list) -> list:
    """Record entries that restart every runner service of `found`. A runner that was frozen or stopped stays online
    but deaf (its session with GitHub died): SIGCONT is not enough, the service is kickstarted. Never wakes or parks a
    CI machine (only the CI supervisor does)."""
    uid = str(os.getuid())
    return [{"text": f"restart runner service {label}", "kind": "runner", "do": ["true"],
             "undo": ["launchctl", "kickstart", "-k", f"gui/{uid}/{label}"]} for label, _ in found]
