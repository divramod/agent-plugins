"""A smuggle's part in a train that did not land (hal2 plan 0360 step 18, D61, D62): the fix goes to the smuggling
field as a fix order by code (orders.py through `tollman.py order <slot> --smuggle`), no wake; the train waits frozen
for it (D7: no time limit).

- `smuggles`: the landed smuggles the queue still lists (`smuggle.phase` `unverified`: their ranges wait for a land
  run to gate them, hal2-git queue::keep_unverified), newest first, each with the files it changed: from its
  `gate_base` (the barn before it) to the next smuggle's `gate_base`, the newest to the barn's head; nothing else
  lands while a train stands. With `carrier`: only those its ticket's `covers` names (the candidate gates them).
- `touched`: the first smuggle whose files a red names (the path in the failed log's tail, or the file's stem in a
  failing test's name): triage's `smuggled` kind (D61).
- `conflict`: a landing that ended `conflict` while smuggles stand is the resumed landing's merge of the new main
  (D62): the order goes to the newest smuggle whose files conflict, else to the newest smuggle.
"""

import subprocess
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import trial as trial_merge
from tick import act, default_ref

CLI = Path(__file__).with_name("tollman.py")
STEM = 4  # a file's stem shorter than this is never looked for in a test's name
TEXT = {
    "resume_conflict": "the train's merge of the new main conflicts with your smuggle in {files}: on `{branch}` merge "
                       "`origin/main` into the carrier's head, resolve, push, answer fixed <sha>",
    "smuggled_red": "the train's land run {run} is red in {jobs} on files your smuggle changed ({files}): on "
                    "`{branch}` fix it from the carrier's head, push, answer fixed <sha>",
}


def diff(main: str, base: str | None, end: str) -> list[str]:
    if not base or not Path(main).is_dir():
        return []
    try:
        code, text = trial_merge.git(main, "diff", "--name-only", f"{base}..{end}")
    except (OSError, subprocess.TimeoutExpired):
        return []
    return text.splitlines() if code == 0 and text else []


def smuggles(main: str, tickets, carrier: str | None = None) -> list[dict]:
    """[{slot, seq, files}], newest first (see the module doc)."""
    landed = sorted((t for t in tickets or () if (t.get("smuggle") or {}).get("phase") == "unverified"),
                    key=lambda t: t.get("seq", 0))
    ends = [t["smuggle"].get("gate_base") for t in landed[1:]] + [default_ref(main)]
    out = [{"slot": t["slot"], "seq": t.get("seq"), "files": diff(main, t["smuggle"].get("gate_base"), end)}
           for t, end in zip(landed, ends)]
    if carrier is not None:
        covers = next((t.get("covers") or [] for t in tickets if t.get("slot") == carrier), [])
        out = [s for s in out if s["slot"] in covers]
    return out[::-1]


def touched(rows: list[dict], tail: str, tests: list[str]) -> dict | None:
    """The newest smuggle whose files the red names, with them (`hits`), or None."""
    for s in rows or ():
        hits = [f for f in s["files"] if f in (tail or "") or (len(stem := Path(f).stem) >= STEM
                                                               and any(stem in t for t in tests))]
        if hits:
            return {**s, "hits": hits}
    return None


def order(top: str, slot: str, why: str, after: str, run: str | None = None) -> dict:
    """The fix order to the smuggling field, run after the train's `red` line (orders.order needs a red train)."""
    argv = [sys.executable, str(CLI), "order", slot, "--smuggle", "--why", why, *(["--run", run] if run else []),
            "--repo", top]
    key = f"smuggle-order:{after}:{slot}"
    stuck = act("trains", "train-stuck", "wake", key=f"stuck:{key}",
                text=f"the fix order to smuggle {slot} failed: run `{' '.join(argv[1:5])} ...` to see why")
    return act("trains", "fix-order", "run", "-", key=key, argv=argv, after=after, on_fail=[stuck],
               text=f"fix order to smuggle {slot}: {why[:120]}")


def conflict(top: str, main: str, train: dict, result: dict | None, tickets, after: str) -> list[dict]:
    """The order for a resume conflict (D62), or [] when no smuggle stands."""
    rows = smuggles(main, tickets) or [{"slot": p["field"], "files": []} for p in reversed(train.get("pauses") or [])]
    if not rows:
        return []
    files = (result or {}).get("files") or []
    s = next((s for s in rows if set(files) & set(s["files"])), rows[0])
    named = [f for f in files if f in s["files"]] or files
    why = TEXT["resume_conflict"].format(files=", ".join(named[:5]) or "its files", branch=f"{s['slot']}-train-fix")
    return [order(top, s["slot"], why, after)]


def red(top: str, verdict: dict, after: str, run: str | None) -> list[dict]:
    """The order for a smuggled red (D61)."""
    e, slot = verdict["evidence"], verdict["evidence"]["slot"]
    why = TEXT["smuggled_red"].format(run=run or "none", jobs=", ".join(e.get("jobs") or e.get("red") or []) or "a job",
                                      files=", ".join(e.get("files", [])[:5]), branch=f"{slot}-train-fix")
    return [order(top, slot, why, after, run)]
