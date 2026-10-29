"""The tollman's one workqueue hold over a train's land path (plan 0466 D4), used by engine.land."""

import contextlib
import os
import shutil
import subprocess
from pathlib import Path

WQ = "hal2-cli-workqueue"


@contextlib.contextmanager
def landing_hold(top: str):
    """ONE workqueue hold over the whole land path (plan 0466 D4): taken by id before the pretest, released in a
    `finally`, and `HAL2_WORKQUEUE_HOLD=<id>` in this process's environment so the pretest's and the landing's
    children (hal2-git's own LandingHold nests as a no-op) are part of it. `hold take` runs a holder of its own, so
    a crash of this process ends it: `--owner-pid` names this process, the holder ends when it is gone and has no
    time cap while it lives (plan 0466 D5: a long train outlives 60 minutes). Without the CLI on the PATH
    or when the take fails: a warning and no hold, the train still runs."""
    hold_id = f"train-{Path(top).name}-{os.getpid()}"
    taken = False
    if os.environ.get("HAL2_WORKQUEUE_FREEZE") == "0":  # the user's off switch: nothing would freeze
        pass
    elif shutil.which(WQ):
        try:
            p = subprocess.run([WQ, "hold", "take", "--class", "landing", "--id", hold_id, "--field", Path(top).name,
                                "--owner-pid", str(os.getpid())],
                               cwd=top, capture_output=True, text=True, timeout=3600)
            taken = p.returncode == 0
            if not taken:
                print(f"tollman: no workqueue hold ({(p.stdout + p.stderr).strip()[-200:]})", flush=True)
        except (OSError, subprocess.TimeoutExpired) as e:
            print(f"tollman: no workqueue hold ({e})", flush=True)
    else:
        print(f"tollman: no workqueue hold ({WQ} is not on the PATH)", flush=True)
    before = os.environ.get("HAL2_WORKQUEUE_HOLD")
    if taken:
        os.environ["HAL2_WORKQUEUE_HOLD"] = hold_id
    try:
        yield
    finally:
        if before is None:
            os.environ.pop("HAL2_WORKQUEUE_HOLD", None)
        else:
            os.environ["HAL2_WORKQUEUE_HOLD"] = before
        if taken:
            try:
                subprocess.run([WQ, "hold", "release", "--id", hold_id], cwd=top, capture_output=True, timeout=60)
            except (OSError, subprocess.TimeoutExpired) as e:
                print(f"tollman: the workqueue hold {hold_id} was not released ({e})", flush=True)
