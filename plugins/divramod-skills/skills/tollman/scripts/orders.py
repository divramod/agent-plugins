"""Fix orders (hal2 plan 0360 step 6, D6, D29): a red train is never broken up; the car that broke it is fixed in
the train. Replaces unhitch-after-red and breakup (the user's own `--by-user` stays, frozen.py).

- `order`: the tollman's session, after its triage judgment (a `car_red` wake), orders the car's foreman: an `order`
  line of the train state (train_state.py; the train goes `fixing`, frozen as red), the carrier's head published on
  its remote branch (never moved back), and one acked message (`tick.execute` stamps it, `tollman [<id>] ...`): fix on
  `<NN>-train-fix` from `origin/<carrier>`, push, answer `fixed <sha>`. `order main` (a `main_red` wake, D29): the
  tollman's own hand fixes on `tollman-train-fix`; no foreman message, a wake for its own session.
- early (plan 0383 step 5, D5, L35): `order` also while the train still lands, placed by code when the triage of
  the run's first red job names exactly one car (early_order.py) or by the session's hand; the train stays `landing`
  and its red makes it `fixing` (train_state.py). The message is the same (the fix on `<NN>-train-fix` from
  `origin/<carrier>`, never the field's own branch); an early order for a field that has one open is no second one.
  `fixed` waits for the run's end (L34): while the train lands an answer is neither checked nor merged.
- post-merge (plan 0383 step 6, D6, L34): `order --post <landed train>` for a red after the merge job of a train
  that is in the barn (post_merge.py): the order rides the train that stands (its `post`, train_state.py), the
  field need be no car of it, the train's state never changes (it never holds the next train). Its fix is merged
  into that train before its run starts (next_train.py, in the landing's process), or by `fixed` while no landing
  runs; a train that lands first hands it on to the next.
- `fixed`: the answer, checked (the sha on `origin/<branch>`, or the local branch for `main`, and descending from the
  order's base), merged into the carrier (`--no-ff`; generated-only conflicts take the carrier's side, as
  frozen.merge_car), a `fixed` line; the last order closed, the train is `retry` and the next round's `restart` lands
  the same cars plus the fixes on a new candidate (the merge; no empty retry commit, engine.fresh). A refused answer
  keeps the order open and tells the foreman why.
- `answers`: the round reads the foreman's ack (`acks.py ack <id> done fixed <sha>`, the message's ack id found by its
  `fix order <id>`) and runs `tollman.py fixed` by code (deterministic first).
"""

import re
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import generated
import mtm_scan
import train_state
from carrier import Done, git
from tick import act

MAIN = "main"  # `order main`: the barn's red, fixed by the tollman's own hand (D29)
OWN_FIX = "tollman-train-fix"
CLI = Path(__file__).with_name("tollman.py")
FIXED = re.compile(r"\bfixed\s+([0-9a-f]{7,40})\b")
HEAD = "tollman (wagon train): fix order {id} for field {field}: train {train} is red ({red}). Run: {run}. Why: {why}."
TEXT = {
    "order": HEAD + "\nIn your field: `git fetch origin {carrier}; git switch -C {branch} origin/{carrier}` (the train "
                    "with every car and fix so far, {base}), fix, commit, `git push origin {branch}`, then answer "
                    "`done fixed <sha>` with the ack below (`tollman.py fixed` is run by the tollman, you only "
                    "answer). `{branch}` is a side branch: never landed on its own, it rides in this train; after the barn "
                    "merge it into your branch before /merge-from-main, then delete it (merge-to-main's references/tollman.md, \"A fix "
                    "order\"). `tollman.py triage {rid}` shows the evidence.{early}",
    "main": HEAD + "\nThe barn is red: a hand of yours fixes it in the train's worktree `{where}` on `{branch}` from {base} "
                   "(`git switch -C {branch} {base}`), commits, switches back to `{carrier}`, then you run "
                   "`tollman.py fixed main <sha>`; the fix rides in this train (D29).",
    "early": " The run still runs: push your fix as soon as it is ready; the tollman merges it into the train after "
             "the run has finished.",
    "post": "tollman (wagon train): fix order {id} for field {field}: train {post} is in the barn, but {red} is red "
            "after its merge. Run: {run}.\nIn your field: `git fetch origin {carrier}; git switch -C {branch} "
            "origin/{carrier}` (the next train {train}, {base}), fix, commit, `git push origin {branch}`, then answer "
            "`done fixed <sha>` with the ack below. `{branch}` is a side branch: never landed on its own, the tollman "
            "merges it into the next train before that train's run starts (nothing waits for it); after the barn "
            "merge it into your branch before /merge-from-main, then delete it. `tollman.py triage {rid}` shows the "
            "evidence.",
    "refused": "tollman (wagon train): your fix {sha} for fix order {id} is refused: {why}. The order stays open: "
               "branch `{branch}` from `origin/{carrier}`, fix, push and answer `done fixed <sha>` again.",
}


