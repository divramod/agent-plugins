"""The verbs of a train with a conflicting car (hal2 plan 0522 D18; resolve.py is the round's side):

- `form` (`tollman.py resolve-form --cars <json>`): `engine.form` for a draft with a car marked `conflict`
  (trains.draft), the same forming (engine_form.py): the train's own worktree, the barn, its `formed` line, the yard's
  car, then `merge_rest`, which `engine.form` ends with too (plan 0610 E25: a car that does not merge there is a
  resolve order, never a cleared train)
- `merge_rest`: the cars the carrier lacks merged in queue order (frozen.merge_car); the first that conflicts (not
  only in generated files) is aborted and `wait` writes its `resolving` line: the carrier's head published on its
  remote branch (orders.publish, never moved back: `train-<n>-<a>`, run_names.base_ref), a resolve order
  `<NN>-resolve-<n>` on `<NN>-train-<n>-<a>-resolve` (run_names.fix_branch; a train without a number:
  `<NN>-train-resolve`), worked in the field's kept fix worktree `<NN>-fix` (plan 0610 D18). All
  merged: the generated files written again, the CURRENT_PLAN pointer, then `engine.restart` (mark; the landing's
  pretest runs before its push)
- `resolved` (`tollman.py resolved <field> <sha>`): the answer checked (on `origin/<branch>`, from the order's base,
  the car's head in it, no conflict marker left in its files), the carrier fast-forwarded to it, a `resolved` line,
  then `merge_rest` again. Refused: the foreman is told why, the order stays open
- `publish` (`tollman.py resolve-publish`): the base pushed again when it was not
A car leaves the train only on the user's own word (frozen.py).
"""

import datetime as dt
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import engine
import frozen
import generated
import hold
import orders
import run_names
import train_state
import trial
from carrier import Done, git
from resolve import open_resolve, what
from tick import act

MARKER = r"^(<<<<<<<|>>>>>>>)( |$)"
REFUSED = ("tollman (wagon train): your resolve {sha} for resolve order {id} is refused: {why}. The order stays "
           "open: `git switch -C {branch} origin/{carrier}`, `git merge {head}`, resolve, push and answer "
           "`done resolved <sha>` again.")


def form(top: str, cars: list[dict], now: dt.datetime | None = None, alone_next=()) -> Done:
    """engine.form's forming (engine_form.py, plan 0610 E25: one forming for both verbs); the cars by `merge_rest`."""
    import engine_form
    return engine_form.form(top, cars, now, alone_next)


def merge_rest(top: str, now: dt.datetime | None = None, taken=()) -> Done:
    """The cars the carrier lacks merged in order; a conflict waits `resolving`; all in: the landing starts."""
    main, field, train, top = engine.here(top)
    branch, taken = git(top, "branch", "--show-current")[1] or field, list(taken)
    for car in train["cars"]:
        if git(top, "merge-base", "--is-ancestor", car["head"], "HEAD")[0] == 0:
            continue
        code, _, got = frozen.merge_car(top, branch, car)
        if code:
            return wait(top, main, train, car, taken, now)
        taken += got
    if taken:  # the train's last commit: the generated files written again for its head, before the landing
        code, text, commit, files = generated.regenerate(top, sorted(set(taken)), [c["field"] for c in train["cars"]])
        train_state.append(main, "regenerated", field, now, train=train["train"], commit=commit, files=files, why=text)
        if code:
            return 1, f"{text}; train {train['train']} stands (D3)"
    frozen.write_current(top, train["cars"], bool(train.get("yard")))
    if held := hold.of(main):  # plan 0383 step 7: nothing restarts while held; unheld, the round restarts it
        return 0, f"train {train['train']}: every car merged, it lands once unheld ({hold.text(held)})"
    return engine.restart(top, now)


def next_id(rows: list[dict], field: str) -> str:
    """`<field>-resolve-<n>`: n counts the field's resolve orders in the whole state."""
    return f"{field}-resolve-{1 + len({e.get('id') for e in rows if e['kind'] == 'resolving' and e.get('field') == field})}"


