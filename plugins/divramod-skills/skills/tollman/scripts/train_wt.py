"""A train's own worktree (hal2 plan 0375 D5, D8): every train forms in a worktree `tollman-train-<plan>-<plan>...`
beside the tollman's field, named by its cars' plan numbers in order (a car without a plan: `f<field>`; at most 64
characters, L104), its branch
of the same name the carrier: the queue's ticket, the landing's `land/<name>` and the train state's `slot` are its.
The tollman's own field only starts it (its head is the worktree's start) and never holds a train's commits.

- `add`: the worktree created at the field's head; one of the same name left from before is dropped first, through
  the proof, or no train forms (the session is woken)
- `carrier`: where a train's verbs run, the standing train's worktree (the `formed` line's `worktree`), else the
  field itself (a train formed before plan 0375 stands in it)
- `unsaved`: the never-delete-unsaved-work proof: nothing uncommitted, and every commit outside the barn and the
  other origin branches is the train's own, a merge (a car's, a fix order's, the barn's) or a commit only a train
  makes (`chore(wagon-train)`, `chore(generated)`, `chore(yard)`: the cars' work lives on in their fields, the yard's
  files in the yard)
- `drop`: the worktree and its branch removed once the proof is empty (a breakup, the asleep round's drop, a landed
  train); otherwise kept and why said, never forced. Then `sweep`: origin's train branches no local branch holds
  and whose tip is in the barn deleted with a lease, in a detached push (L55)
- `later`: a landed train's worktree is dropped after the next train formed, outside the round (L135: a `git worktree
  remove` of a full build tree took 6+ min inside the round and held train 29 back): the chain's end starts one
  detached `train_wt.py drop-left` (setsid, never nohup: L111), which `drop`s every train worktree beside the field
  but the standing train's and those made after it started, one run at a time (a lock), its lines in
  `train-drop.log`; the prune duty's `retry` starts it again while one is left (a failed drop never blocks a train)

  train_wt.py later --repo <field>                      start the detached drop run, return at once
  train_wt.py drop-left --repo <field> --since <epoch>  the run itself (what `later` starts)
"""

import argparse
import fcntl
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import lead_marker
import mtm_scan
import train_state
from carrier import KEEPALIVE, Done, git
from tick import act, default_ref

PREFIX = "tollman-train-"
CURRENT = "CURRENT_PLAN"  # the pointer's name (hal2 plan 0409 step 12)
OWN_FIX = PREFIX + "fix"
OWN_COMMITS = ("chore(wagon-train)", "chore(generated)", "chore(yard)")  # what only a train commits
MAX = 64  # hal2-git's longest slot name (L104)
SPAWN = subprocess.Popen  # sweep's detached push (a test runs it to its end)
DETACH = subprocess.Popen  # later's detached drop run (a test runs it in its own process)
DROP_LOG, DROP_LOCK = "train-drop.log", "train-drop.lock"  # in the tollman's state folder
LOG_MAX = 1 << 20  # the drop log starts over past this
RETRY = 3600  # the prune duty starts the drop run again at most this often while a train worktree is left


def is_train(slot) -> bool:
    """A train's worktree (and branch); `tollman-train-fix` is the tollman's own fix branch (orders.OWN_FIX), none."""
    return str(slot or "").startswith(PREFIX) and slot != OWN_FIX


def ours(slot, own: str) -> bool:
    """A car's `rides_with` that is no other carrier's: none, the tollman's field or a train's worktree."""
    return slot in (None, own) or is_train(slot)


def ticket(tickets: list[dict], own: str, train: dict | None) -> dict:
    """The carrier's ticket: the standing train's; between trains the field's own, else a train's worktree left with
    a mark (its process died before its end took the mark: broken up there, `left`)."""
    mine = next((t for t in tickets if t.get("slot") == ((train or {}).get("carrier") or own)), {})
    if train or mine.get("train"):
        return mine
    return next((t for t in tickets if is_train(t.get("slot")) and t.get("train")
                 and Path(t.get("worktree") or "-").is_dir()), mine)


def left(mine: dict, train: dict | None, top: str) -> str:
    """Where a breakup runs: a leftover mark's worktree, else the field `top` (the engine finds the train's)."""
    return mine["worktree"] if not train and is_train(mine.get("slot")) else top


def name(cars: list[dict]) -> str:
    """`tollman-train-` and each car's plan number in order (`0375-tollman-switch`: 0375), else `f<field>`; over
    MAX (hal2-git's slot limit, L104: a 23-car train's 135 chars broke its form) `tollman-train-big-<first>-<last>-<n>`."""
    parts = [m[1] if (m := re.match(r"(\d+)-", c.get("plan") or "")) else f"f{c['field']}" for c in cars]
    full = PREFIX + "-".join(parts)
    return full if len(full) <= MAX else f"{PREFIX}big-{parts[0]}-{parts[-1]}-{len(parts)}"[:MAX]


