"""Half-removed fields (hal2 plan 0377 step 5, D7, PR19): a removal killed midway, found by the next run and finished.

`timeout 600 prune.py remove 36` was killed mid-delete and left 5435 tracked files deleted. So every removal is
journaled in the farm's prune state folder (`removing.json`, written just before, dropped when the command ended):

- `journaled`: a journaled field still a worktree. Resumed (`--force`) only with HEAD as journaled, nothing changed but
  deleted tracked files and every commit on origin (its default branch, a servant's on `origin/<foreman>`).
- `folder-left`: an NN folder beside the fields that is no worktree. Resumed (deleted, `git worktree prune`, its
  branch dropped when on origin) only when journaled; else left and reported: on doubt never delete.
- `files-gone`: journaled, the folder already gone; git's bookkeeping finished the same way.
- `deleted-files`: no journal, nothing changed but at least HALF_MIN tracked files deleted, no session. Restored by
  `git checkout -- .` only when HEAD is on an origin branch, then the proof decides; else left and reported.
"""

import shutil
import time
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import prune_act  # the hands; prune_act never imports this module (the executor journals around a removal)
import prune_proof
import store
import tick

JOURNAL = "removing.json"
HALF_MIN = 100  # deleted tracked files without a journal: a removal killed midway, not a person's edit
IGNORED = ("plans/CURRENT_PLAN", "plans/LEAD")  # untracked pointers where a farm does not ignore them


def journal(main: str) -> dict:
    return store.read_json(store.state_dir(main) / JOURNAL, {})


def begin(main: str, field: dict, foreman: str | None) -> None:
    j = journal(main)
    j[field["slot"]] = {"path": field["path"], "head": field.get("head"), "branch": field.get("branch"),
                        "foreman": foreman, "at": time.time()}
    store.write_json(store.state_dir(main) / JOURNAL, j)


def done(main: str, slot: str) -> None:
    j = journal(main)
    if j.pop(slot, None) is not None:
        store.write_json(store.state_dir(main) / JOURNAL, j)


def deleted(path: str) -> int | None:
    """How many tracked files are deleted in the worktree, None when anything else changed too."""
    n = 0
    for line in prune_proof.git(path, "status", "--porcelain").splitlines():
        if line.startswith(" D "):
            n += 1
        elif not (line.startswith("?? ") and line[3:] in IGNORED):
            return None
    return n


def detect(main: str, fields: list[dict], only: set[str] | None = None) -> list[dict]:
    """The half-removed fields `{slot, path, state, journal, deleted}` (`only`: those slots), in slot order."""
    known, j, out = {f["slot"]: f for f in fields}, journal(main), []
    wanted = lambda slot: only is None or slot in only  # noqa: E731
    for slot, e in j.items():
        if wanted(slot):
            path = Path(e["path"])
            state = "files-gone" if not path.exists() else "journaled" if slot in known else "folder-left"
            out.append({"slot": slot, "path": str(path), "state": state, "journal": e,
                        "deleted": deleted(str(path)) if state == "journaled" else None,
                        "sessions": (known.get(slot) or {}).get("sessions", [])})
    for f in fields:
        n = None if f["slot"] in j or f.get("sessions") else deleted(f["path"])
        if n is not None and n >= HALF_MIN:
            out.append({"slot": f["slot"], "path": f["path"], "state": "deleted-files", "journal": None, "deleted": n})
    for base in bases(main, fields, j):
        for d in sorted(base.iterdir()) if base.is_dir() else []:
            if (prune_proof.NUMBERED.fullmatch(d.name) and d.is_dir() and d.name not in known and d.name not in j
                    and wanted(d.name)):
                out.append({"slot": d.name, "path": str(d), "state": "folder-left", "journal": None, "deleted": None})
    return sorted(out, key=lambda h: h["slot"])


def bases(main: str, fields: list[dict], j: dict) -> set[Path]:
    """The folders the farm's worktrees live in (every worktree git knows but main, the fields, the journal's)."""
    known = [x[9:] for x in prune_proof.git(main, "worktree", "list", "--porcelain").splitlines()
             if x.startswith("worktree ")][1:]
    return {Path(p).parent for p in [*known, *(f["path"] for f in fields), *(e["path"] for e in j.values())]}