def remote_tip(top: str, ref: str) -> tuple[int, str]:
    code, text = git(top, "ls-remote", "origin", ref)
    return code, next((w[0] for w in (line.split() for line in text.splitlines()) if w[1:] == [ref]), "") or text * code


def publish(top: str, base: str) -> str:
    """The carrier's remote branch made to hold `base`, so a foreman branches from it: "" when it does already
    (`base` itself or a later head: never moved back), else a leased push (carrier.push_base's lease: never a bare
    force); a failure starts with `not`."""
    ref = "refs/heads/" + (git(top, "branch", "--show-current")[1] or Path(top).name)
    code, tip = remote_tip(top, ref)
    if code:
        return f"not published: origin's {ref} not read: {tip[-200:]}"
    if tip and (tip == base or git(top, "merge-base", "--is-ancestor", base, tip)[0] == 0):
        return ""
    code, text = git(top, "push", "-q", f"--force-with-lease={ref}:{tip}", "origin", f"{base}:{ref}")
    return f"not published: origin's {ref} still holds {tip[:12] or 'nothing'}: {text[-200:]}" if code else \
        f"origin's {ref} pushed to {base[:12]}"


def next_id(rows: list[dict], field: str) -> str:
    """`<field>-fix-<n>`: n counts the field's orders in the whole state, so an id names one message for good."""
    return f"{field}-fix-{1 + sum(1 for e in rows if e['kind'] == 'order' and e.get('field') == field)}"


def refusal(train: dict | None, field: str, smuggle: bool, post: str | None) -> str:
    """Why no order for `field` can be placed on the standing `train`, or ""."""
    if post:  # a post-merge order rides any train that stands, whatever its state (it never holds it)
        return "" if train else "no train stands: a post-merge red's fix rides the foreman's next harvest"
    if not train or train["state"] not in ("red", "fixing", "landing"):
        return f"no red or landing train stands ({(train or {}).get('state', 'none')}): a fix order needs one"
    if field != MAIN and not smuggle and field not in [c["field"] for c in train["cars"]]:
        return f"{field} rides no car of train {train['train']}: `order <car field>` or `order main`"
    return ""


def order(top: str, field: str, why: str, run: str | None, panes: dict, now=None,
          smuggle: bool = False, post: str | None = None) -> tuple[int, str, list[dict]]:
    """The order for `field` (a car of the standing red train, `main`, with `smuggle` a smuggling field: its
    smuggle conflicts with or broke the train, plan 0360 step 18; with `post` a car of that landed train, its red
    after the merge): its exit, its line and its actions (the foreman's message or the own session's wake), which
    the caller executes."""
    main = mtm_scan.main_checkout(top)
    rows = train_state.lines(main)
    train = train_state.standing(rows)
    if why_not := refusal(train, field, smuggle, post):
        return 1, why_not, []
    early = train["state"] == "landing" and not post
    open_ = train["post"] if post else train["orders"] if early else []
    if o := next((o for o in open_ if o["field"] == field), None):
        return 0, f"fix order {o['id']} for {field} stands already: no second one while it is open", []
    base, carrier = git(top, "rev-parse", "HEAD")[1], git(top, "branch", "--show-current")[1] or Path(top).name
    told = publish(top, base)
    if told.startswith("not"):
        return 1, f"no fix order: {told}", []
    oid, branch = next_id(rows, field), OWN_FIX if field == MAIN else f"{field}-train-fix"
    train_state.append(main, "order", Path(top).name, now, train=train["train"], field=field, branch=branch, base=base,
                       why=why, run=run or train.get("run"), id=oid, post=post)
    words = {"id": oid, "field": field, "train": train["train"],
             "red": why if early or post else train.get("why") or train.get("status"), "early": TEXT["early"] * early,
             "run": run or train.get("run") or "none", "why": why, "carrier": carrier, "branch": branch,
             "base": base[:12], "rid": run or train.get("run") or "", "where": top, "post": post}
    key = f"order:{train['train']}:{field}:{oid.rsplit('-', 1)[1]}"
    if field == MAIN:
        a = act("trains", "fix-order-main", "wake", key=key, text=TEXT["main"].format(**words), evidence=words)
    else:
        a = act("trains", "fix-order", "send", field, pane=panes.get(field), key=key,
                text=TEXT["post" if post else "order"].format(**words))
    return 0, f"fix order {oid}: {field} fixes train {train['train']} on {branch} from {base[:12]}" + (
        f"; {told}" if told else ""), [a]


def check(top: str, o: dict, sha: str) -> str:
    """Why `sha` does not answer the order `o`, or ""."""
    branch = o["branch"]
    git(top, "fetch", "-q", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}")
    if git(top, "rev-parse", "-q", "--verify", f"{sha}^{{commit}}")[0]:
        return f"{sha} is no commit here (pushed to origin/{branch}?)"
    refs = [f"origin/{branch}"] + [branch] * (o["field"] == MAIN)  # the tollman's own fix may stay local
    if not any(git(top, "merge-base", "--is-ancestor", sha, r)[0] == 0 for r in refs):
        return f"{sha[:12]} is not on origin/{branch}"
    if git(top, "merge-base", "--is-ancestor", o["base"], sha)[0]:
        return f"{sha[:12]} does not descend from the order's base {o['base'][:12]} (branch from origin/<carrier>)"
    return ""


