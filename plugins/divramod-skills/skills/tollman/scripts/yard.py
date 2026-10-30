"""The yard job (hal2 plan 0294 step 8; decisions D4, D15, D19): before a bring in the tollman brings in what
lies uncommitted in the yard (the main checkout on the default branch), as the first car of the train, tested by
the gate. Nothing is pushed to the default branch directly. Functions over `git` calls, no frame, no state file:
the engine (engine.py) calls them and keeps what was carried in the train state.

  survey(yard)                 what `git status` shows there; everything is skipped (and said, never repaired)
                               when the yard is not on the default branch, is in a merge, rebase, cherry-pick,
                               revert or bisect, or is ahead of the barn
  sort(yard, entries, base)    each path `placed`, or `left` with its reason: the name's (yard_rules.py: secret-
                               shaped, junk, a root outside the allowlist), a conflict state, staged and changed
                               again, gitignored, a submodule or nested repository, a file the barn changed since
                               the yard's head, a file a session unhitched from a red train and that is still the
                               same, a deletion of a file another field's crop changes, a symlink leaving the
                               repository, no regular file, larger than 5 MB, a file a car of this train changes
  look(yard, base, ...)        survey and sort; reads only (the dry run, the farmer's report)
  carry(yard, field, placed)   the placed files' content copied into the tollman's field and committed there
                               as `chore(yard): <n> files from the yard`, by explicit paths, hooks on; each path
                               with the hash of what it carried (a file the barn holds as it is: its hash, no
                               change). No placed file, or nothing that differs: no commit
  settle(yard, carried)        after the green landing: a carried path whose content in the yard and in the barn
                               still has the carried hash loses its local change, then `git pull --ff-only`. A
                               path changed meanwhile stays; a pull that is no fast-forward is said, never forced,
                               and what was dropped is put back: the yard is then as it was

This is the only code of the role that changes the yard, and it does so only in `settle`, only for files it
carried, only after their content is in the barn (hal2's records worktree-no-main-without-consent and
no-implicit-commits: the user asked for it by name, D4). `survey`, `sort`, `look` and `carry` only read the yard
(`git --no-optional-locks`: not even its index is refreshed), and the tollman never gitignores, moves or
edits a file there. After a red train or an unhitch nobody calls `settle`: the yard stays as it was.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import bounded

import origin
import trial
import yard_rules as rules

MAX = 5 * 1024 * 1024
SUBJECT = "chore(yard): {n} file{s} from the yard"
BODY = "Brought in by the tollman from the main checkout, as the train's first car (hal2 plan 0294, D15).\n\n"
BODY_NEUTRAL = "Brought in from the main checkout, as the train's first car.\n\n"
CONFLICT = frozenset(("DD", "AU", "UD", "UA", "DU", "AA", "UU"))
UNDER_WAY = {"MERGE_HEAD": "a merge", "rebase-merge": "a rebase", "rebase-apply": "a rebase",
             "CHERRY_PICK_HEAD": "a cherry-pick", "REVERT_HEAD": "a revert", "BISECT_LOG": "a bisect"}
FROM = ("--pathspec-from-file=-", "--pathspec-file-nul")  # explicit paths, NUL-separated on stdin


def run(repo: str, *args: str, data: str | None = None) -> subprocess.CompletedProcess:
    """git in `repo`: every path literal (no pathspec magic; check-ignore knows none), no optional lock taken,
    names kept byte for byte."""
    literal = [] if args[0] == "check-ignore" else ["--literal-pathspecs"]
    return bounded.run(["git", "--no-optional-locks", *literal, *args], cwd=repo, input=data, local=600,
                       coding={"encoding": "utf-8", "errors": "surrogateescape"})


def objects(repo: str, rev: str, paths: list[str]) -> dict[str, tuple[str, str]]:
    """{path: (hash, type)} for the paths `rev` holds, in one `git cat-file`; a path it lacks is left out."""
    paths = [p for p in paths if "\n" not in p]
    if not paths:
        return {}
    said = run(repo, "cat-file", "--batch-check=%(objectname) %(objecttype)",
               data="".join(f"{rev}:{p}\n" for p in paths)).stdout.split("\n")
    found = {p: tuple(line.split(" ")) for p, line in zip(paths, said)}
    return {p: o for p, o in found.items() if len(o) == 2 and o[1] in ("blob", "tree", "commit")}


def blob(repo: str, path: str) -> str | None:
    """The hash git would store for the file as it lies there now (a symlink: its target's text); None when it is
    gone, `tree` for a folder."""
    full = os.path.join(repo, path)
    if os.path.islink(full):
        return run(repo, "hash-object", "--stdin", data=os.readlink(full)).stdout.strip() or None
    if os.path.isdir(full):
        return "tree"
    return (run(repo, "hash-object", "--", path).stdout.strip() or None) if os.path.isfile(full) else None


def survey(yard: str, default: str = "origin/main") -> dict:
    """What lies uncommitted in the yard: {"skipped": why or None, "entries": [{"xy", "path"}]} (`xy` is git
    status's two letters; a staged rename is a deletion and an addition). Reads only."""
    name = default.split("/", 1)[-1]
    branch = run(yard, "symbolic-ref", "-q", "--short", "HEAD").stdout.strip()
    why = None if branch == name else f"the yard is on {branch or 'a detached head'}, not on {name}"
    gitdir = Path(run(yard, "rev-parse", "--absolute-git-dir").stdout.strip() or os.path.join(yard, ".git"))
    why = why or next((f"{what} is under way in the yard" for mark, what in UNDER_WAY.items()
                       if (gitdir / mark).exists()), None)
    ahead = run(yard, "rev-list", "--count", f"{default}..HEAD").stdout.strip()
    if not why and ahead != "0":
        why = f"the yard is {ahead or 'an unknown number of'} commits ahead of {default}"
    status = None if why else run(yard, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames")
    if status and status.returncode:
        why = f"git status failed in the yard: {status.stderr.strip()[-200:]}"
    if why:
        return {"skipped": why, "entries": []}
    return {"skipped": None, "entries": [{"xy": e[:2], "path": e[3:]} for e in status.stdout.split("\0") if e[3:]]}


def allowed(yard: str, base: str) -> set[str]:
    """The top-level entries a yard file may lie in: the root allowlist as the yard's record holds it (an
    amendment rides with the entry it allows) and every entry the barn tracks already."""
    record = Path(yard) / rules.RECORD
    listed = rules.allowlist(record.read_text(errors="replace")) if record.is_file() else set()
    return listed | {n for n in run(yard, "ls-tree", "--name-only", "-z", base).stdout.split("\0") if n}


def shaped(yard: str, e: dict, c: dict) -> str | None:
    """Why the file itself keeps a path in the yard, or None: it may ride. `c`: sort's lookups."""
    path, xy, full = e["path"], e["xy"], os.path.join(yard, e["path"])
    was, now = c["head"].get(path), c["barn"].get(path)
    if xy in CONFLICT:
        return "a merge conflict"
    if xy[0] not in " ?!" and xy[1] not in " ?!":
        return "staged and changed again in the working tree"
    if "\n" in path:
        return "a line break in its name"
    if xy == "!!" or path in c["ignored"]:
        return "gitignored"
    if "commit" in (was or now or ("", "")) or (os.path.isdir(full) and not os.path.islink(full)):
        return "a submodule or a nested repository"
    if was != now and (now or (None,))[0] not in c["past"].get("carried", {}).get(path, ()):
        return "the barn changed it since the yard's head: pull the yard" if was else "the barn has a file of that name"
    refused = c["past"].get("refused", {})
    if path in refused and refused[path] == blob(yard, path):
        return "unhitched from a red train: it stays until it changes"
    if not os.path.lexists(full):
        return f"deleted here, but field {c['fields'][path]}'s crop changes it" if path in c["fields"] else None
    st = os.lstat(full)
    if stat.S_ISLNK(st.st_mode):
        inside = os.path.commonpath([os.path.realpath(yard), os.path.realpath(full)]) == os.path.realpath(yard)
        if not inside:
            return "a symlink leaving the repository"
    elif not stat.S_ISREG(st.st_mode):
        return "no regular file"
    elif st.st_size > MAX:
        return f"larger than 5 MB ({st.st_size / 1048576:.1f} MB)"
    return f"field {c['cars'][path]}'s crop changes it too" if path in c["cars"] else None


def sort(yard: str, entries: list[dict], base: str = "HEAD", cars: dict | None = None, fields: dict | None = None,
         past: dict | None = None) -> tuple[list[dict], list[dict]]:
    """The survey's entries as `placed` ([{path, deleted, known}], `known`: the barn tracks the path) and `left`
    ([{path, why}]; a junk folder and a root outside the allowlist once). `base`: the barn's head the field stands
    on; `cars` and `fields`: {path: field} of what this train's cars and every field's crop change; `past`:
    {"carried": {path: [hash]}, "refused": {path: hash}} from the train state (a barn file the yard itself brought
    in is the yard's to change again; what a session unhitched stays out until it changes)."""
    paths = [e["path"] for e in entries]
    barn = objects(yard, base, paths)
    dirs = sorted({j.rstrip("/") for j in map(rules.junk, paths) if j and j.endswith("/")})
    roots, tracked = allowed(yard, base), set(objects(yard, base, dirs))
    ignored = run(yard, "check-ignore", "-z", "--stdin", data="\0".join(paths)).stdout.split("\0") if paths else []
    c = {"head": objects(yard, "HEAD", paths), "barn": barn, "ignored": set(ignored) - {""}, "cars": cars or {},
         "fields": fields or {}, "past": past or {}}
    placed, left = [], {}
    for e in sorted(entries, key=lambda e: e["path"]):
        path = e["path"]
        found = rules.named(path, path in barn, roots, tracked) or (path, shaped(yard, e, c))
        if found[1]:
            left.setdefault(*found)
        else:
            placed.append({"path": path, "deleted": not os.path.lexists(os.path.join(yard, path)),
                           "known": path in barn})
    return placed, [{"path": p, "why": w} for p, w in left.items()]


def crops(yard: str, default: str, heads: dict[str, str]) -> dict[str, str]:
    """{path: field} of every path a field's crop changes: what its head changed since it left the barn."""
    out: dict[str, str] = {}
    for field, head in heads.items():
        diff = run(yard, "diff", "--name-only", "--no-renames", "-z", f"{default}...{head}").stdout
        for path in filter(None, diff.split("\0")):
            out.setdefault(path, field)
    return out


def fields(yard: str) -> dict[str, str]:
    """{field: head} of the farm's other worktrees (`git worktree list`)."""
    out, path = {}, ""
    for line in run(yard, "worktree", "list", "--porcelain").stdout.splitlines():
        if line.startswith("worktree "):
            path = line[9:]
        elif line.startswith("HEAD ") and os.path.realpath(path) != os.path.realpath(yard):
            out[os.path.basename(path)] = line[5:]
    return out


def look(yard: str, base: str = "HEAD", default: str = "origin/main", cars: list[dict] | tuple = (),
         past: dict | None = None) -> dict:
    """survey and sort: {"skipped": why or None, "placed": [...], "left": [...]}. `cars`: the train's
    ([{field, head}]). Reads only."""
    seen = survey(yard, default)
    if seen["skipped"]:
        return {"skipped": seen["skipped"], "placed": [], "left": []}
    riding = crops(yard, default, {c["field"]: c["head"] for c in cars})
    gone = any(not os.path.lexists(os.path.join(yard, e["path"])) for e in seen["entries"])
    placed, left = sort(yard, seen["entries"], base, riding,
                        {**(crops(yard, default, fields(yard)) if gone else {}), **riding}, past)
    return {"skipped": None, "placed": placed, "left": left}


def copy(yard: str, field: str, e: dict) -> None:
    """One placed file's content from the yard into the field (a deletion: the file leaves the field)."""
    src, dst = os.path.join(yard, e["path"]), os.path.join(field, e["path"])
    if os.path.lexists(dst):
        os.unlink(dst)
    if e["deleted"]:
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.islink(src):
        os.symlink(os.readlink(src), dst)
    else:
        shutil.copy2(src, dst)


def undo(field: str, placed: list[dict]) -> None:
    """The field as it was before a carry that made no commit (it holds nothing staged of its own)."""
    run(field, "reset", "-q")
    known = [e["path"] for e in placed if e["known"]]
    if known:
        run(field, "checkout", "-q", "HEAD", *FROM, data="\0".join(known))
    for e in placed:
        if not e["known"] and os.path.lexists(os.path.join(field, e["path"])):
            os.unlink(os.path.join(field, e["path"]))


def carry(yard: str, field: str, placed: list[dict], cars: list[dict] | tuple = ()) -> tuple[str | None, list, str]:
    """The placed files as one commit on the field's head: (commit, [{path, hash}], "") with the hash of what
    each path carried (None: its deletion). A placed file the barn holds as it is (a yard that was not fast-
    forwarded) is carried too, without a change, so `settle` drops it; only such files: no commit. Or (None, [],
    why) and the field as it was: a copy, `git add` or hook that failed, or a car of `cars` ([{field, head}])
    that would not merge onto the commit (the yard never holds a train)."""
    if not placed:
        return None, [], ""
    carried, same, why = [], [], ""
    try:
        for e in placed:
            copy(yard, field, e)
        adds = [e["path"] for e in placed if e["known"] or not e["deleted"]]  # not: gone here and in the barn
        done = run(field, "add", *FROM, data="\0".join(adds)) if adds else subprocess.CompletedProcess([], 0, "", "")
        raw = run(field, "diff", "--cached", "--raw", "-z", "--no-renames", "--abbrev=40").stdout.split("\0")
        for meta, path in zip(raw[::2], raw[1::2]) if not done.returncode else ():
            new = meta.split()[3]
            carried.append({"path": path, "hash": None if not new.strip("0") else new})
        if not done.returncode:
            barn, changed = objects(field, "HEAD", [e["path"] for e in placed]), {c["path"] for c in carried}
            same = [{"path": e["path"], "hash": barn.get(e["path"], (None,))[0]} for e in placed
                    if e["path"] not in changed]
        if carried:
            n = len(carried)
            body = BODY + "\n".join(f"- {c['path']}" for c in carried[:100]) + ("\n- ..." if n > 100 else "")
            if origin.neutral(field):  # neutral commits (plan 0409 D15): no plan mark in the body, no trailers
                body = body.replace(BODY, BODY_NEUTRAL, 1)
            done = run(field, "commit", "-q", "-m", SUBJECT.format(n=n, s="" if n == 1 else "s"), "-m", body,
                       *origin.paragraph(field, [origin.YARD]), *FROM,
                       data="\0".join(c["path"] for c in carried))
        why = done.stderr.strip()[-300:] or "git failed" if done.returncode else ""
    except (OSError, subprocess.SubprocessError) as e:
        why = str(e)
    if why or not carried:
        undo(field, placed)
        return None, ([] if why else same), why
    commit = acc = run(field, "rev-parse", "HEAD").stdout.strip()
    for car in cars:
        acc, files = trial.merge(field, acc, car["head"])
        if acc is None or files:
            run(field, "reset", "-q", "--keep", f"{commit}~1")
            return None, [], f"car {car['field']} would not merge onto the yard's commit ({', '.join(files[:3])})"
    return commit, sorted(carried + same, key=lambda c: c["path"]), ""


def settle(yard: str, carried: list[dict], default: str = "origin/main") -> dict:
    """After the green landing: {"dropped": [path], "kept": [{path, why}], "pulled": bool, "why": str}. A carried
    path is dropped (a tracked one restored to HEAD, a new one removed) only when its content in the yard and in
    the barn both still have the carried hash and the index holds nothing else; then `git pull --ff-only`. When
    that is no fast-forward, what was dropped is put back from the barn (the same content) and kept: the yard is
    as it was. A yard `survey` would skip is not touched at all."""
    out = {"dropped": [], "kept": [], "pulled": False, "why": ""}
    skipped = survey(yard, default)["skipped"]
    if skipped or not carried:
        out.update(kept=[{"path": c["path"], "why": skipped} for c in carried if skipped], why=skipped or "")
        return out
    paths = [c["path"] for c in carried]
    barn, head = objects(yard, default, paths), objects(yard, "HEAD", paths)
    index = {row.split("\t", 1)[1]: row.split()[1]
             for row in run(yard, "ls-files", "-s", "-z").stdout.split("\0") if "\t" in row}
    for c in carried:
        path, want = c["path"], c.get("hash")
        why = ("changed meanwhile" if blob(yard, path) != want
               else "the barn does not hold what was carried" if barn.get(path, (None,))[0] != want
               else "staged differently meanwhile" if index.get(path) not in (None, want, head.get(path, (None,))[0])
               else "")
        out["kept"].append({"path": path, "why": why}) if why else out["dropped"].append(path)
    tracked = [p for p in out["dropped"] if p in head]
    new = [p for p in out["dropped"] if p not in head]
    if tracked:
        run(yard, "checkout", "-q", "HEAD", *FROM, data="\0".join(tracked))
    if new:
        run(yard, "rm", "-q", "--cached", "--ignore-unmatch", *FROM, data="\0".join(new))
    for path in new:
        if os.path.lexists(os.path.join(yard, path)):
            os.unlink(os.path.join(yard, path))
    remote, _, name = default.partition("/")
    pull = run(yard, "pull", "-q", "--ff-only", remote, name)
    out.update(pulled=pull.returncode == 0, why="" if pull.returncode == 0 else pull.stderr.strip()[-300:])
    if pull.returncode and out["dropped"]:
        there = [c["path"] for c in carried if c["path"] in out["dropped"] and c.get("hash")]
        if there:
            run(yard, "restore", f"--source={default}", "--worktree", *FROM, data="\0".join(there))
        for path in set(out["dropped"]) - set(there):
            if os.path.lexists(os.path.join(yard, path)):
                os.unlink(os.path.join(yard, path))
        out["kept"] += [{"path": p, "why": "put back: the yard was not fast-forwarded"} for p in out["dropped"]]
        out["dropped"] = []
    return out
