#!/usr/bin/env python3
"""The train engine's changes (hal2 plan 0294 step 6, D8, D10, D12, D22, D23): what `trains.py` plans, done. One
function and one verb per change of a train, each writing its line of the train state (`train_state.py`), so
whoever follows the trains (the message board, step 7) hooks in here and nowhere else. The tick runs the verbs as
its `run` actions; none waits for CI.

  engine.py form --cars <json> [--repo <field>]
      in the train's own worktree `tollman-train-<plan>-...` beside the tollman's field, on its head with the barn's
      (train_wt.py, plan 0375 D5; every later verb runs there, its branch the carrier; a breakup, the asleep round's
      drop and the landed train drop it through the never-delete proof): the yard's uncommitted work as the first car (yard.py:
      what it can place, one commit; it never fails a train; engine_yard.py), then each car's head merged in
      order (a merge commit per car, frozen.merge_car), the CURRENT_PLAN pointer written (`yard` and the cars' plan names
      joined by ` + `: the land run's title; its bracket shows the cars' worktrees, `[02|03]`, the yard as `main`, never this field, plan 0352), then
      `restart`. Before the cars the field's remote branch goes back on its head when an earlier train's end left that
      train there (carrier.py, plan 0313 step 14). A car that does not merge, or a mark the queue refuses, undoes this
      call's forming (`clear`; the last drop-out before the train is frozen, plan 0360 D3); one whose conflicts are all
      generated files takes the barn's side, and the train's last commit writes them again (generated.py, plan 0313
      step 8; a command that fails undoes the forming too)
  engine.py restart [--repo <field>]
      mark the train (`hal2-cli-git worktree queue train`), then start its landing detached (`land`, which stamps
      its own pid on the mark: `queue train <carrier> --pid`, so the tollman's sleep stops it, D2), its output in
      train-landing.log, its pid in the state; also after an interrupted landing (the rerun adopts the run) and
      after the session's `retry`, which first gives the field one empty commit: a new candidate, a fresh run; for a
      train formed but never started (its form died) first the cars the field lacks (frozen.complete): the same train
  engine.py land [--land-ref <train-...>] [--repo <field>]
      the detached process: first the train's pretest (pretest_train.py, plan 0349 D75: a red one prints the result
      `pretest_red` and no landing starts), then the wait until the land run before has finished and the answered
      post-merge fixes merged (next_train.py, plan 0383 step 6), then `hal2-cli-git worktree merge-to-main --json
      --land-ref <name>` as its child, on the train's own branch `land/<name>` (train_branch.py, plan 0383 D2;
      `restart` names it). It stays that landing's parent until it ends, because a merge-to-main whose starter is
      gone ends `interrupted`
  engine.py landed [--run <url>] [--commit <sha>] [--repo <field>]
      the train is in the barn: the field fast-forwarded to it, the CURRENT_PLAN pointer gone; the files the yard's
      car carried leave the yard where they are still the same, and the yard is fast-forwarded (yard.settle); in a
      farm whose plans live in its store, its sync trigger (`sync --if-due landing`, the plan skill's planread.py)
  engine.py red --status <status> [--run <url>] [--why <text>] [--repo <field>]
      the landing did not land; the train waits, frozen, for its fix or the session's `retry` (no wait limit, D7)
  engine.py breakup --why <text> [--by-user] [--repo <field>]
      without a train: a leftover mark cleared. A train that stands is frozen (plan 0360 D3, frozen.py): refused,
      unless `--by-user`, the user's own command: then it is no more: its mark cleared, the queue its failed landing
      holds released, the field back on the head it had before the cars, and its remote branch too (carrier.py)
  engine.py unhitch <field> ... | retry ...      a car, a red train (engine_car.py)

Exit 0 done (also nothing to do), 1 the change was refused or failed (the tick wakes the session).
"""

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import bounded
import frozen
import generated
import mirror
import mtm_scan
import next_train
import origin
import pretest_train
import train_branch
import train_state
import train_wt
import workqueue_hold
from carrier import Done, git, push_base
from engine_yard import load_yard, settle_yard
from tick import default_ref
from skillpath import load  # noqa: E402  (farmer_frame put the skills unit's scripts/ on the path)

planread = load("plan", "planread", __file__)  # the plan store's sync trigger (hal2 plan 0409 step 9)

