"""The land branch's name is checked before every push (the user, 2026-11-04: "the name of a train should also be
checked by the pre checks. it should be land/<wt> or land/train-<no>-<try>. this also needs to be deterministic now";
train 51's run went out as `land/tollman-train-big-0514-0581-28`: started by hand, unmarked, hal2-git fell back to
`land/<carrier>`).

`engine.land` asks `refuses` twice: before the pretest (no pretest for a landing that may not push) and right before
the landing (after the wait for the run before, the last point before every push). The branch it lands on is what
hal2-cli-git will push: `land/<ref>` when the engine passes `--land-ref`, else the carrier's train mark's
`land/train-<n>-<a>` (`worktree queue --json`'s `trains`, the row whose `carrier` is the field), else hal2-git's
fallback `land/<carrier>`. It must be `land/<NN>` (a field's own landing) or `land/train-<n>-<a>` with `<n>` the
standing train's number. Anything else, or a queue that cannot be read: refused, one line `tollman: refused: ...` and
the landing's result as a JSON line (`status` `refused`, as head_guard's), exit 1; never a push under a wrong name.
"""

import json
import re
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import train_state

GOOD = re.compile(r"^land/(?:\d{2}|train-(\d+)-(\d+))$")
LINE = "tollman: refused: the landing would push {branch}, not land/<NN> or land/train-<n>-<a>: {why}"


def branch(field: str, ref: str | None, queue: dict | None) -> str | None:
    """The branch the landing pushes (see the module doc); None when the queue cannot be read."""
    if ref:
        return ref if ref.startswith("land/") else f"land/{ref}"
    if not isinstance(queue, dict):
        return None
    row = next((t for t in queue.get("trains") or [] if t.get("carrier") == field), None)
    return f"land/{row['name']}" if row and row.get("name") else f"land/{field}"


def why_bad(name: str | None, number) -> str | None:
    """Why `name` is no good land branch for the train numbered `number`, or None."""
    if name is None:
        return "the merge queue could not be read"
    m = GOOD.match(name)
    if not m:
        return "the train has no `--train <n> --attempt <a>` mark" if name.startswith("land/tollman") else "bad name"
    if m.group(1) and number and int(m.group(1)) != int(number):
        return f"the mark names train {m.group(1)}, the standing train is {number}"
    return None


def queue(top: str) -> dict | None:
    from engine import cli  # lazily: engine imports this module
    code, out = cli(["worktree", "queue", "--json"], top)
    try:
        return json.loads(out) if code == 0 else None
    except ValueError:
        return None


def refuses(top: str, ref: str | None = None, read=queue) -> int:
    """1 (printed) when the landing of the carrier `top` would push a branch of another name, else 0."""
    main = mtm_scan.main_checkout(top)
    train = train_state.standing(train_state.lines(main)) or {}
    name = branch(Path(top).name, ref, read(top))
    why = why_bad(name, train.get("number"))
    if not why:
        return 0
    line = LINE.format(branch=name or "?", why=why)
    print(line, flush=True)
    print(json.dumps({"status": "refused", "run": None, "message": line}), flush=True)
    return 1