def describe(h: dict) -> str:
    left = "other changes too" if h["deleted"] is None else f"{h['deleted']} tracked file(s) deleted"
    return {"journaled": f"a journaled removal was cut off: {left}",
            "folder-left": "the folder is left without its worktree" + ("" if h["journal"] else " (no prune removal)"),
            "files-gone": "a journaled removal deleted the folder, git's bookkeeping is left",
            "deleted-files": f"{h['deleted']} tracked files deleted, nothing else changed"}[h["state"]]


def base_of(main: str, h: dict) -> str:
    foreman = (h["journal"] or {}).get("foreman")
    return f"origin/{foreman}" if foreman else tick.default_ref(main)


def unsafe(main: str, h: dict) -> str | None:
    """Why a journaled removal may not be resumed now, None when it may."""
    slot, path, base, e = h["slot"], h["path"], base_of(main, h), h["journal"]
    if h.get("sessions"):
        return f"a session runs in it ({', '.join(str(x.get('pane_id')) for x in h['sessions'])})"
    if h["state"] == "journaled":
        if prune_proof.git(path, "rev-parse", "HEAD") != e.get("head"):
            return "its HEAD moved since the removal began"
        if h["deleted"] is None:
            return "it holds changes besides deleted files"
        why = (prune_proof.unsaved_for_lead(path, slot, base) if e.get("foreman")
               else [w for w in prune_proof.unsaved(path, slot, base) if w != "uncommitted changes"
                     and not w.startswith(prune_proof.POINTER_WHY)])
        return "; ".join(why) or None
    refs = prune_proof.git(main, "for-each-ref", "--format=%(refname:short)", f"refs/heads/{slot}",
                           f"refs/heads/{slot}-*").split()
    late = [r for r in refs if prune_proof.git(main, "rev-list", "--count", f"{base}..{r}") not in ("0", "")]
    return f"branch {', '.join(late)} holds commits not on {base}" if late else None


def finish(main: str, h: dict) -> tuple[str, str]:
    """The folder deleted (no timeout, D7), git's bookkeeping pruned, the branch dropped (its commits are on origin)."""
    slot, base = h["slot"], base_of(main, h)
    shutil.rmtree(h["path"], ignore_errors=True)
    if Path(h["path"]).exists():
        return "failure", f"{h['path']} could not be deleted"
    prune_act.run(["git", "worktree", "prune"], main)
    if prune_proof.git(main, "rev-parse", "--verify", "--quiet", f"refs/heads/{slot}"):
        prune_act.run(["git", "branch", "-D", slot], main)
    if prune_proof.ref_exists(main, f"origin/{slot}"):
        if prune_proof.git(main, "rev-list", "--count", f"{base}..origin/{slot}") != "0":
            return "success", f"folder deleted; origin/{slot} kept: it holds commits not in {base}"
        return prune_act.drop_remote(main, slot, base, "folder deleted")
    return "success", "folder deleted"


def resume(main: str, h: dict, dry: bool) -> tuple[str, str, bool]:
    """(status, line, planned again): the half-removed field finished, restored or left with why."""
    slot, path = h["slot"], h["path"]
    if h["state"] == "deleted-files":
        if not prune_proof.git(path, "branch", "-r", "--contains", "HEAD"):
            return ("skipped", f"left {slot}: {h['deleted']} tracked files deleted, HEAD on no origin branch: "
                    "restore by hand", False)
        if dry:
            return "success", f"would restore {h['deleted']} tracked files of {slot}, then the proof runs again", False
        code, text = prune_act.run(["git", "checkout", "--", "."], path)
        if code:
            return "failure", f"failed to restore {slot}: {text}", False
        return "success", f"restored {h['deleted']} tracked files of {slot} (HEAD is on origin); the proof decides", True
    if h["journal"] is None:
        return "skipped", f"left {slot}: {path} is no worktree, no prune run began its removal: check it by hand", False
    if h["state"] == "journaled" and h["deleted"] == 0:
        if not dry:
            done(main, slot)
        return "success", f"the removal of {slot} deleted nothing yet: its journal dropped, the proof decides", not dry
    why = unsafe(main, h)
    if why:
        return "skipped", f"left {slot}: the removal is not resumed: {why}", False
    if dry:
        return "success", f"would resume the removal of {slot}", False
    if h["state"] == "journaled":
        status, text = prune_act.remove_cmd(main, slot, (h["journal"] or {}).get("foreman"), force=True)
    else:
        status, text = finish(main, h)
    if status == "success":
        done(main, slot)
    said = "resumed the removal of" if status == "success" else "failed to resume the removal of"
    return status, f"{said} {slot}: {text}", False
