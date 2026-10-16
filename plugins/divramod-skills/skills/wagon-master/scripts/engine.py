#!/usr/bin/env python3
"""The train engine's changes (hal2 plan 0294 step 6, D8, D10, D12, D22, D23): what `trains.py` plans, done. One
function and one verb per change of a train, each writing its line of the train state (`train_state.py`), so
whoever follows the trains (the message board, step 7) hooks in here and nowhere else. The tick runs the verbs as
its `run` actions; none waits for CI.

  engine.py form --cars <json> [--repo <field>]
      in the wagon master's field, on the barn's head: the yard's uncommitted work as the first car (yard.py:
      what it can place, one commit; it never fails a train), then each car's head merged in order (a merge
      commit per car), plans/CURRENT_PLAN written (`yard` and the cars' plan names joined by ` + `: the land run's
      title; its bracket shows the cars' worktrees, `[02|03]`, the yard as `main`, never this field, plan 0352), then
      `restart`. Before the cars the field's remote branch goes back on its head when an earlier train's end left that
      train there (carrier.py, plan 0313 step 14). A car that does not merge, or a mark the queue refuses, breaks the
      train up again; one whose conflicts are all generated files takes the barn's side, and the train's last commit writes them
      again (generated.py, plan 0313 step 8; a command that fails breaks the train up)
  engine.py restart [--repo <field>]
      mark the train (`hal2-cli-git worktree queue train`), then start its landing detached (`land`), its output in
      train-landing.log, its pid in the state; also after an interrupted landing (the rerun adopts the run) and
      after the session's `retry`, which first gives the field one empty commit: a new candidate, a fresh run
  engine.py land [--repo <field>]
      the detached process: first the train's pretest (pretest_train.py, plan 0349 D75: a red one prints the result
      `pretest_red` and no landing starts), then `hal2-cli-git worktree merge-to-main --json` as its child. It stays
      that landing's parent until it ends, because a merge-to-main whose starter is gone ends `interrupted`
  engine.py landed [--run <url>] [--commit <sha>] [--repo <field>]
      the train is in the barn: the field fast-forwarded to it, plans/CURRENT_PLAN gone; the files the yard's
      car carried leave the yard where they are still the same, and the yard is fast-forwarded (yard.settle)
  engine.py red --status <status> [--run <url>] [--why <text>] [--repo <field>]
      the landing did not land; the train waits for the session's `unhitch` or `retry`
  engine.py breakup --why <text> [--repo <field>]
      the train that stands is no more: its mark cleared, the queue its failed landing holds released, the field
      back on the head it had before the cars, and its remote branch too (carrier.py, leased push). Without a
      train: a leftover mark cleared
  engine.py unhitch <field> --why <text> [--repo <dir>]
      take a field's ready mark (`worktree queue ready <field> --clear`); a car of a red train: the rest forms
      again (`wagon_master.py unhitch` at once, chain.py; this verb alone at the next round). Refused for a car of a train that lands: a running landing is never stopped.
      `unhitch yard`: the yard's car of a red train; its files stay out of every train until they change
  engine.py retry --why <text> [--skip-pretest] [--repo <dir>]
      a red train lands again as it is (a flaky gate), on a fresh land run: the next `restart` commits an empty
      `wagon train <name>: retry <n>` on the field, so the candidate is new and the red run never adopted again;
      `--skip-pretest`: a `skipped` pretest line with the why first, so its landing starts without the pretest (a
      red pretest that is the Mac's, not a car's)

Exit 0 done (also nothing to do), 1 the change was refused or failed (the tick wakes the session).
"""

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import generated
import mtm_scan
import pretest_train
import train_state
import yard
from carrier import Done, git, push_base
from tick import default_ref

HAL = "hal2-cli-git"
LAND = [HAL, "worktree", "merge-to-main", "--json"]
CURRENT = "plans/CURRENT_PLAN"
RETRY = "wagon train {train}: retry {n}"  # the subject of a retried train's empty commit (plan 0313 step 13)

def cli(args: list[str], cwd: str) -> Done:
    """hal2-cli-git, its exit code and output."""
    try:
        p = subprocess.run([HAL, *args], cwd=cwd, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)
    return p.returncode, (p.stdout + p.stderr).strip()


