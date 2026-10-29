"""A public farm's snapshot mirror once a train is in the barn (hal2 plan 0409 step 15, D2, A12): the tollman's
machine landed it, so it publishes, never CI. `hal2-cli-git publish` does it all (public off: nothing, nothing said);
a binary without `publish` (one older than the plan) is left alone. `$HAL2_CLI_GIT` names another binary."""

import os
import shutil
import subprocess


def publish(main: str) -> str:
    """The landed line's addition: '' when public is off or the binary has no `publish`, else its first line."""
    cli = shutil.which(os.environ.get("HAL2_CLI_GIT", "hal2-cli-git"))
    if cli is None:
        return ""
    try:  # a binary found but not runnable (a stub, a missing interpreter) counts as none
        if subprocess.run([cli, "publish", "--help"], capture_output=True, check=False).returncode:
            return ""
        out = subprocess.run([cli, "publish", "--repo", main], capture_output=True, text=True, check=False)
    except OSError:
        return ""
    first = (out.stdout.strip().splitlines() or [""])[0]
    if out.returncode == 0:
        return "" if first.startswith("publish: skipped") else f"; {first}"
    said = first or out.stderr.strip()[-200:]
    return f"; publish refused or failed (exit {out.returncode}), the mirror is not updated: {said}"
