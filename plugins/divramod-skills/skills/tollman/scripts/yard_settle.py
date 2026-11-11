"""The yard settled after a green landing (hal2 plan 0294 step 8, D4; split out of yard.py by plan 0789 step 5): the
only code of the tollman that changes the yard (yard.py's docstring says why it may).

  settle(yard, carried, default, head)  a carried path whose content in the yard and in the barn still has the
                                        carried hash loses its local change, then `git pull --ff-only` (also for a
                                        yard whose HEAD rode with no file, plan 0789 D2: the barn holds it now). A
                                        path changed meanwhile stays; a pull that is no fast-forward is said, never
                                        forced, and what was dropped is put back: the yard is then as it was
"""

from __future__ import annotations

import os

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)

import yard
from yard import FROM, blob, objects, run


def settle(repo: str, carried: list[dict], default: str = "origin/main", head: str | None = None) -> dict:
    """After the green landing: {"dropped": [path], "kept": [{path, why}], "pulled": bool, "why": str}. A carried
    path is dropped (a tracked one restored to HEAD, a new one removed) only when its content in the yard and in
    the barn both still have the carried hash and the index holds nothing else; then `git pull --ff-only`. When
    that is no fast-forward, what was dropped is put back from the barn (the same content) and kept: the yard is
    as it was. A yard `survey` would skip is not touched at all. `head`: the yard's HEAD that rode (yard_head.py):
    the pull is tried for it even with no file carried."""
    out = {"dropped": [], "kept": [], "pulled": False, "why": ""}
    skipped = yard.survey(repo, default)["skipped"]
    if skipped or not (carried or head):
        out.update(kept=[{"path": c["path"], "why": skipped} for c in carried if skipped], why=skipped or "")
        return out
    paths = [c["path"] for c in carried]
    barn, held = objects(repo, default, paths), objects(repo, "HEAD", paths)
    index = {row.split("\t", 1)[1]: row.split()[1]
             for row in run(repo, "ls-files", "-s", "-z").stdout.split("\0") if "\t" in row}
    for c in carried:
        path, want = c["path"], c.get("hash")
        why = ("changed meanwhile" if blob(repo, path) != want
               else "the barn does not hold what was carried" if barn.get(path, (None,))[0] != want
               else "staged differently meanwhile" if index.get(path) not in (None, want, held.get(path, (None,))[0])
               else "")
        out["kept"].append({"path": path, "why": why}) if why else out["dropped"].append(path)
    tracked = [p for p in out["dropped"] if p in held]
    new = [p for p in out["dropped"] if p not in held]
    if tracked:
        run(repo, "checkout", "-q", "HEAD", *FROM, data="\0".join(tracked))
    if new:
        run(repo, "rm", "-q", "--cached", "--ignore-unmatch", *FROM, data="\0".join(new))
    for path in new:
        if os.path.lexists(os.path.join(repo, path)):
            os.unlink(os.path.join(repo, path))
    remote, _, name = default.partition("/")
    pull = run(repo, "pull", "-q", "--ff-only", remote, name)
    out.update(pulled=pull.returncode == 0, why="" if pull.returncode == 0 else pull.stderr.strip()[-300:])
    if pull.returncode and out["dropped"]:
        there = [c["path"] for c in carried if c["path"] in out["dropped"] and c.get("hash")]
        if there:
            run(repo, "restore", f"--source={default}", "--worktree", *FROM, data="\0".join(there))
        for path in set(out["dropped"]) - set(there):
            if os.path.lexists(os.path.join(repo, path)):
                os.unlink(os.path.join(repo, path))
        out["kept"] += [{"path": p, "why": "put back: the yard was not fast-forwarded"} for p in out["dropped"]]
        out["dropped"] = []
    return out
