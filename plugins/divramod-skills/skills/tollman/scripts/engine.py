#!/usr/bin/env python3
"""The train engine's changes (hal2 plan 0294 step 6, D8, D10, D12, D22, D23): what `trains.py` plans, done. One
function and one verb per change of a train, each writing its line of the train state (`train_state.py`), so
whoever follows the trains (the message board, step 7) hooks in here and nowhere else. The tick runs the verbs as
its `run` actions; none waits for CI.

  engine.py form --cars <json> [--alone-next <field> ...] [--repo <field>]
      in the train's own worktree `tollman-train-<plan>-...` beside the tollman's field, on its head with the barn's
      (train_wt.py, plan 0375 D5; every later verb runs there, its branch the carrier; a breakup, the asleep round's
      drop and the landed train drop it through the never-delete proof): the yard's uncommitted work as the first car (yard.py:
      what it can place, one commit; it never fails a train; engine_yard.py), then each car's head merged in
      order (a merge commit per car, frozen.merge_car), the CURRENT_PLAN pointer written (`yard` and the cars' plan names
      joined by ` + `: the land run's title; its bracket shows the cars' worktrees, `[02|03]`, the yard as `main`, never this field, plan 0352), then
      `restart`. Before the cars the field's remote branch goes back on its head when an earlier train's end left that
      train there (carrier.py, plan 0313 step 14). Nothing undoes a forming (plan 0610 E25, engine_form.py): a car that
      does not merge waits `resolving` with its resolve order, a failed regenerate or a refused mark leaves the train
      `formed` for the next restart; one whose conflicts are all generated files takes the barn's side, and the train's
      last commit writes them again (generated.py, plan 0313 step 8). `--alone-next`: the alone cars that ride alone
      next (plan 0610 D15). The minimum of hitched fields (trains.MIN_HITCHED) is the round's: this verb by hand, the
      user's `land now`, is never bound by it
  engine.py restart [--repo <field>]
      under the hold (hold.py, L88) nothing; else mark the train (`queue train`), start its landing detached (`land`
      stamps its pid, D2); also after an interrupted landing, a `retry` (one empty commit) and a train never started;
      first the cars the carrier lacks (a form that died, a car joined outside a landing, plan 0610 D17) merged by
      resolve_train.merge_rest (a conflict waits `resolving` with its resolve order); 75 while the last start's
      process lives after its red was taken (plan 0522 D17); a train with a car whose light checks are red and that
      has no fix order yet goes `red` (`proof_red`) instead, its fix orders first (proof_orders.py, the user
      2026-11-04: every hitched wagon rides); one past its checks that starts nothing: `attempt` (plan 0620 D5)
  engine.py land [--repo <field>]
      the detached process: first the train's pretest (pretest_train.py, plan 0349 D75: a red one prints the result
      `pretest_red` and no landing starts), then the wait until the land run before has finished and the answered
      post-merge fixes merged (next_train.py, plan 0383 step 6), then `hal2-cli-git worktree merge-to-main --json`
      as its child, on the train's own branch (train_branch.py, plan 0383 D2; hal2-git names it from the mark and
      `restart` records what `land-ref` says, plan 0607 D6). It stays that landing's parent until it ends, because
      a merge-to-main whose starter is gone ends `interrupted`. Right before it the unchanged-head guard (head_guard.py, plan 0560 D5): the head of
      the last red run of the train is refused (`tollman: refused`, the result `refused`, exit 1), any other is
      written as the `push` line; before both open_train.stops: a car that joined and waits for its resolve, is
      unmerged or has red light checks holds the push (plan 0610 E5, E6); then, on the train's first run only, the
      tollman's and the farmer's own branches merged as its last two cars (role_cars.py, plan 0610 D18); a train
      stopped by a role car left out twice in a row never pushes (D24)
  engine.py landed [--run <url>] [--commit <sha>] [--repo <field>]
      the train is in the barn: the field fast-forwarded, CURRENT_PLAN gone (its worktree dropped later, L135); the
      yard's carried files dropped where still the same, the yard fast-forwarded; a store farm's `sync --if-due landing`
  engine.py red --status <status> [--run <url>] [--why <text>] [--repo <field>]
      the landing did not land; the train waits, frozen, for its fix or the session's `retry` (no wait limit, D7)
  engine.py breakup --why <text> [--by-user --words <the user's words>] [--repo <field>]
      without a train: a leftover mark cleared. A train that stands is frozen (plan 0360 D3, frozen.py): refused,
      unless `--by-user`, the user's own command: then it is no more: its mark cleared, the queue its failed landing
      holds released, the field back on the head it had before the cars, and its remote branch too (carrier.py)
  engine.py unhitch <field> ... | retry ...      a car, a red train (engine_car.py)

Exit 0 done (also nothing to do), 1 the change was refused or failed (the tick wakes the session), 75 waits (OFFLINE).
"""

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import adopt
import bounded
import frozen
import head_guard
import hold
import land_name
import mirror
import mtm_scan
import next_train
import open_train
import origin
import pretest_train
import proof_orders
import role_cars
import train_branch
import train_state
import train_wt
import workqueue_hold
from carrier import Done, git, push_base
from engine_yard import settle_yard
from tick import OFFLINE, default_ref
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
    """Start `land` (`--land-ref ref` only when one is given) in a session of its own (no terminal, no
    parent that waits), its output in `log`: its pid."""
    with log.open("w") as out:
        argv = [sys.executable, str(Path(__file__).resolve()), "land", "--repo", top, *(["--land-ref", ref] if ref else [])]
        p = subprocess.Popen(argv, cwd=top, env={**os.environ, adopt.SPAWNED: "1"},  # adopt.direct: only this child
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


def form(top: str, cars: list[dict], now: dt.datetime | None = None, alone_next=()) -> Done:
    """The train of `cars` formed (engine_form.py: never cleared again, plan 0610 E25)."""
    import engine_form  # it calls back into this module (here, fetch)
    return engine_form.form(top, cars, now, alone_next)


def restart(top: str, now: dt.datetime | None = None) -> Done:
    main, field, train, top = here(top)
    if not train or (gone := train_wt.astray(top, train)):
        return 1, gone if train else "no train stands: nothing to land"
    if train_state.alive(pid := train["pid"]):  # its landing runs, or still ends after a red taken from its run (D17)
        return (0, f"train {train['train']}: its landing runs (pid {pid})") if train["state"] == "landing" else (
            OFFLINE, f"train {train['train']}: its last landing (pid {pid}) still ends: never a second one beside it")
    if entry := adopt.live(top, field):  # a landing the state does not know (a hand-typed land): adopted, never doubled
        return adopt.adopt(main, field, train, entry, now)
    if held := hold.of(main):  # L88: read again right before the start, never the round's earlier reading
        return 0, f"train {train['train']} not started: {hold.text(held)}"
    if frozen.lacking(top, train):
        import resolve_train  # a form that died between its lines, a car joined outside a landing (plan 0610 D17):
        return resolve_train.merge_rest(top, now)  # merged in order, a conflict waits `resolving`; then this again
    red = proof_orders.red_line(main, field, train, now)  # a car's light checks are red: fixed in the train first
    code, text = (0, red) if red else start(main, field, train, top, now)  # (proof_orders.py), never pushed so
    if red or code:  # plan 0620 D5: a try that started nothing raises the attempt, so the next round's key is new
        train_state.attempted(main, field, train, now)
    return code, text


def start(main: str, field: str, train: dict, top: str, now: dt.datetime | None = None) -> Done:
    """`restart` past its checks and its cars' light checks: the train marked and its landing spawned."""
    code, commit = fresh(top, train) if train["state"] == "retry" and not train["fixed"] else (0, None)  # a fix merged
    if code:
        return 1, f"train {train['train']} was not retried: {commit[-300:]}"
    if not train_branch.numbered(train):  # plan 0607 D4: hal2-git names no landing branch without the numbered mark
        return 1, f"train {train['train']} not started: it has no number (formed before plan 0398), so no land branch"
    if (named := train_wt.to_run(top, train["number"], train["starts"] + 1))[0]:
        return 1, f"train {train['train']} not started: {named[1]}"  # the carrier's branch is its run's (D18)
    code, out = cli(["worktree", "queue", "train", field, *(c["field"] for c in train["cars"]), *train_branch.mark(train),
                     "--json"], top)
    if code:
        return 1, f"train {train['train']} was not marked: {out[-300:]}"
    ref, why = land_name.next_ref(top)  # the branch hal2-git pushes this start to, asked after the mark (plan 0607 D6)
    if ref is None:
        return 1, f"train {train['train']} was not named: {why}"
    log = train_state.folder(main) / train_state.LOG
    pid = spawn(top, log, None)  # the numbered mark names its own branch: no --land-ref
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
    (`--land-ref`, plan 0383 D2), as this process's child: its output goes where this process's does (the log).
    The workqueue hold covers only the pretest, the train's local work (plan 0467), and none for a train through
    merge-to-main-cloud (D37): the wait holds nothing, and the landing's own step-scoped hold (hal2-git's hold_step)
    governs the merge-to-main."""
    code, out = cli(["worktree", "queue", "train", Path(top).name, "--pid", str(os.getpid()), "--json"], top)
    print(*["tollman: the train's pid is not on its mark:", out[-200:]] * bool(code), flush=True)
    argv = LAND + ["--land-ref", ref] * bool(ref)
    if land_name.refuses(top, ref):  # only the branch hal2-git names for the mark, checked before the pretest and the push
        return 1
    with workqueue_hold.landing_hold(top):
        if pretest_train.before_landing(top):
            return 1
    next_train.before_push(top)
    # a joined car's resolve, merge or fix first (plan 0610 E5, E6); L88: the hold's last look; then the role cars, the
    # train's last, once on its first run (role_cars.py, plan 0610 D18); plan 0560 D5: never the head of the train's
    # last red run again (head_guard.py)
    if code := open_train.stops(top) or hold.stops(top):
        return code
    if code := role_cars.merge(top):  # its lines printed; a stopped train (plan 0610 D24) never pushes
        return code
    return head_guard.refuses(top) or land_name.refuses(top, ref) or subprocess.run(argv, cwd=top).returncode


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
    # its worktree stays until the next train formed: the chain's end drops it detached (train_wt.later, L135)
    if home:
        behind += (f"; the yard: {len(home['dropped'])} carried files dropped, {len(home['kept'])} kept, "
                   + ("fast-forwarded" if home["pulled"] else f"not fast-forwarded ({home['why']})"))
    if planread.sync(main, "landing") is not None:
        behind += "; the plan store synced"  # the cars' plans reach the state ref (nothing in the files home)
    behind += mirror.publish(main)  # a public farm's snapshot mirror, from this machine (plan 0409 step 15)
    return 0, f"train {train['train']} is in the barn{behind}"


def red(top: str, status: str, run: str | None = None, why: str = "", now: dt.datetime | None = None) -> Done:
    main, field, train, _ = here(top)
    if not train or train["state"] != "landing":  # `fixed` wrote it already (L108): never a second red line
        return 0, f"no landing train stands ({(train or {}).get('state', 'none')})"
    train_state.append(main, "red", field, now, train=train["train"], status=status, run=run, why=why,
                       head=train.get("head"))  # this start's push: the head of a red run (head_guard.py)
    return 0, f"train {train['train']} is red ({status}): frozen, it waits for its fix or `retry` (plan 0360 D3, D7)"


def breakup(top: str, why: str, now: dt.datetime | None = None, user: bool = False, words: str = "") -> Done:
    """The verb: a leftover mark cleared; a train that stands only on the user's own word (frozen.py), `--words`
    with it (plan 0611 D13), save the round's breakup of a train the user split (its unhitch is the record)."""
    main, _, train, _ = here(top)
    if train and not user:
        return 1, frozen.refused(train, "a breakup")
    split = bool(train) and train["state"] == "split" and frozen.by_user(train)
    if user and not words.strip() and not split:
        return 1, "no breakup: `--by-user` needs `--words \"<the user's words>\"` (plan 0611 D13)"
    code, text = clear(top, why, now)
    if user and words.strip() and not code:
        import records_kinds  # the user's order, open until code sees its effect (plan 0611)
        name = (train or {}).get("train")
        records_kinds.add(main, "user-order", (train or {}).get("carrier") or "-", f"break up train {name}: {why}",
                          "user", records_kinds.train_event("cleared", train=name), now, words=words.strip(),
                          train=name, order="breakup")
    return code, text