def wait(top: str, main: str, train: dict, car: dict, taken: list[str], now=None) -> Done:
    """The car's conflict: its merge undone, the base published, its `resolving` line (the train waits)."""
    files = [f for f in git(top, "diff", "--name-only", "--diff-filter=U")[1].splitlines() if f]
    git(top, "merge", "--abort")
    base, cars = git(top, "rev-parse", "HEAD")[1], [c["field"] for c in train["cars"]]
    barn = bool(trial.merge(top, train["base"], car["head"])[1])  # it conflicts with the barn itself
    ahead = [] if barn else cars[:cars.index(car["field"])]
    ref = run_names.base_ref(train, git(top, "branch", "--show-current")[1] or Path(top).name)  # plan 0610 D18
    rid, told = next_id(train_state.lines(main), car["field"]), orders.publish(top, base, ref)
    train_state.append(main, "resolving", Path(top).name, now, train=train["train"], field=car["field"],
                       head=car["head"], files=files, ahead=ahead, base=base, id=rid, ref=ref,
                       branch=run_names.fix_branch(train, car["field"], "resolve"), taken=sorted(set(taken)) or None,
                       unpublished=told if told.startswith("not") else None)
    return 0, (f"train {train['train']} waits resolving: car {car['field']} conflicts with {what(ahead)} in "
               f"{', '.join(files[:5])}; resolve order {rid}" + (f"; {told}" if told else ""))


def publish(top: str, now: dt.datetime | None = None) -> Done:
    """The open resolve's base pushed again after it was not: its `resolving` line again, without `unpublished`."""
    main, _, train, top = engine.here(top)
    r = open_resolve(train)
    if not r or not r.get("unpublished"):
        return 0, "no resolve order waits for its base"
    told = orders.publish(top, r["base"], r.get("ref"))
    if told.startswith("not"):
        return 1, told
    keys = {k: v for k, v in r.items() if k not in ("schema", "at", "kind", "slot", "unpublished")}
    train_state.append(main, "resolving", Path(top).name, now, **keys)
    return 0, told or f"resolve order {r['id']}: its base is on origin"


def check(top: str, r: dict, sha: str) -> str:
    """Why `sha` does not resolve the order `r`, or ""."""
    if why := orders.check(top, r, sha):  # fetched, on origin/<branch>, from the order's base
        return why
    if git(top, "merge-base", "--is-ancestor", r["head"], sha)[0]:
        return f"{sha[:12]} does not hold the car's head {r['head'][:12]} (`git merge {r['head'][:12]}`)"
    code, left = git(top, "grep", "-l", "-E", MARKER, sha, "--", *r.get("files") or ["."])
    return f"conflict markers are left in {left.replace(sha + ':', '')[:200]}" if code == 0 and left else ""


def resolved(top: str, field: str, sha: str, panes: dict, now=None) -> tuple[int, str, list[dict]]:
    """The answer to `field`'s open resolve order: merged and the train goes on, or refused with the foreman told."""
    main, _, train, top = engine.here(top)
    r = open_resolve(train)
    if not r or r["field"] != field:
        return 1, f"no open resolve order for {field}", []
    if why := check(top, r, sha):
        text = REFUSED.format(sha=sha[:12], id=r["id"], why=why, branch=r["branch"],
                                      carrier=train["carrier"], head=r["head"])
        tell = act("trains", "resolve-refused", "send", field, pane=panes.get(field),
                   key=f"resolve-refused:{r['id']}:{sha}", text=text)
        return 1, f"resolve order {r['id']} stays open: {why}", [tell]
    code, out = git(top, "merge", "-q", "--ff-only", sha)
    if code:
        return 1, f"{sha[:12]} does not fast-forward train {train['train']}: {out[-300:]}", []
    train_state.append(main, "resolved", Path(top).name, now, train=train["train"], field=field, id=r["id"], sha=sha,
                       commit=sha)
    code, text = merge_rest(top, now, r.get("taken") or [])
    return code, f"resolve order {r['id']} merged ({sha[:12]}); {text}", []
