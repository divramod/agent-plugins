"""Output and wording of the prune run (split from executor.py): the workflow commands (D19) and the action summaries."""

import prune_proof
import sizes

PAST = {"remove": "removed", "muck-out": "mucked out", "trim": "trimmed", "clear-pointer": "cleared",
        "tart-prune": "pruned", "cache-clear": "cleared"}


class Out:
    """The workflow commands (D19) and plain lines; a tool's line that looks like a command is indented."""

    def __init__(self, write=None):
        self.write = write or (lambda text: print(text, flush=True))

    def job(self, name: str) -> None:
        self.write(f"::job::{name}")

    def step(self, slot: str, kind: str = "field") -> None:
        self.write(f"::step::{kind} {slot}")

    def end(self, status: str) -> None:
        self.write(f"::end-step::{status}")

    def line(self, text: str) -> None:
        for one in str(text).splitlines():
            self.write(f"  {one}" if one.startswith("::") else one)


def why_not(f: dict) -> str:
    """Why a field is no candidate any more, in the proof's words where it has them."""
    busy = [s for s in f["sessions"] if s.get("state") in prune_proof.BUSY]
    if busy:
        return f"its agent {busy[0]['pane_id']} is {busy[0]['state']}"
    if f.get("building"):
        return "a build or test runs in it"
    if f.get("hold"):
        return f["hold"]
    return f.get("proof") or "no longer a candidate"


def summary(a: dict, status: str, freed: int, text: str) -> str:
    slot, size = a["field"], sizes.human(freed)
    if status == "skipped":
        return f"skipped {slot}: {text.splitlines()[-1] if text else a['why']}"
    if status == "failure":
        return f"failed to {a['action']} {slot}: {text.splitlines()[-1] if text else 'no output'}"
    if a["action"] == "clear-pointer":
        return f"cleared CURRENT_PLAN {a['plan']} ({a['why'].rsplit(': ', 1)[-1]})"
    if a["action"] == "trim":
        return f"trimmed {slot} {', '.join(a.get('paths') or ['the cleanup set'])}: {size} freed"
    return f"{PAST[a['action']]} {slot}: {size} freed, {a['why']}"