def spawn(top: str, log: Path) -> int:
    """Start `land` in a session of its own (no terminal, no parent that waits), its output in `log`: its pid."""
    with log.open("w") as out:
        p = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "land", "--repo", top], cwd=top,
                             stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    return p.pid


def here(top: str) -> tuple[str, str, dict | None]:
    """The main checkout, the field's name and the train that stands."""
    main = mtm_scan.main_checkout(top)
    return main, Path(top).name, train_state.standing(train_state.lines(main))


def fetch(top: str) -> str:
    """The barn's ref, fetched (offline: as it is known)."""
    default = default_ref(top)
    git(top, "fetch", "-q", "origin", default.removeprefix("origin/"))
    return default


def load_yard(top: str, main: str, default: str, name: str, cars: list[dict], now=None) -> tuple[int, str]:
    """The yard's uncommitted work as the train's first car (yard.py; D4, D15): what it can place is one commit on
    the field's head, its files a `yard` line of the train state. It never fails a train: the number of files that
    ride and, when the yard had work that does not, why."""
    try:
        past = train_state.yard_past(train_state.lines(main))
        seen = yard.look(main, git(top, "rev-parse", "HEAD")[1], default, cars, past)
        commit, files, why = yard.carry(main, top, seen["placed"], cars)
    except (OSError, subprocess.SubprocessError) as e:
        return 0, f"the yard does not ride: {e}"
    if files:  # without a commit: files the barn holds as they are, for yard.settle after the landing
        train_state.append(main, "yard", Path(top).name, now, train=name, commit=commit, files=files)
    return len(files) * bool(commit), (f"the yard does not ride: {why}" if why else
                                       f"the yard rides with {len(files)} files" if commit else "")


def settle_yard(main: str, train: dict, default: str) -> dict | None:
    """After a green landing: the files the yard's car carried leave the yard where they are still the same, and
    the yard is fast-forwarded (yard.settle). None: the yard did not ride."""
    if not train.get("yard"):
        return None
    try:
        return yard.settle(main, train["yard"], default)
    except (OSError, subprocess.SubprocessError) as e:
        return {"dropped": [], "kept": [], "pulled": False, "why": str(e)}


def form(top: str, cars: list[dict], now: dt.datetime | None = None) -> Done:
    main, field, train = here(top)
    if train:
        return 0, f"train {train['train']} stands ({train['state']}): no second one"
    if not cars:
        return 1, "a train needs a car"
    default = fetch(top)
    behind = git(top, "merge-base", "--is-ancestor", default, "HEAD")[0]
    taken = []  # generated files whose conflict took the barn's side (generated.py, plan 0313 step 8)
    if behind and git(top, "merge", "-q", "--no-edit", default)[0] and not (taken := generated.take(top, "--theirs")):
        git(top, "merge", "--abort")
        return 1, f"{default} does not merge into {field}: no train formed"
    name = "+".join(c["field"] for c in cars) + "@" + train_state.utc(now)
    branch, base = git(top, "branch", "--show-current")[1] or field, git(top, "rev-parse", "HEAD")[1]
    pushed = push_base(top, field, base)  # a dead train an earlier end left on the remote (plan 0313 step 14)
    train_state.append(main, "formed", field, now, train=name, cars=cars, base=base,
                       **({"pushed": pushed} if pushed else {}))
    told = f"; {pushed}" if pushed else ""
    rides, note = load_yard(top, main, default, name, cars, now)
    for car in cars:
        what = f"wagon train: field {car['field']} ({car.get('plan') or car['branch']}), head {car['head']}"
        code, out = git(top, "merge", "-q", "--no-ff", "-m", f"Merge branch '{car['branch']}' into {branch}",
                        "-m", what, car["head"])
        got = generated.take(top, "--ours") if code else []
        if code and not got:
            broken = breakup(top, f"car {car['field']} did not merge: {out[-300:]}", now)[1]
            return 1, f"car {car['field']} did not merge; {broken}{told}"
        taken += got
    if taken:  # the train's last commit: the generated files written again for its head, before the landing
        code, text, commit, files = generated.regenerate(top, sorted(set(taken)))
        train_state.append(main, "regenerated", field, now, train=name, commit=commit, files=files, why=text)
        if code:
            return 1, f"{text}; {breakup(top, text, now)[1]}{told}"
    current = Path(top) / CURRENT
    current.parent.mkdir(parents=True, exist_ok=True)
    current.write_text(" + ".join(["yard"] * bool(rides) + [c.get("plan") or c["field"] for c in cars]) + "\n")
    code, text = restart(top, now)
    return (1, f"{text}; {breakup(top, text, now)[1]}{told}") if code else (0, text + told + (f"; {note}" * bool(note)))