HAL = "hal2-cli-git"
LAND = [HAL, "worktree", "merge-to-main", "--json"]
CURRENT = frozen.CURRENT
# A retried train's empty commit (plan 0313 step 13); a typed `chore(wagon-train)` line, its origin in trailers (plan 0355)
RETRY = "chore(wagon-train): land the train again on a fresh run (retry {n})"

def cli(args: list[str], cwd: str) -> Done:
    """hal2-cli-git, its exit code and output."""
    try:
        p = bounded.run([HAL, *args], cwd=cwd)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)
    return p.returncode, (p.stdout + p.stderr).strip()


def spawn(top: str, log: Path, ref: str | None) -> int:
    """Start `land` (`--land-ref ref` only for a train without a number) in a session of its own (no terminal, no
    parent that waits), its output in `log`: its pid."""
    with log.open("w") as out:
        argv = [sys.executable, str(Path(__file__).resolve()), "land", "--repo", top, *(["--land-ref", ref] if ref else [])]
        p = subprocess.Popen(argv, cwd=top,
                             stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    return p.pid


def here(top: str) -> tuple[str, str, dict | None, str]:
    """The main checkout, the carrier's name, the train that stands and the carrier's folder: the train's worktree
    while it is there, else `top` (train_wt.folder)."""
    main = mtm_scan.main_checkout(top)
    train = train_state.standing(train_state.lines(main))
    top = train_wt.folder(train, top)
    return main, Path(top).name, train, top


def fetch(top: str) -> str:
    """The barn's ref, fetched (offline: as it is known)."""
    default = default_ref(top)
    git(top, "fetch", "-q", "origin", default.removeprefix("origin/"))
    return default


def form(top: str, cars: list[dict], now: dt.datetime | None = None) -> Done:
    main, _, train, _ = here(top)
    if train:
        return 0, f"train {train['train']} stands ({train['state']}): no second one"
    if not cars:
        return 1, "a train needs a car"
    default = fetch(top)
    code, top = train_wt.add(top, cars)  # the train's own worktree on the field's head (plan 0375 D5)
    if code:
        return 1, top
    field = Path(top).name
    behind = git(top, "merge-base", "--is-ancestor", default, "HEAD")[0]
    taken = []  # generated files whose conflict took the barn's side (generated.py, plan 0313 step 8)
    if behind and git(top, "merge", "-q", "--no-edit", default)[0] and not (taken := generated.take(top, "--theirs")):
        git(top, "merge", "--abort")
        return 1, f"{default} does not merge into {field}: no train formed; {train_wt.drop(top)[1]}"
    name = "+".join(c["field"] for c in cars) + "@" + train_state.utc(now)
    number = train_state.next_number(main)  # plan 0398 D4: the train's number, the land branch `train-<n>-<a>`
    branch, base = git(top, "branch", "--show-current")[1] or field, git(top, "rev-parse", "HEAD")[1]
    pushed = push_base(top, field, base)  # a dead train an earlier end left on the remote (plan 0313 step 14)
    train_state.append(main, "formed", field, now, train=name, number=number, cars=cars, base=base, worktree=top,
                       **({"pushed": pushed} if pushed else {}))
    told = f"; {pushed}" if pushed else ""
    rides, note = load_yard(top, main, default, name, cars, now)
    for car in cars:
        code, out, got = frozen.merge_car(top, branch, car)
        if code:
            broken = clear(top, f"car {car['field']} did not merge: {out[-300:]}", now)[1]
            return 1, f"car {car['field']} did not merge; {broken}{told}"
        taken += got
    if taken:  # the train's last commit: the generated files written again for its head, before the landing
        code, text, commit, files = generated.regenerate(top, sorted(set(taken)), [c["field"] for c in cars])
        train_state.append(main, "regenerated", field, now, train=name, commit=commit, files=files, why=text)
        if code:
            return 1, f"{text}; {clear(top, text, now)[1]}{told}"
    frozen.write_current(top, cars, bool(rides))
    code, text = restart(top, now)
    return (1, f"{text}; {clear(top, text, now)[1]}{told}") if code else (0, text + told + (f"; {note}" * bool(note)))


def restart(top: str, now: dt.datetime | None = None) -> Done:
    main, field, train, top = here(top)
    if not train or (gone := train_wt.astray(top, train)):
        return 1, gone if train else "no train stands: nothing to land"
    if train["state"] == "landing" and train_state.alive(train["pid"]):
        return 0, f"train {train['train']}: its landing runs (pid {train['pid']})"
    code, commit = fresh(top, train) if train["state"] == "retry" and not train["fixed"] else (0, None)  # a fix merged
    if code:
        return 1, f"train {train['train']} was not retried: {commit[-300:]}"
    code, done = frozen.complete(top, train) if train["state"] == "formed" else (0, "")
    if code:
        return 1, done
    code, out = cli(["worktree", "queue", "train", field, *(c["field"] for c in train["cars"]), *train_branch.mark(train),
                     "--json"], top)
    if code:
        return 1, f"train {train['train']} was not marked: {out[-300:]}"
    log, ref = train_state.folder(main) / train_state.LOG, train_branch.ref(train)
    pid = spawn(top, log, None if train_branch.numbered(train) else ref)  # a numbered mark names its own branch
    train_state.append(main, "started", field, now, train=train["train"], pid=pid, log=str(log), commit=commit,
                       land_ref=ref)
    return 0, f"train {train['train']}: landing started (pid {pid}, start {train['starts'] + 1})"


def fresh(top: str, train: dict) -> Done:
    """A retried train's new candidate (plan 0313 step 13, D19): hal2-git builds the landing's candidate as the
    same commit for the same HEAD on the same barn (`candidate_with`: HEAD's dates) and finds its land run by that
    commit, so a retry as it was adopted the red run again. One empty commit on the field makes the candidate new
    and its push a fresh run; none when HEAD is this retry's commit already (its mark was refused). The commit."""
    subject = RETRY.format(n=train["starts"])
    if git(top, "log", "-1", "--format=%s")[1] != subject:
        why = train.get("retried") or "a flaky gate"
        code, out = git(top, "commit", "-q", "--allow-empty", "-m", subject, "-m", f"Landed again on a fresh run: {why}",
                        *origin.paragraph(top, [c["field"] for c in train.get("cars") or []]))
        if code:
            return code, out
    return git(top, "rev-parse", "HEAD")


def land(top: str, ref: str | None = None) -> int:
    """Its pid on the mark (the sleep stops its group, plan 0375 D2), the pretest, the wait for the run before and
    the post-merge fixes (next_train.py, plan 0383 step 6), then the landing on the train's branch `ref`
    (`--land-ref`, plan 0383 D2), as this process's child: its output goes where this process's does (the log)."""
    code, out = cli(["worktree", "queue", "train", Path(top).name, "--pid", str(os.getpid()), "--json"], top)
    print(*["tollman: the train's pid is not on its mark:", out[-200:]] * bool(code), flush=True)
    argv = LAND + ["--land-ref", ref] * bool(ref)
    with workqueue_hold.landing_hold(top):
        if pretest_train.before_landing(top):
            return 1
        next_train.before_push(top)
        return subprocess.run(argv, cwd=top).returncode


def landed(top: str, run: str | None = None, commit: str | None = None, now: dt.datetime | None = None) -> Done:
    main, field, train, top = here(top)
    if not train:
        return 0, "no train stands"
    default = fetch(top)
    code, out = git(top, "merge", "-q", "--ff-only", default)  # the landing reset the field: this makes sure
    frozen.POINTERS.remove(top, CURRENT)
    home = settle_yard(main, train, default)
    train_state.append(main, "landed", field, now, train=train["train"], cars=[c["field"] for c in train["cars"]],
                       run=run, commit=commit, yard=home)
    behind = f"; {field} did not fast-forward: {out[-200:]}" if code else ""
    behind += f"; {train_wt.drop(top)[1]}" if train_wt.is_train(field) else ""  # in the barn: nothing of it is lost
    if home:
        behind += (f"; the yard: {len(home['dropped'])} carried files dropped, {len(home['kept'])} kept, "
                   + ("fast-forwarded" if home["pulled"] else f"not fast-forwarded ({home['why']})"))
    if planread.sync(main, "landing") is not None:
        behind += "; the plan store synced"  # the cars' plans reach the state ref (nothing in the files home)
    behind += mirror.publish(main)  # a public farm's snapshot mirror, from this machine (plan 0409 step 15)
    return 0, f"train {train['train']} is in the barn{behind}"


def red(top: str, status: str, run: str | None = None, why: str = "", now: dt.datetime | None = None) -> Done:
    main, field, train, _ = here(top)
    if not train:
        return 0, "no train stands"
    train_state.append(main, "red", field, now, train=train["train"], status=status, run=run, why=why)
    return 0, f"train {train['train']} is red ({status}): frozen, it waits for its fix or `retry` (plan 0360 D3, D7)"


def breakup(top: str, why: str, now: dt.datetime | None = None, user: bool = False) -> Done:
    """The verb: a leftover mark cleared; a train that stands only on the user's own word (frozen.py)."""
    train = here(top)[2]
    if train and not user:
        return 1, frozen.refused(train, "a breakup")
    return clear(top, why, now)


def clear(top: str, why: str, now: dt.datetime | None = None) -> Done:
    """The train or the leftover mark gone (the user's breakup, `form` undoing its own forming, the asleep round's
    drop), and with it the train's worktree (train_wt.drop: only through the proof)."""
    main, field, train, top = here(top)
    if train and train["state"] == "landing" and train_state.alive(train["pid"]):
        return 1, f"train {train['train']} lands (pid {train['pid']}): a running landing is never stopped"
    gone, field = train_wt.astray(top, train), (train or {}).get("carrier") or field
    code, out = cli(["worktree", "queue", "train", field, "--clear", "--json"], main)
    if code:
        return 1, f"the mark of {field} stays: {out[-300:]}"
    try:
        queue = json.loads(cli(["worktree", "queue", "--json"], main)[1]).get("queue", [])
    except (json.JSONDecodeError, AttributeError):
        queue = []
    if any(t.get("slot") == field and t.get("state") == "held" and not t.get("waits_for") for t in queue):
        cli(["worktree", "release", field, "--by", "the user", "--json"], main)  # the user's breakup: that candidate is gone
    pushed = ""
    if train and not gone:
        git(top, "merge", "--abort")
        code, out = git(top, "reset", "-q", "--keep", train["base"]) if train.get("base") else (0, "")
        frozen.POINTERS.remove(top, CURRENT)
        if code:
            return 1, f"{field} did not go back to {train['base']}: {out[-300:]}"
        pushed = push_base(top, field, train["base"]) if train.get("base") else ""
    train_state.append(main, "cleared", field, now, train=train["train"] if train else None, why=why,
                       **({"pushed": pushed} if pushed else {}))
    done = f"train {train['train']} broken up: {why}" if train else f"the mark of {field} cleared: {why}"
    code, dropped = train_wt.drop(top) if train_wt.is_train(Path(top).name) and not gone else (0, gone)
    return code, done + "".join(f"; {t}" for t in (pushed, dropped) if t)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="verb", required=True)
    for verb in ("form", "restart", "land", "landed", "red", "breakup", "unhitch", "retry"):
        sub.add_parser(verb).add_argument("--repo", default=".")
    sub.choices["form"].add_argument("--cars", required=True, type=json.loads)
    sub.choices["land"].add_argument("--land-ref")
    sub.choices["unhitch"].add_argument("field")
    for verb in ("landed", "red"):
        sub.choices[verb].add_argument("--run")
    sub.choices["landed"].add_argument("--commit")
    sub.choices["red"].add_argument("--status", required=True)
    sub.choices["red"].add_argument("--why", default="")
    for verb in ("breakup", "unhitch", "retry"):
        sub.choices[verb].add_argument("--why", required=True)
    for verb in ("breakup", "unhitch"):  # the user's own command (plan 0360 D3), never the session's
        sub.choices[verb].add_argument("--by-user", action="store_true")
    sub.choices["retry"].add_argument("--skip-pretest", action="store_true")
    a = p.parse_args(argv)
    found, shown = git(a.repo, "rev-parse", "--show-toplevel")
    top = a.repo if found else shown
    if a.verb == "land":
        return land(top, a.land_ref)
    import engine_car  # its verbs call back into this module (here, cli)
    code, text = {"form": lambda: form(top, a.cars), "restart": lambda: restart(top),
                  "landed": lambda: landed(top, a.run, a.commit), "red": lambda: red(top, a.status, a.run, a.why),
                  "breakup": lambda: breakup(top, a.why, user=a.by_user),
                  "unhitch": lambda: engine_car.unhitch(top, a.field, a.why, user=a.by_user),
                  "retry": lambda: engine_car.retry(top, a.why, skip_pretest=a.skip_pretest)}[a.verb]()
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
