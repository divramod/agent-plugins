"""The role cars (hal2 plan 0610 D18; roles/tollman/ROLE.md, the user, 2026-11-04: "you should both go to the end of
train, so that we can avoid, that the changes, which came in between create conflicts and we only have to join the
two of you once"; "the tollman and the farmer should only go into the train in the first try of a train"): what the
tollman's and the farmer's own branches (`tollman-<repo>`, `farmer-<repo>`) hold beyond the carrier rides every train
as its last two cars, the tollman's then the farmer's, hitched or not.

- When: `engine.land` merges them right before the push of the train's first land run (no `push` line yet), after
  every car, join and fix is in (next_train.before_push, open_train.stops). A later run of the same train (after a
  red, a retry) takes no newer head: the carrier keeps what the first run merged, so a role change never turns a fixed
  train red again. One `roles` line per train says what rode.
- The newest head: the role's local branch (every worktree shares the refs), origin's when that holds the local one.
  A head the carrier holds already is nothing to merge. The tollman's field's head at the forming is the carrier's
  start (train_wt.add: the barn's own fix rides first, own_fix.py, and the draft is made on it), so its car is what it
  committed since.
- A role car never holds a train: a merge that conflicts (not only in generated files) is aborted and the car stays
  out of this train, its why on the `roles` line and printed (merge the barn into the role's branch; the next train
  takes it again). Generated files are written again as a join writes them (generated.regenerate).
- Owed (plan 0610 D24, the farmer: "a role car left out over a push conflict must ride the very next train as its
  first car, and that must be enforced by code ... A car that is left out twice in a row must stop the train and come
  to the farmer, not be left out a third time"): a `roles` line's `out` is the record, each with `times` (its
  leave-outs in a row, `owed`); every leave-out is a board note to the farmer naming the car and its conflict
  (`role-car-out`, board.NOTES). The next train's forming merges an owed car `first`, right after the barn and before
  the yard and every wagon (engine_form.form, a `roles` line with `place: first`). A second leave-out in a row stops
  the train (`stop` on its `roles` line, the state `stopped`: frozen, never pushed, `merge` refuses the push) and a
  board note goes to the farmer (`role-car-stopped`); each round tries the stopped car again (`role_cars.py retry`,
  trains.py) only when its head moved, so once the farmer made it merge the train goes on, and a third leave-out is
  never recorded.

  role_cars.py retry [--repo <field>]      a stopped train's role car merged again (the round's action)
"""

import argparse
import os
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import frozen
import generated
import mtm_scan
import train_state
from carrier import git

KIND = "roles"
ROLES = ("tollman", "farmer")  # the order they ride in, at the train's end
FIRST = "first"  # a `roles` line's `place` for an owed car merged first at the forming (D24)
OUT, STOPPED = "role-car-out", "role-car-stopped"  # the farmer's board notes (board.NOTES)
STOP_AT = 2  # leave-outs in a row that stop the train (D24)


def rode(rows: list[dict], train: dict) -> bool:
    """Whether the train's role cars had their turn at its end already (its `roles` line that is not the forming's)."""
    return any(e.get("kind") == KIND and e.get("train") == train["train"] and e.get("place") != FIRST for e in rows)


def owed(rows: list[dict]) -> dict[str, dict]:
    """{field: its last `out` entry with `times`, its leave-outs in a row}: the role cars left out and not merged
    since (D24)."""
    out: dict[str, dict] = {}
    for e in (e for e in rows if e.get("kind") == KIND):
        for m in e.get("merged") or []:
            out.pop(m.get("field"), None)
        for o in e.get("out") or []:
            out[o["field"]] = {**o, "times": out.get(o["field"], {}).get("times", 0) + 1}
    return out


def newest(top: str, branch: str) -> str | None:
    """The newest head of the role's `branch`: the local one, origin's when that holds it (or no local one)."""
    local = git(top, "rev-parse", "-q", "--verify", f"refs/heads/{branch}^{{commit}}")
    remote = git(top, "rev-parse", "-q", "--verify", f"refs/remotes/origin/{branch}^{{commit}}")
    lh, rh = (local[1] if local[0] == 0 else None), (remote[1] if remote[0] == 0 else None)
    if lh and rh and lh != rh and git(top, "merge-base", "--is-ancestor", lh, rh)[0] == 0:
        return rh
    return lh or rh


def one(top: str, carrier_branch: str, branch: str, head: str, fields: list[str]) -> str:
    """The role's head merged into the carrier `top`: "" merged, else why it stays out (the merge undone)."""
    pre = git(top, "rev-parse", "HEAD")[1]
    code, out, taken = frozen.merge_car(top, carrier_branch, {"field": branch, "branch": branch, "head": head})
    if code:
        git(top, "merge", "--abort")
        git(top, "reset", "-q", "--keep", pre)
        return f"it does not merge into the train ({out.strip()[-160:] or 'a conflict'})"
    if taken and (made := generated.regenerate(top, sorted(set(taken)), fields))[0]:
        git(top, "reset", "-q", "--keep", pre)
        return f"its generated files were not written again: {made[1][-160:]}"
    return ""


