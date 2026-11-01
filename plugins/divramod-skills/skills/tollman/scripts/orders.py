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
  `origin/<carrier>`, never the field's own branch); an early order for a field that has one open is no second one:
  a red job it does not name yet is added to it (`also`, plan 0522 D16: one message per red job, one answer).
  `fixed` waits for the run's end (L34): while the train lands an answer is neither checked nor merged.
- post-merge (plan 0383 step 6, D6, L34): `order --post <landed train>` for a red after the merge job of a train
  that is in the barn (post_merge.py): the order rides the train that stands (its `post`, train_state.py), the
  field need be no car of it, the train's state never changes (it never holds the next train). Its fix is merged
  into that train before its run starts (next_train.py, in the landing's process), or by `fixed` while no landing
  runs; a train that lands first hands it on to the next.
- `fixed`: the answer, checked (the sha on `origin/<branch>`, or the local branch for `main`, and descending from the
  order's base), proven green (fix_proof.py, plan 0522 D5: the order's `jobs`, a light one run by the tollman on the
  sha, a heavy one by the gate's green line in the answer; `--unproven <why>` the session's word without), merged
  into the carrier (`--no-ff`; generated-only conflicts take the carrier's side, as
  frozen.merge_car), a `fixed` line; the last order closed, the train is `retry` and the next round's `restart` lands
  the same cars plus the fixes on a new candidate (the merge; no empty retry commit, engine.fresh). A refused answer
  keeps the order open and tells the foreman why.
- plan 0490 step 10: `fixed` takes a landing whose process is gone as ended (L47, L108: `still_lands`), `--redundant`
  (L56); the texts' PUSH and PROOF (orders_text.py; L84, L85, L106, L113); a fix left local over 30 min wakes once (L106)
- `answers`: the round reads the foreman's ack (`acks.py ack <id> done fixed <sha>[: <green lines>]`, the message's
  ack id found by its `fix order <id>`), starts the light jobs' proof detached and, once it is decided, runs
  `tollman.py fixed` by code (deterministic first).