def restart(top: str, now: dt.datetime | None = None) -> Done:
    main, field, train = here(top)
    if not train:
        return 1, "no train stands: nothing to land"
    if train["state"] == "landing" and train_state.alive(train["pid"]):
        return 0, f"train {train['train']}: its landing runs (pid {train['pid']})"
    code, commit = fresh(top, train) if train["state"] == "retry" else (0, None)
    if code:
        return 1, f"train {train['train']} was not retried: {commit[-300:]}"
    code, out = cli(["worktree", "queue", "train", field, *(c["field"] for c in train["cars"]), "--json"], top)
    if code:
        return 1, f"train {train['train']} was not marked: {out[-300:]}"
    log = train_state.folder(main) / train_state.LOG
    pid = spawn(top, log)
    train_state.append(main, "started", field, now, train=train["train"], pid=pid, log=str(log), commit=commit)
    return 0, f"train {train['train']}: landing started (pid {pid}, start {train['starts'] + 1})"


def fresh(top: str, train: dict) -> Done:
    """A retried train's new candidate (plan 0313 step 13, D19): hal2-git builds the landing's candidate as the
    same commit for the same HEAD on the same barn (`candidate_with`: HEAD's dates) and finds its land run by that
    commit, so a retry as it was adopted the red run again. One empty commit on the field makes the candidate new
    and its push a fresh run; none when HEAD is this retry's commit already (its mark was refused). The commit."""
    subject = RETRY.format(train=train["train"], n=train["starts"])
    if git(top, "log", "-1", "--format=%s")[1] != subject:
        why = train.get("retried") or "a flaky gate"
        code, out = git(top, "commit", "-q", "--allow-empty", "-m", subject, "-m", f"Landed again on a fresh run: {why}")
        if code:
            return code, out
    return git(top, "rev-parse", "HEAD")


def land(top: str) -> int:
    """The pretest, then the landing, as this process's child: its output goes where this process's does (the log)."""
    return 1 if pretest_train.before_landing(top) else subprocess.run(LAND, cwd=top).returncode


def landed(top: str, run: str | None = None, commit: str | None = None, now: dt.datetime | None = None) -> Done:
    main, field, train = here(top)
    if not train:
        return 0, "no train stands"
    default = fetch(top)
    code, out = git(top, "merge", "-q", "--ff-only", default)  # the landing reset the field: this makes sure
    (Path(top) / CURRENT).unlink(missing_ok=True)
    home = settle_yard(main, train, default)
    train_state.append(main, "landed", field, now, train=train["train"], cars=[c["field"] for c in train["cars"]],
                       run=run, commit=commit, yard=home)
    behind = f"; {field} did not fast-forward: {out[-200:]}" if code else ""
    if home:
        behind += (f"; the yard: {len(home['dropped'])} carried files dropped, {len(home['kept'])} kept, "
                   + ("fast-forwarded" if home["pulled"] else f"not fast-forwarded ({home['why']})"))
    return 0, f"train {train['train']} is in the barn{behind}"


def red(top: str, status: str, run: str | None = None, why: str = "", now: dt.datetime | None = None) -> Done:
    main, field, train = here(top)
    if not train:
        return 0, "no train stands"
    train_state.append(main, "red", field, now, train=train["train"], status=status, run=run, why=why)
    return 0, f"train {train['train']} is red ({status}): it waits for `unhitch` or `retry`"


