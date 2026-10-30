"""Is a train building? (hal2 plan 0472 step 1, D1): the one answer /prune and the tollman's prune duty share.

A landing's or train's local phase runs its checks and install under ONE workqueue hold (landings-freeze-builds), so a
live hold in `hal2-cli-workqueue status --json` (`holds`, plan 0418) means builds are running. While it stands prune
plans no trim, no muck out and no size walk: those mass deletes and tree walks starved train 25's local phase of I/O.
Removals of landed fields need no walk and go on. A missing CLI or an answer that cannot be read counts as not busy.

  busy.py [--repo DIR]
      the answer as a program (hal2 plan 0480 D4): the tollman's prune duty runs it live before a trim, a muck out or a
      response of a plan one round old (it never imports /prune); prints the reason or nothing, exit 0.
"""

import argparse
import json
import subprocess
import sys

DEFERRED = "deferred: train building"
TIMEOUT = 20


def reason(main: str, run=subprocess.run) -> str | None:
    """`deferred: train building (hold <id> of field <f>)` while a workqueue hold is live, else None."""
    try:
        p = run(["hal2-cli-workqueue", "status", "--json"], cwd=main, capture_output=True, text=True, timeout=TIMEOUT)
        holds = json.loads(p.stdout).get("holds") or []
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return None
    if p.returncode or not isinstance(holds, list) or not holds:
        return None
    h = holds[0] if isinstance(holds[0], dict) else {}
    return f"{DEFERRED} (hold {h.get('id', '?')} of field {h.get('field', '?')}, {h.get('state', 'holding')})"


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="busy.py", description=__doc__.splitlines()[0])
    p.add_argument("--repo", default=".")
    print(reason(p.parse_args(argv).repo) or "")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
