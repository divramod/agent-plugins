"""The train engine's verbs on a car and on a red train (hal2 plan 0294 step 6, plan 0360 D3; moved out of engine.py
by plan 0375 step 4): `engine.py unhitch` and `engine.py retry`, also `tollman.py unhitch|retry`.

  engine.py unhitch <field> --why <text> [--by-user] [--repo <dir>]
      take a field's ready mark (`worktree queue ready <field> --clear`) of a wagon that rides no train. A car of
      a train that stands is refused (D3); a running landing is never stopped. Only the user's own `--by-user`
      takes a car of a red train out: the rest forms again (`tollman.py unhitch` at once, chain.py).
      `unhitch yard --by-user`: the yard's car of a red train; its files stay out of every train until they change
  engine.py retry --why <text> [--skip-pretest] [--repo <dir>]
      a red train lands again as it is (a flaky gate), on a fresh land run: the next `restart` commits an empty
      `chore(wagon-train): ... (retry <n>)` on the carrier, so the candidate is new and the red run never adopted
      again; `--skip-pretest`: a `skipped` pretest line with the why first, so its landing starts without the pretest
      (a red pretest that is the Mac's, not a car's)
"""

import datetime as dt

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import engine
import frozen
import train_state
from carrier import Done


def unhitch(repo: str, field: str, why: str, now: dt.datetime | None = None, user: bool = False) -> Done:
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
    code, out = (0, "") if its else engine.cli(["worktree", "queue", "ready", field, "--clear", "--json"], main)
    if code:
        return 1, f"{field} was not unhitched: {out[-300:]}"
    train_state.append(main, "unhitched", field, now, train=train["train"] if car else None, why=why, files=its,
                       by=frozen.USER if car else None)
    return 0, f"{field} unhitched: {why}" + ("; the rest of the train forms again" if car else "")


def retry(repo: str, why: str, now: dt.datetime | None = None, skip_pretest: bool = False) -> Done:
    main, _, train, _ = engine.here(repo)
    if not train or train["state"] != "red":
        return 1, "no red train without open fix orders stands: nothing to land again (a fix is `tollman.py fixed`)"
    if skip_pretest:  # the session's word: this red is the Mac's (pretest_train.before_landing lets it through)
        train_state.append(main, "pretest", train["carrier"], now, train=train["train"], seconds=0, result="skipped",
                           jobs=[], why=f"skipped by the session: {why}")
    train_state.append(main, "retry", train["carrier"], now, train=train["train"], why=why)
    return 0, f"train {train['train']} lands again at the next round{' without its pretest' * skip_pretest}: {why}"