def folder(train: dict | None, top: str) -> str:
    """The folder the train's verbs run in: its worktree while it is there, else `top` (the tollman's field)."""
    wt = (train or {}).get("worktree")
    return wt if wt and Path(wt).is_dir() else top


def carrier(top: str) -> str:
    """`folder` of the train that stands now, seen from the field `top`."""
    return folder(train_state.standing(train_state.lines(mtm_scan.main_checkout(top))), top)


def astray(top: str, train: dict | None) -> str:
    """Why `top` is not the standing train's carrier (its worktree is gone), or "": its git is never touched then."""
    if train and Path(top).name != train["carrier"]:
        return f"the worktree of train {train['train']} ({train.get('worktree') or train['carrier']}) is gone"
    return ""


def foreign(cwd: str, rev: str, branch: str) -> list[str]:
    """The commits of `rev` outside the barn and every origin branch but the train's own (`<branch>`,
    `land/<branch>`) that are no train's: neither a merge nor a commit only a train makes."""
    code, out = git(cwd, "log", "--format=%H %P%x09%s", rev, "--not", default_ref(cwd), f"--exclude=origin/{branch}",
                    f"--exclude=origin/land/{branch}", "--remotes")
    if code:
        return [f"its commits not read: {out[-200:]}"]
    left = [line.split()[0][:12] for line in out.splitlines() if line.strip()
            and len(line.split("\t")[0].split()) < 3 and not line.split("\t", 1)[-1].startswith(OWN_COMMITS)]
    return [f"{len(left)} commit(s) of no train and on no other origin branch: {', '.join(left[:5])}"] if left else []


def unsaved(wt: str) -> list[str]:
    """Why the worktree `wt` may not go (the proof), [] when nothing of it would be lost."""
    code, top = git(wt, "rev-parse", "--show-toplevel")
    if code or Path(top).resolve() != Path(wt).resolve():
        return [f"{wt} is no worktree of its own: {top[-200:]}"]
    code, status = git(wt, "status", "--porcelain")
    if code or status:
        return [f"{len(status.splitlines())} uncommitted change(s)" if not code else f"status not read: {status[-200:]}"]
    return foreign(wt, "HEAD", git(wt, "branch", "--show-current")[1] or Path(wt).name)


def drop(wt: str) -> Done:
    """The train's worktree and its branch gone, through the proof; kept (exit 1) when it finds anything."""
    path = Path(wt)
    if not is_train(path.name):
        return 1, f"{path.name} is no train's worktree: never dropped"
    if not path.is_dir():
        return 0, f"worktree {path.name} is gone already"
    lead_marker.pointers.remove(path, CURRENT)  # the train's title (frozen.write_current), none of a car's work
    if why := unsaved(wt):
        return 1, f"worktree {path.name} kept (never delete unsaved work): {'; '.join(why)}"
    main, branch = mtm_scan.main_checkout(wt), git(wt, "branch", "--show-current")[1]
    code, out = git(main, "worktree", "remove", str(path))
    if code:
        return 1, f"worktree {path.name} not removed: {out[-200:]}"
    code, out = git(main, "branch", "-D", branch) if branch else (0, "")
    swept = sweep(main)
    return 0, f"worktree {path.name} dropped" + (f", its branch kept: {out[-200:]}" if code else "") + swept


def landed(main: str) -> dict[str, str]:
    """{branch: tip} of origin's train branches as this repository last saw them (no network) that no local branch
    holds any more and whose tip is in the barn: a landed or dropped train's, nothing of it lost (L55)."""
    code, out = git(main, "for-each-ref", "--format=%(refname:lstrip=3) %(objectname)", f"refs/remotes/origin/{PREFIX}*")
    barn, found = default_ref(main), {}
    for branch, tip in (line.split() for line in (out.splitlines() if code == 0 else []) if len(line.split()) == 2):
        if is_train(branch) and git(main, "rev-parse", "-q", "--verify", f"refs/heads/{branch}")[0] \
                and git(main, "merge-base", "--is-ancestor", tip, barn)[0] == 0:
            found[branch] = tip
    return found