"""

import datetime as dt
import re
import sys
import time
import zlib
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import fix_proof
import generated
import mtm_scan
import train_state
from carrier import Done, git
from orders_open import close, stopped, told_finished, unpushed
from orders_text import TEXT, proof_text
from tick import act

MAIN = "main"  # `order main`: the barn's red, fixed by the tollman's own hand (D29)
OWN_FIX = "tollman-train-fix"
CLI = Path(__file__).with_name("tollman.py")
FIXED = re.compile(r"\bfixed\s+([0-9a-f]{7,40})\b")
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
    n = sum(1 for e in rows if e["kind"] == "order" and e.get("field") == field and not e.get("also"))
    return f"{field}-fix-{1 + n}"


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
          smuggle: bool = False, post: str | None = None, jobs: list[str] | None = None) -> tuple[int, str, list[dict]]:
    """The order for `field` (a car of the standing red train, `main`, with `smuggle` a smuggling field: its
    smuggle conflicts with or broke the train, plan 0360 step 18; with `post` a car of that landed train, its red
    after the merge): its exit, its line and its actions (the foreman's message or the own session's wake), which
    the caller executes. `jobs`: the gate jobs its fix must turn green, else those its `why` or the train's red names
    (fix_proof.named)."""
    main = mtm_scan.main_checkout(top)
    rows = train_state.lines(main)
    train = train_state.standing(rows)
    if why_not := refusal(train, field, smuggle, post):
        return 1, why_not, []
    early = train["state"] == "landing" and not post
    open_ = train["post"] if post else train["orders"] if early else []
    jobs = list(dict.fromkeys(jobs or [])) or fix_proof.named(top, why, train.get("why") or "")
    if o := next((o for o in open_ if o["field"] == field), None):
        if more := [j for j in jobs if j not in (o.get("jobs") or [])] * early:
            return also(top, main, train, o, why, run, more, panes, now)
        return 0, f"fix order {o['id']} for {field} stands already: no second one while it is open", []
    base, carrier = git(top, "rev-parse", "HEAD")[1], git(top, "branch", "--show-current")[1] or Path(top).name
    told = publish(top, base)
    if told.startswith("not"):
        return 1, f"no fix order: {told}", []
    oid, branch = next_id(rows, field), OWN_FIX if field == MAIN else f"{field}-train-fix"
    train_state.append(main, "order", Path(top).name, now, train=train["train"], field=field, branch=branch, base=base,
                       why=why, run=run or train.get("run"), id=oid, post=post, jobs=jobs or None)
    words = {"id": oid, "field": field, "train": train["train"],
             "red": why if early or post else train.get("why") or train.get("status"), "early": TEXT["early"] * early,
             "run": run or train.get("run") or "none", "why": why, "carrier": carrier, "branch": branch,
             "base": base[:12], "rid": run or train.get("run") or "", "where": top, "post": post,
             "proof": proof_text(top, jobs)}
    key = f"order:{train['train']}:{field}:{oid.rsplit('-', 1)[1]}"
    if field == MAIN:
        a = act("trains", "fix-order-main", "wake", key=key, text=TEXT["main"].format(**words), evidence=words)
    else:
        a = act("trains", "fix-order", "send", field, pane=panes.get(field), key=key,
                text=TEXT["post" if post else "order"].format(**words))
    return 0, f"fix order {oid}: {field} fixes train {train['train']} on {branch} from {base[:12]}" + (
        f"; {told}" if told else ""), [a]


def also(top: str, main: str, train: dict, o: dict, why: str, run: str | None, jobs: list[str], panes: dict,
         now=None) -> tuple[int, str, list[dict]]:
    """Another red job of the field with the open early order `o` (plan 0522 D16): an `order` line `also` adds `jobs`
    to it (train_state.py), and the foreman is told this red too; one answer fixes both."""
    train_state.append(main, "order", Path(top).name, now, train=train["train"], field=o["field"], id=o["id"],
                       also=o["id"], why=why, run=run or o.get("run"), jobs=jobs)
    text = TEXT["also"].format(id=o["id"], field=o["field"], why=why, run=run or o.get("run") or "none",
                               branch=o["branch"], proof=proof_text(top, jobs))
    a = act("trains", "fix-order", "send", o["field"], pane=panes.get(o["field"]), text=text,
            key=f"order:{train['train']}:{o['field']}:also:{','.join(jobs)}")
    return 0, f"fix order {o['id']} for {o['field']}: also {', '.join(jobs)}", [a]


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


WAIT = 30  # seconds `fixed` waits for a landing's process to end after its run finished (L47)
POST_WAITS = ("formed", "landing", "paused", "split")  # a post-merge fix: the landing's process merges it (next_train)


def still_lands(top: str, main: str, train: dict, now=None) -> str:
    """Why the `landing` train's run is not over for a fix (L34), or "" once it is: its landing's process is gone
    (L108: stopped by signal, no red line), also when it ends within WAIT s of the run the watch told finished (L47).
    Over, the red line is written here as the round's settle writes it (an early order: `fixing`), unless it landed."""
    alive = lambda: train_state.alive(train.get("pid"))  # noqa: E731
    for _ in range(WAIT if alive() and told_finished(main, train) else 0):
        time.sleep(1)
        if not alive():
            break
    if alive():
        return "the train's land run still runs; the fix is merged after it ends"
    result = train_state.result(main) or {}
    if result.get("status") in ("landed", "nothing") or (result.get("status") == "shipping" and result.get("commit")):
        return "the train landed: the round settles it, its early orders ride the next train"
    train_state.append(main, "red", Path(top).name, now, train=train["train"], status=result.get("status") or "ended",
                       run=result.get("run") or train.get("land_run"),
                       why="its landing's process is gone: red line by `fixed` (L47, L108)")
    return ""


def fixed(top: str, field: str, sha: str | None, panes: dict, now=None, proof: str = "", unproven: str = "",
          redundant: bool = False) -> tuple[int, str, list[dict]]:
    """The answer to `field`'s open order: merged, or refused with the foreman told why. `proof`: the answer's text
    (its green lines), `unproven`: the session's why for taking it without proof (fix_proof.py); `redundant` (L56):
    the order closed on the carrier's head, its fix in the train already."""
    main = mtm_scan.main_checkout(top)
    train = train_state.standing(train_state.lines(main))
    o = next((o for o in (train or {}).get("orders", []) if o["field"] == field), None)
    p = None if o else next((p for p in (train or {}).get("post", []) if p["field"] == field), None)
    if o and train["state"] == "landing" and (why := still_lands(top, main, train, now)):
        return 1, f"fix order {o['id']} waits: {why}", []
    train = train_state.standing(train_state.lines(main)) if o else train
    if p and train["state"] in POST_WAITS:
        return 1, f"fix order {p['id']} waits: the landing merges it before its run starts, else the next train", []
    if not p and (not train or train["state"] != "fixing" or not o):
        return 1, f"no open fix order for {field}", []
    o = o or p
    if redundant:
        return close(top, main, train, o, now)
    code, commit = proven(top, main, o, sha, proof, unproven)
    if code == 2:
        return 1, f"fix order {o['id']} waits: {commit}", []
    code, commit = (code, commit) if code else take(top, main, train, o, sha, now, unproven)
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


