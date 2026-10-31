"""The tollman's workqueue hold over a train's local work, its pretest (plan 0466 D4, narrowed by plan 0467), used by
engine.land: the wait for the run before holds nothing, and the merge-to-main runs outside it, under hal2-git's own
step-scoped hold (held through its local phase only). A train through merge-to-main-cloud holds nothing at all (plan
0467 D37, the user: "for the cloud mtm i dont see a reason right now"), as hal2-git's landing does."""

import contextlib
import os
import re
import shutil
import subprocess
from pathlib import Path

WQ = "hal2-cli-workqueue"
CLOUD = "merge-to-main-cloud.yml"


def cloud_train(top: str) -> bool:
    """Whether the train in `top` lands through merge-to-main-cloud, as hal2-git picks it (ci/choice.rs):
    `HAL2_LAND_WORKFLOW` over `.hal/landing.toml`'s `workflow`, and only when the tree has that workflow file."""
    setting = os.environ.get("HAL2_LAND_WORKFLOW", "").strip()
    if not setting:
        try:
            text = (Path(top) / ".hal" / "landing.toml").read_text()
        except OSError:
            text = ""
        found = re.search(r'^\s*workflow\s*=\s*"([a-z]+)"', text, re.M)
        setting = found.group(1) if found else ""
    return setting == "cloud" and (Path(top) / ".github" / "workflows" / CLOUD).is_file()


@contextlib.contextmanager
def landing_hold(top: str):
    """ONE workqueue hold over the train's local work, the pretest (plan 0466 D4, plan 0467): taken by id before it,
    released in a `finally` before the wait and the landing, and `HAL2_WORKQUEUE_HOLD=<id>` in this process's
    environment meanwhile so the pretest's children are part of it. `hold take` runs a holder of its own, so
    a crash of this process ends it: `--owner-pid` names this process, the holder ends when it is gone and has no
    time cap while it lives (plan 0466 D5: a long train outlives 60 minutes). A cloud train (`cloud_train`), no CLI
    on the PATH or a failed take: no hold (the latter two with a warning), the train still runs."""
    hold_id = f"train-{Path(top).name}-{os.getpid()}"
    taken = False
    if os.environ.get("HAL2_WORKQUEUE_FREEZE") == "0":  # the user's off switch: nothing would freeze
        pass
    elif cloud_train(top):
        print("tollman: no workqueue hold, the train lands through merge-to-main-cloud (plan 0467 D37)", flush=True)
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