def sweep(main: str) -> str:
    """origin's landed train branches (`landed`) deleted, each leased on the tip seen, in one detached push: the
    landed train's round never waits for it (D9); a branch that moved since is refused by its lease and stays."""
    gone = landed(main)
    if not gone:
        return ""
    leases = [f"--force-with-lease=refs/heads/{b}:{tip}" for b, tip in gone.items()]
    SPAWN(["git", "push", "-q", "--no-verify", *leases, "origin", *(f":refs/heads/{b}" for b in gone)], cwd=main,
          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
          env={**os.environ, "GIT_SSH_COMMAND": os.environ.get("GIT_SSH_COMMAND") or KEEPALIVE})
    return f"; origin's landed train branches deleted: {', '.join(sorted(gone))}"


def add(top: str, cars: list[dict]) -> Done:
    """The train's worktree beside the field `top`, on a new branch at `top`'s head: (0, its path) or (1, why)."""
    wt = Path(top).parent / name(cars)
    git(top, "worktree", "prune")
    if wt.exists() and (left := drop(str(wt)))[0]:
        return 1, f"a train's worktree is left from before, no train formed: {left[1]}"
    if git(top, "rev-parse", "-q", "--verify", f"refs/heads/{wt.name}")[0] == 0:  # a branch without its worktree
        if why := foreign(top, f"refs/heads/{wt.name}", wt.name):
            return 1, f"branch {wt.name} is left from before and kept (never delete unsaved work): {why[0]}"
        git(top, "branch", "-D", wt.name)
    code, out = git(top, "worktree", "add", "-q", "-b", wt.name, str(wt), "HEAD")
    return (0, str(wt)) if code == 0 else (1, f"worktree {wt.name} not added: {out[-300:]}")


def leftovers(top: str, train: dict | None) -> list[Path]:
    """The train worktrees beside the field `top` but the standing train's: a directory listing, no git."""
    keep = {(train or {}).get("carrier"), Path((train or {}).get("worktree") or "-").name}
    return sorted(p for p in Path(top).parent.glob(PREFIX + "*") if is_train(p.name) and p.name not in keep
                  and p.is_dir())


def left_now(top: str, main: str) -> list[Path]:
    """`leftovers` beside the train that stands now (the train state read again)."""
    return leftovers(top, train_state.standing(train_state.lines(main)))


def later(top: str) -> str:
    """The drop of the train worktrees left beside `top`, started detached (L135): never waited for."""
    main = mtm_scan.main_checkout(top)
    if not (left := left_now(top, main)):
        return ""
    argv = [sys.executable, str(Path(__file__).resolve()), "drop-left", "--repo", top, "--since", str(time.time())]
    path = train_state.folder(main) / DROP_LOG
    try:
        with path.open("a" if not path.exists() or path.stat().st_size < LOG_MAX else "w") as log:
            DETACH(argv, cwd=top, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as e:  # never fails the chain: the prune duty tries again
        return f"not dropped yet ({e}), the prune duty tries again: {', '.join(p.name for p in left)}"
    return f"dropping in the background: {', '.join(p.name for p in left)}"


def drop_left(top: str, since: float) -> list[str]:
    """`drop-left`: each leftover `drop`ped through the proof, under the drop lock (busy: another run does it); a
    worktree that stands as the train now or was made after `since` (a train formed meanwhile) is never touched."""
    main = mtm_scan.main_checkout(top)
    with (train_state.folder(main) / DROP_LOCK).open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return ["another drop run goes on"]
        done = []
        for wt in left_now(top, main):
            made = (wt / ".git").stat().st_mtime if (wt / ".git").exists() else 0.0
            if made > since or wt not in left_now(top, main):  # a train formed meanwhile: never touched
                continue
            done.append(f"{train_state.utc()} {drop(str(wt))[1]}")
        return done


def retry(top: str, main: str) -> list[dict]:
    """The prune duty's retry while a train worktree is left (a drop that failed or never started), once per RETRY."""
    if not any(is_train(p.name) for p in Path(top).parent.glob(PREFIX + "*")):
        return []  # the round's usual case: one listing, no read of the train state
    if not (left := [p.name for p in left_now(top, main)]):
        return []
    argv = [sys.executable, str(Path(__file__).resolve()), "later", "--repo", top]
    return [act("prune", "train-drop", "run", key=f"train-drop:{','.join(left)}", window=RETRY, argv=argv, cwd=top,
                text=f"train worktrees left beside the field, dropped in the background: {', '.join(left)}")]


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("later").add_argument("--repo", required=True)
    left = sub.add_parser("drop-left")
    left.add_argument("--repo", required=True)
    left.add_argument("--since", type=float, required=True)
    a = p.parse_args(argv)
    lines = [later(a.repo) or "no train worktree is left"] if a.cmd == "later" else drop_left(a.repo, a.since)
    print(*lines, sep="\n", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
