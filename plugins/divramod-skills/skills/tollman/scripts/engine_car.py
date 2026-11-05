"""The train engine's verbs on a car and on a red train (hal2 plan 0294 step 6, plan 0360 D3; moved out of engine.py
by plan 0375 step 4): `engine.py unhitch` and `engine.py retry`, also `tollman.py unhitch|retry`.

  engine.py unhitch <field> --why <text> [--by-user --words <the user's words>] [--repo <dir>]
      only the user's own command (`--by-user`; the user, 2026-11-04: "when a car has hitched, it will never leave the
      queue again"): take a field's ready mark (`worktree queue ready <field> --clear`). A car of
      a train that stands is refused (D3); a running landing is never stopped. Only the user's own `--by-user`
      takes a car of a red train out: the rest forms again (`tollman.py unhitch` at once, chain.py).
      `unhitch yard --by-user`: the yard's car of a red train; its files stay out of every train until they change
  engine.py retry --why <text> [--skip-pretest] [--repo <dir>]
      a red train lands again as it is (a flaky gate), on a fresh land run: the next `restart` commits an empty
      `chore(wagon-train): ... (retry <n>)` on the carrier, so the candidate is new and the red run never adopted
      again; `--skip-pretest`: a `skipped` pretest line with the why first, so its landing starts without the pretest
      (a red pretest that is the Mac's, not a car's). A train still `landing` whose landing's process is gone (or
      ends within orders.WAIT s of its finished run) is red for it: the red line is written as `fixed` writes it
      (orders.still_lands, L139: train 31's retry came before the round's red line). A refusal names the train's
      state and its open orders; a post-merge order never blocks a retry. A retry never touches a mark (a hitch is
      forever).
"""

import datetime as dt

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import engine
import frozen
import orders
import train_state
from carrier import Done


def unhitch(repo: str, field: str, why: str, now: dt.datetime | None = None, user: bool = False,
            words: str = "") -> Done:
    main, _, train, _ = engine.here(repo)
    its = train["yard"] if train and field == train_state.YARD else None  # the yard's car: no ticket to clear
    if field == train_state.YARD and not its:
        return 1, "the yard rides no train that stands: nothing to unhitch"
    car = bool(train and (its or any(c["field"] == field for c in train["cars"])))
    if car and train["state"] not in ("red", "fixing", "split"):
        return 1, (f"{field} rides train {train['train']} ({train['state']}): a running landing is never stopped; "
                   "unhitch it once the train is red")
    if car and not user:
        return 1, frozen.refused(train, f"unhitching {field}")
    if not user:  # the user, 2026-11-04: "when a car has hitched, it will never leave the queue again"
        return 1, (f"{field} is not unhitched: a hitched wagon never leaves the queue (the user, 2026-11-04: \"when a "
                   "car has hitched, it will never leave the queue again\"); only the user's own `--by-user` does it")
    if not words.strip():  # plan 0611 D13: the user's order is a record that carries the user's own words
        return 1, f"{field} is not unhitched: `--by-user` needs `--words \"<the user's words>\"` (plan 0611 D13)"
    code, out = (0, "") if its else engine.cli(["worktree", "queue", "ready", field, "--clear", "--json"], main)
    if code:
        return 1, f"{field} was not unhitched: {out[-300:]}"
    train_state.append(main, "unhitched", field, now, train=train["train"] if car else None, why=why, files=its,
                       by=frozen.USER if car else None)
    import records_kinds  # plan 0611: the user's order, open until code sees its effect
    records_kinds.add(main, "user-order", field, f"unhitch {field} (the user): {why}", "user",
                      records_kinds.train_event("unhitched", train=train["train"] if car else None, field=field), now,
                      words=words.strip(), train=train["train"] if car else None, order="unhitch")
    return 0, f"{field} unhitched: {why}" + ("; the rest of the train forms again" if car else "")


def retry(repo: str, why: str, now: dt.datetime | None = None, skip_pretest: bool = False) -> Done:
    main, _, train, top = engine.here(repo)
    wait = orders.still_lands(top, main, train, now) if train and train["state"] == "landing" else ""
    train = train if wait or not train or train["state"] != "landing" else engine.here(repo)[2]  # its red line (L139)
    if not train or train["state"] != "red":
        return 1, refusal(train, wait)
    if skip_pretest:  # the session's word: this red is the Mac's (pretest_train.before_landing lets it through)
        code, tree = engine.git(top, "rev-parse", "HEAD^{tree}")  # this tree only: a later fix is pretested (0522)
        train_state.append(main, "pretest", train["carrier"], now, train=train["train"], seconds=0, result="skipped",
                           jobs=[], why=f"skipped by the session: {why}", tree=None if code else tree or None)
    train_state.append(main, "retry", train["carrier"], now, train=train["train"], why=why)
    import records_kinds  # plan 0611: the restart promised, open until the train's next `started` line
    records_kinds.add(main, "restart", train["carrier"], f"train {train['train']} lands again: {why}", "tollman",
                      records_kinds.train_event("retry", train=train["train"]), now, train=train["train"], of="train")
    return 0, f"train {train['train']} lands again at the next round{' without its pretest' * skip_pretest}: {why}"


def refusal(train: dict | None, wait: str = "") -> str:
    """Why `retry` lands nothing: no train, or its state with the open fix orders and post-merge orders (L139: a post
    order rides the train and never blocks a retry; an open fix order's `fixed` lands the cars again)."""
    if not train:
        return "no train stands: nothing to land again"
    ids = lambda rows: ", ".join(o.get("id") or "?" for o in rows) or "none"  # noqa: E731
    why = f"train {train['train']} is {train['state']}" + (f" ({wait})" if wait else "")
    fix = ("; its open fix orders: " + ids(train.get("orders") or []) + " (their `tollman.py fixed` lands the cars "
           "again)") if train.get("orders") else ""
    post = ("; its post-merge orders " + ids(train.get("post") or []) + " ride it and never block a retry"
            ) if train.get("post") else ""
    return f"{why}: only a red train lands again by retry{fix}{post}"