def ride(top: str, main: str, train: dict, fields: list[str], fields_owed: dict[str, dict]) -> tuple[list, list]:
    """Each role (in ROLES, or only those owed) merged into the carrier `top`: (merged, out); an `out` carries
    `times`, its leave-outs in a row with this one."""
    branch_of = git(top, "branch", "--show-current")[1] or Path(top).name
    merged, out = [], []
    for role in ROLES:
        branch = mtm_scan.roles.slot_name(main, role)
        if fields_owed is not None and branch not in fields_owed:
            continue
        head = newest(top, branch)
        if not head or git(top, "merge-base", "--is-ancestor", head, "HEAD")[0] == 0:
            merged += [{"field": branch, "head": head, "carried": True}] if branch in (fields_owed or {}) else []
            continue
        if why := one(top, branch_of, branch, head, fields):
            times = (owed(train_state.lines(main)).get(branch) or {}).get("times", 0) + 1
            out.append({"field": branch, "head": head, "why": why, "times": times})
        else:
            merged.append({"field": branch, "head": head})
    return merged, out


def record(main: str, top: str, train: dict, merged: list, out: list, now=None, place: str | None = None) -> list[str]:
    """The `roles` line, a board note to the farmer per car left out and, at the second leave-out in a row, the
    train's stop (D24): the lines to print."""
    stop = next(({k: o[k] for k in ("field", "head", "why")} for o in out if o["times"] >= STOP_AT), None)
    train_state.append(main, KIND, Path(top).name, now, train=train["train"], merged=merged, out=out or None,
                       place=place, stop=stop)
    farmer, name = mtm_scan.roles.slot_name(main, "farmer"), train["train"]
    lines = [f"train {name}: role car {m['field']} ({m['head'][:12]}) rides "
             + ("first" if place == FIRST else "at its end") for m in merged if not m.get("carried")]
    for o in out:
        text = (f"train {name}: role car {o['field']} ({o['head'][:12]}) stays out of this train ({o['times']} in a "
                f"row): {o['why']}; merge the barn into {o['field']}, the next train takes it first")
        if o["times"] >= STOP_AT:
            text = (f"train {name} stopped: role car {o['field']} ({o['head'][:12]}) is left out a second time in a "
                    f"row: {o['why']}; it never pushes until {o['field']} merges (merge the barn into it), farmer")
        note(main, STOPPED if o["times"] >= STOP_AT else OUT, farmer, text, f"{name}:{o['field']}:{o['head'][:12]}")
        lines.append(text)
    return lines


def note(main: str, kind: str, farmer: str, text: str, key: str) -> None:
    """A `record` of the tollman's log that board.sync posts as a note to the farmer (board.NOTES)."""
    mtm_scan.log(main, {"kind": kind, "slot": farmer, "what": text, "by": "role_cars", "do": "record",
                        "key": f"{kind}:{key}"}, train_state.ROLE)


def first(top: str, now=None) -> tuple[int, list[str]]:
    """The forming's look (engine_form.form, D24): the owed role cars merged as the train's first cars, right after
    the barn; (1, its lines) when one is left out a second time in a row (the train stopped), else (0, lines)."""
    main = mtm_scan.main_checkout(top)
    rows = train_state.lines(main)
    train, due = train_state.standing(rows), owed(rows)
    if not train or not due:
        return 0, []
    merged, out = ride(top, main, train, [], due)
    lines = record(main, top, train, merged, out, now, FIRST)
    return int(any(o["times"] >= STOP_AT for o in out)), lines


def retry(top: str, now=None) -> tuple[int, str]:
    """A stopped train's role car again (the round's action, D24): merged first now, the train `formed` again (the
    restart merges the cars it lacks); still out: nothing recorded (no third leave-out), it waits for the farmer."""
    main = mtm_scan.main_checkout(top)
    rows = train_state.lines(main)
    train = train_state.standing(rows)
    if not train or train["state"] != "stopped":
        return 0, "no stopped train"
    stop, name = train["stop"], train["train"]
    head = newest(top, stop["field"])
    carried = bool(head) and git(top, "merge-base", "--is-ancestor", head, "HEAD")[0] == 0
    if not carried and (not head or head == stop["head"]):
        return 0, f"train {name} stays stopped: {stop['field']} has no new head, it waits for the farmer"
    if not carried and (why := one(top, git(top, "branch", "--show-current")[1] or Path(top).name, stop["field"],
                                   head, [c["field"] for c in train["cars"]])):
        return 0, f"train {name} stays stopped: {stop['field']} ({head[:12]}) still does not merge: {why}"
    train_state.append(main, KIND, Path(top).name, now, train=name, place=FIRST,
                       merged=[{"field": stop["field"], "head": head, **({"carried": True} if carried else {})}])
    return 0, f"train {name}: role car {stop['field']} ({head[:12]}) merged, the train goes on"


def merge(top: str, now=None) -> int:
    """engine.land's look right before the push: the role cars merged into the carrier `top` once per train (the
    module doc), their lines printed; 1 when the train is stopped (D24): it never pushes."""
    main = mtm_scan.main_checkout(top)
    rows = train_state.lines(main)
    train = train_state.standing(rows)
    if train and train["state"] == "stopped":
        print(f"tollman: train {train['train']} is stopped: role car {train['stop']['field']} is left out twice in a "
              "row, no push (the farmer)", flush=True)
        return 1
    if not train or train["carrier"] != Path(top).name or train.get("push") or rode(rows, train):
        return 0
    merged, out = ride(top, main, train, [c["field"] for c in train["cars"]], None)
    for line in record(main, top, train, merged, out, now):
        print(line, flush=True)
    return int(any(o["times"] >= STOP_AT for o in out))


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("verb", choices=("retry",))
    p.add_argument("--repo", default=os.getcwd())
    code, text = retry(p.parse_args(argv).repo)
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