def clear(top: str, why: str, now: dt.datetime | None = None) -> Done:
    """The train or the leftover mark gone (the user's breakup, the asleep round's drop; never a forming, plan 0610
    E25), and with it the train's worktree (train_wt.drop: only through the proof)."""
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
    sub.choices["form"].add_argument("--alone-next", nargs="*", default=[])
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
        sub.choices[verb].add_argument("--words", default="", help="the user's own words (plan 0611 D13)")
    sub.choices["retry"].add_argument("--skip-pretest", action="store_true")
    a = p.parse_args(argv)
    found, shown = git(a.repo, "rev-parse", "--show-toplevel")
    top = a.repo if found else shown
    if a.verb == "land":
        if adopt.direct():  # only restart's spawn starts a landing: it marks the train and writes its started line
            print(adopt.REFUSED, file=sys.stderr)
            return 2
        return land(top, a.land_ref)
    import engine_car  # its verbs call back into this module (here, cli)
    code, text = {"form": lambda: form(top, a.cars, alone_next=a.alone_next), "restart": lambda: restart(top),
                  "landed": lambda: landed(top, a.run, a.commit), "red": lambda: red(top, a.status, a.run, a.why),
                  "breakup": lambda: breakup(top, a.why, user=a.by_user, words=a.words),
                  "unhitch": lambda: engine_car.unhitch(top, a.field, a.why, user=a.by_user, words=a.words),
                  "retry": lambda: engine_car.retry(top, a.why, skip_pretest=a.skip_pretest)}[a.verb]()
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