def breakup(top: str, why: str, now: dt.datetime | None = None) -> Done:
    main, field, train = here(top)
    if train and train["state"] == "landing" and train_state.alive(train["pid"]):
        return 1, f"train {train['train']} lands (pid {train['pid']}): a running landing is never stopped"
    code, out = cli(["worktree", "queue", "train", field, "--clear", "--json"], top)
    if code:
        return 1, f"the mark of {field} stays: {out[-300:]}"
    try:
        queue = json.loads(cli(["worktree", "queue", "--json"], main)[1]).get("queue", [])
    except (json.JSONDecodeError, AttributeError):
        queue = []
    if any(t.get("slot") == field and t.get("state") == "held" and not t.get("waits_for") for t in queue):
        cli(["worktree", "release", field, "--json"], top)  # its own failed landing's hold: that candidate is gone
    pushed = ""
    if train:
        git(top, "merge", "--abort")
        code, out = git(top, "reset", "-q", "--keep", train["base"]) if train.get("base") else (0, "")
        (Path(top) / CURRENT).unlink(missing_ok=True)
        if code:
            return 1, f"{field} did not go back to {train['base']}: {out[-300:]}"
        pushed = push_base(top, field, train["base"]) if train.get("base") else ""
    train_state.append(main, "cleared", field, now, train=train["train"] if train else None, why=why,
                       **({"pushed": pushed} if pushed else {}))
    done = f"train {train['train']} broken up: {why}" if train else f"the mark of {field} cleared: {why}"
    return 0, done + (f"; {pushed}" if pushed else "")


def unhitch(repo: str, field: str, why: str, now: dt.datetime | None = None) -> Done:
    main, _, train = here(repo)
    its = train["yard"] if train and field == train_state.YARD else None  # the yard's car: no ticket to clear
    if field == train_state.YARD and not its:
        return 1, "the yard rides no train that stands: nothing to unhitch"
    car = bool(train and (its or any(c["field"] == field for c in train["cars"])))
    if car and train["state"] not in ("red", "split"):
        return 1, (f"{field} rides train {train['train']} ({train['state']}): a running landing is never stopped; "
                   "unhitch it once the train is red")
    code, out = (0, "") if its else cli(["worktree", "queue", "ready", field, "--clear", "--json"], main)
    if code:
        return 1, f"{field} was not unhitched: {out[-300:]}"
    train_state.append(main, "unhitched", field, now, train=train["train"] if car else None, why=why, files=its)
    return 0, f"{field} unhitched: {why}" + ("; the rest of the train forms again" if car else "")


def retry(repo: str, why: str, now: dt.datetime | None = None, skip_pretest: bool = False) -> Done:
    main, _, train = here(repo)
    if not train or train["state"] != "red":
        return 1, "no red train stands: nothing to land again"
    if skip_pretest:  # the session's word: this red is the Mac's (pretest_train.before_landing lets it through)
        train_state.append(main, "pretest", train["carrier"], now, train=train["train"], seconds=0, result="skipped",
                           jobs=[], why=f"skipped by the session: {why}")
    train_state.append(main, "retry", train["carrier"], now, train=train["train"], why=why)
    return 0, f"train {train['train']} lands again at the next round{' without its pretest' * skip_pretest}: {why}"


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="verb", required=True)
    for verb in ("form", "restart", "land", "landed", "red", "breakup", "unhitch", "retry"):
        sub.add_parser(verb).add_argument("--repo", default=".")
    sub.choices["form"].add_argument("--cars", required=True, type=json.loads)
    sub.choices["unhitch"].add_argument("field")
    for verb in ("landed", "red"):
        sub.choices[verb].add_argument("--run")
    sub.choices["landed"].add_argument("--commit")
    sub.choices["red"].add_argument("--status", required=True)
    sub.choices["red"].add_argument("--why", default="")
    for verb in ("breakup", "unhitch", "retry"):
        sub.choices[verb].add_argument("--why", required=True)
    sub.choices["retry"].add_argument("--skip-pretest", action="store_true")
    a = p.parse_args(argv)
    found, shown = git(a.repo, "rev-parse", "--show-toplevel")
    top = a.repo if found else shown
    if a.verb == "land":
        return land(top)
    code, text = {"form": lambda: form(top, a.cars), "restart": lambda: restart(top),
                  "landed": lambda: landed(top, a.run, a.commit), "red": lambda: red(top, a.status, a.run, a.why),
                  "breakup": lambda: breakup(top, a.why), "unhitch": lambda: unhitch(top, a.field, a.why),
                  "retry": lambda: retry(top, a.why, skip_pretest=a.skip_pretest)}[a.verb]()
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