def merge(top: str, o: dict, sha: str) -> Done:
    """The fix merged into the carrier; a conflict only in generated files takes the carrier's side."""
    carrier = git(top, "branch", "--show-current")[1] or Path(top).name
    code, text = git(top, "merge", "-q", "--no-ff", "-m", f"Merge {o['branch']} into {carrier} (fix order {o['id']})",
                     sha)
    if code and not generated.take(top, "--ours"):
        git(top, "merge", "--abort")
        return 1, f"{sha[:12]} does not merge into {carrier}: {text[-300:]}"
    return git(top, "rev-parse", "HEAD")


POST_WAITS = ("formed", "landing", "paused", "split")  # a post-merge fix: the landing's process merges it (next_train)


def fixed(top: str, field: str, sha: str, panes: dict, now=None) -> tuple[int, str, list[dict]]:
    """The answer to `field`'s open order: merged, or refused with the foreman told why."""
    main = mtm_scan.main_checkout(top)
    train = train_state.standing(train_state.lines(main))
    o = next((o for o in (train or {}).get("orders", []) if o["field"] == field), None)
    p = None if o else next((p for p in (train or {}).get("post", []) if p["field"] == field), None)
    if o and train["state"] == "landing":  # L34: a fix is merged and run only after the workflow has finished
        return 1, f"fix order {o['id']} waits: the train's land run still runs; the fix is merged after it ends", []
    if p and train["state"] in POST_WAITS:
        return 1, f"fix order {p['id']} waits: the landing merges it before its run starts, else the next train", []
    if not p and (not train or train["state"] != "fixing" or not o):
        return 1, f"no open fix order for {field}", []
    o = o or p
    code, commit = take(top, main, train, o, sha, now)
    if code:
        carrier = git(top, "branch", "--show-current")[1]
        tell = [] if field == MAIN else [act("trains", "fix-refused", "send", field, pane=panes.get(field),
                                             key=f"fix-refused:{o['id']}:{sha}", text=TEXT["refused"].format(
                                                 sha=sha[:12], id=o["id"], why=commit, branch=o["branch"],
                                                 carrier=carrier))]
        return 1, f"fix order {o['id']} stays open: {commit}", tell
    if p:
        return 0, f"fix order {p['id']} merged ({sha[:12]}) into train {train['train']}: it rides there", []
    rest = [x["id"] for x in train["orders"] if x["id"] != o["id"]]
    return 0, f"fix order {o['id']} merged ({sha[:12]}): " + (f"waits for {', '.join(rest)}" if rest else
                                                              "the same cars land again at the next round"), []


def take(top: str, main: str, train: dict, o: dict, sha: str, now=None) -> Done:
    """The answer `sha` checked and merged into the carrier, its `fixed` line written: (0, the merge) or (1, why)."""
    why = check(top, o, sha)
    code, commit = (1, why) if why else merge(top, o, sha)
    if not code:
        train_state.append(main, "fixed", Path(top).name, now, train=train["train"], field=o["field"], id=o["id"],
                           sha=sha, commit=commit)
    return code, commit


def answered(o: dict, log: list[dict]) -> str | None:
    """The sha the order's message's ack answers with (`done fixed <sha>`), or None."""
    asks = {e["id"] for e in log if e.get("kind") == "ask-ack" and e.get("id")
            and f"fix order {o['id']} " in (e.get("text") or "")}
    return next((m.group(1) for e in reversed(log) if e.get("kind") == "ack" and e.get("id") in asks
                 and e.get("what") == "done" and (m := FIXED.search(e.get("note") or ""))), None)


def answers(top: str, rows: list[dict], log: list[dict]) -> list[dict]:
    """The round's `fixed` runs: an open order whose message's ack says `done fixed <sha>`; a post-merge order's
    only while no landing runs (the landing's process merges it itself, next_train.py)."""
    train = train_state.standing(rows) or {}
    out = []
    own = train.get("orders", []) if train.get("state") == "fixing" else []
    for o in own + ([] if train.get("state") in POST_WAITS else train.get("post", [])):
        if not (sha := answered(o, log)):
            continue
        argv = [sys.executable, str(CLI), "fixed", o["field"], sha, "--repo", top]
        refused = act("trains", "fix-refused", "wake", key=f"stuck:fixed:{o['id']}:{sha}",
                      text=f"the fix {sha[:12]} of order {o['id']} was refused: `{' '.join(argv[1:5])}` says why")
        out.append(act("trains", "fixed", "run", o["field"], key=f"fixed:{o['id']}:{sha}", argv=argv,
                       on_fail=[refused], text=f"fix order {o['id']}: {o['field']} answered fixed {sha[:12]}"))
    return out
