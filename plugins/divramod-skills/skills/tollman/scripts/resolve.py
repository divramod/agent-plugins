"""Every wagon rides (hal2 plan 0522 D18; the user, 2026-10-31: "conflicts need to be resolved and every hitched
wagon should go into the next train"): a car whose merge conflicts is never unhitched. The train waits `resolving`
and the conflicting car's foreman resolves it on the train's branch; the train lands once every conflict is
resolved and its light checks are green (the landing's pretest, pretest_train.py, runs before the push).

This module is the round's side (trains.draft marks the car `conflict`, trains.train_actions forms the train by
`tollman.py resolve-form`); resolve_train.py does the verbs.

- `actions` (trains.handler): one acked message per resolve order (its key: never a second for the same conflict);
  the foreman's ack `done resolved <sha>` (orders.answered) runs `tollman.py resolved <field> <sha>` by code; a base
  that was not published is pushed again first (`tollman.py resolve-publish`)
- `main`: the verbs `resolve-form`, `resolved`, `resolve-publish` (VERBS), resolve_train.py's
"""

import datetime as dt
import json
import re
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import orders
import run_names
import train_state
from tick import act

CLI = Path(__file__).with_name("tollman.py")
VERBS = ("resolve-form", "resolved", "resolve-publish")
WHAT = "resolve order"  # the message's words orders.answered finds the ack by
WORD = re.compile(r"\b(?:resolved|fixed)\s+([0-9a-f]{7,40})\b")
HOUR = 3600
TEXT = {
    "order": "tollman (wagon train): resolve order {id} for field {field}: train {train} carries your crop {head12}, "
             "and it conflicts with {what} in {files}. Every hitched wagon rides (plan 0522 D18): resolve it on the "
             "train's branch. In your kept fix worktree `{where}`, never your field's own checkout (it stays on its "
             "hitched head): `git fetch origin {carrier}; git -C {where} checkout -B {branch} origin/{carrier} || git "
             "worktree add -B {branch} {where} origin/{carrier}` (the train with the cars before yours, {base}), "
             "`git -C {where} merge {head}`, resolve keeping both sides' intent (yours and the train's), commit, "
             "`git -C {where} push origin {branch}`, then answer `done resolved <sha>` with the ack below (your "
             "field `{own}` and its hitch stay as they are). The tollman merges "
             "it into the train, merges the cars behind yours and lands the train once its light checks are green. "
             "`{branch}` is a side branch: never landed on its own, delete it after the barn (merge-to-main's "
             "references/tollman.md, \"A resolve order\").",
}


def what(ahead: list[str]) -> str:
    return f"the cars ahead ({', '.join(ahead)})" if ahead else "the barn"


def open_resolve(train: dict | None) -> dict | None:
    """The standing train's open resolve order (its `resolving` line), or None."""
    return (train or {}).get("resolve") if (train or {}).get("state") == "resolving" else None


def actions(top: str, rows: list[dict], panes: dict, log: list[dict]) -> list[dict]:
    """The round's part (see the module doc): the order's message, once; its answer's `resolved` run."""
    train = train_state.standing(rows)
    if not (r := open_resolve(train)):
        return []
    if r.get("unpublished"):
        argv = [sys.executable, str(CLI), "resolve-publish", "--repo", top]
        return [act("trains", "resolve-publish", "run", r["field"], key=f"publish:{r['id']}", window=HOUR, argv=argv,
                    text=f"resolve order {r['id']}: the train's base pushed again ({r['unpublished'][:120]})")]
    where = str(Path(top).parent / run_names.fix_worktree(r["field"]))  # the kept `<NN>-fix` (plan 0610 D18)
    words = {**r, "train": train["train"], "carrier": r.get("ref") or train["carrier"], "where": where,
             "head12": r["head"][:12], "base": r["base"][:12],
             "what": what(r.get("ahead") or []), "files": ", ".join((r.get("files") or [])[:5]),
             "own": next((c.get("branch") or c["field"] for c in train["cars"] if c["field"] == r["field"]), r["field"])}
    out = [act("trains", "resolve-order", "send", r["field"], pane=panes.get(r["field"]),
               key=f"resolve:{train['train']}:{r['id']}", text=TEXT["order"].format(**words))]
    if answer := orders.answered(r, log, WHAT, WORD):
        argv = [sys.executable, str(CLI), "resolved", r["field"], answer[0], "--repo", top]
        stuck = act("trains", "resolve-refused", "wake", key=f"stuck:resolved:{r['id']}:{answer[0]}",
                    text=f"the resolve {answer[0][:12]} of order {r['id']} was not taken: `{' '.join(argv[1:5])}` says why")
        out.append(act("trains", "resolved", "run", r["field"], key=f"resolved:{r['id']}:{answer[0]}", argv=argv,
                       on_fail=[stuck], text=f"resolve order {r['id']}: {r['field']} answered resolved {answer[0][:12]}"))
    return out


def add_parser(sub) -> None:
    f = sub.add_parser("resolve-form")
    f.add_argument("--cars", required=True)
    f.add_argument("--alone-next", nargs="*", default=[])  # the alone cars owed the next train (plan 0610 D15)
    r = sub.add_parser("resolved")
    r.add_argument("field")
    r.add_argument("sha")
    sub.add_parser("resolve-publish")


def main(args, wiring) -> int:
    """`tollman.py resolve-form|resolved|resolve-publish` (VERBS); a refusal's message done as a round does it."""
    import resolve_train  # the engine's side, loaded only by a verb
    if args.cmd == "resolve-form":
        code, text = resolve_train.form(args.repo, json.loads(args.cars), alone_next=args.alone_next)
    elif args.cmd == "resolve-publish":
        code, text = resolve_train.publish(args.repo)
    else:
        import mtm_scan
        import orders_cli
        import tick
        import train_wt
        main_dir = mtm_scan.main_checkout(args.repo)
        top = str(mtm_scan.roles.slot_dir(main_dir, wiring.role))
        ctx = tick.context(top, main_dir, {}, dt.datetime.now(), False, wiring)
        code, text, done = resolve_train.resolved(train_wt.carrier(top), args.field, args.sha, ctx["panes"])
        orders_cli.deliver(top, main_dir, done, ctx, wiring)
    print(text, file=sys.stderr if code else sys.stdout)
    return code