def proven(top: str, main: str, o: dict, sha: str, proof: str, unproven: str = "", foreground: bool = True) -> Done:
    """(0, "") when `sha` is checked and proven green (or the session takes it `unproven`), (1, why) refused, (2, why)
    its proof runs or has not run; with `foreground` a proof not run yet runs here (the round starts it detached:
    `answers`; a landing's process never waits for one: next_train.py)."""
    if why := check(top, o, sha):
        return 1, why
    if unproven:
        return 0, ""
    state, why = fix_proof.verdict(top, main, o, sha, proof)
    if state == "start" and foreground:
        fix_proof.run(top, main, o["id"], sha)
        state, why = fix_proof.verdict(top, main, o, sha, proof)
    return {"ok": 0, "no": 1}.get(state, 2), why


def take(top: str, main: str, train: dict, o: dict, sha: str, now=None, unproven: str = "") -> Done:
    """The proven answer `sha` merged into the carrier, its `fixed` line written: (0, the merge) or (1, why)."""
    code, commit = merge(top, o, sha)
    if not code:
        train_state.append(main, "fixed", Path(top).name, now, train=train["train"], field=o["field"], id=o["id"],
                           sha=sha, commit=commit, unproven=unproven or None)
    return code, commit


def answered(o: dict, log: list[dict], what: str = "fix order", word=FIXED) -> tuple[str, str] | None:
    """The sha the order's message's ack answers with (`done fixed <sha>`; a resolve order's `word`, resolve.py) and
    the ack's text (its proof), or None."""
    asks = {e["id"] for e in log if e.get("kind") == "ask-ack" and e.get("id")
            and f"{what} {o['id']} " in (e.get("text") or "")}
    return next(((m.group(1), e.get("note") or "") for e in reversed(log) if e.get("kind") == "ack"
                 and e.get("id") in asks and e.get("what") == "done" and (m := word.search(e.get("note") or ""))),
                None)


def answers(top: str, rows: list[dict], log: list[dict], now: dt.datetime | None = None) -> list[dict]:
    """The round's `fixed` runs: an open order whose message's ack says `done fixed <sha>`, once its proof is decided
    (a light job's proof started first, fix_proof.py); a post-merge order's only while no landing runs (the
    landing's process merges it itself, next_train.py, once its proof, started here, is green); an early order's
    also while a held train's landing is gone (`stopped`). An order with no answer whose fix is local only: one
    wake."""
    train = train_state.standing(rows) or {}
    out, now = [], now or dt.datetime.now(dt.timezone.utc)
    own = train.get("orders", []) if train.get("state") == "fixing" or stopped(top, train) else []
    later = train.get("state") in POST_WAITS  # a post-merge fix: proven now, merged by the landing (next_train.py)
    main = ""
    for o in own + train.get("post", []):
        if not (answer := answered(o, log)):
            out += [w for w in [unpushed(top, o, now)] if w]
            continue
        main = main or mtm_scan.main_checkout(top)
        (sha, note), state = answer, fix_proof.verdict(top, main, o, answer[0], answer[1])[0]
        if state == "start":  # the light jobs' proof, detached; a later round takes its result (plan 0522 D5)
            n = fix_proof.attempt(main, o["id"], sha) + 1
            out.append(act("trains", "fix-proof", "run", o["field"], key=f"proof:{o['id']}:{sha}:{n}",
                           argv=[sys.executable, str(fix_proof.CLI), "start", "--repo", top, o["id"], sha],
                           text=f"fix order {o['id']}: the proof of {o['field']}'s fix {sha[:12]} starts (try {n})"))
        if state in ("start", "wait") or (later and o in train.get("post", [])):
            continue
        argv = [sys.executable, str(CLI), "fixed", o["field"], sha, "--repo", top, "--proof", note]
        refused = act("trains", "fix-refused", "wake", key=f"stuck:fixed:{o['id']}:{sha}",
                      text=f"the fix {sha[:12]} of order {o['id']} was refused: `{' '.join(argv[1:5])}` says why")
        lines = f":{zlib.crc32(note.encode()):08x}" if fix_proof.GREEN.search(note) else ""  # an ack with new proof
        out.append(act("trains", "fixed", "run", o["field"], key=f"fixed:{o['id']}:{sha}{lines}", argv=argv,
                       on_fail=[refused], text=f"fix order {o['id']}: {o['field']} answered fixed {sha[:12]}"))
    return out
