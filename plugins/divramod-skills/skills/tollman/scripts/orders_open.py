"""The fix orders' upkeep beside the answer (orders.py, hal2 plan 0490 step 10): the watch's word that the run
finished (L47), a redundant order closed on the carrier's head (L56), a held train whose landing is gone (L108) and
one wake for a fix left on its local branch (L106)."""

import datetime as dt
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import train_state
from carrier import git
from orders_text import TEXT
from tick import act

STALE = 30 * 60  # an order this old with its fix only local wakes the session (L106)


def told_finished(main: str, train: dict) -> bool:
    """The 1-minute watch told the run of the train's current start finished (`done:<run>`, watch_events.py)."""
    import watch_events  # its imports reach far: only here
    s = watch_events.state(main)
    return (s.get("train"), s.get("started")) == (train["train"], train.get("started")) and \
        f"done:{s.get('run')}" in (s.get("seen") or [])


def close(top: str, main: str, train: dict, o: dict, now=None) -> tuple[int, str, list[dict]]:
    """A redundant order (L56: two orders for one red, the first fix covered both) closed on the carrier's head:
    nothing merged, a `fixed` line marked `redundant`."""
    head = git(top, "rev-parse", "HEAD")[1]
    train_state.append(main, "fixed", Path(top).name, now, train=train["train"], field=o["field"], id=o["id"],
                       sha=head, commit=head, redundant=True)
    return 0, f"fix order {o['id']} closed as redundant on the carrier's head {head[:12]}", []


def stopped(top: str, train: dict) -> bool:
    """A `landing` train under the hold whose landing's process is gone (L108): nothing restarts it (L107), so its
    answered early orders are taken now (`fixed` writes its red line)."""
    import hold  # the hold file of the main checkout
    return train.get("state") == "landing" and not train_state.alive(train.get("pid")) \
        and bool(hold.of(mtm_scan.main_checkout(top)))


def unpushed(top: str, o: dict, now: dt.datetime) -> dict | None:
    """One wake for an order older than STALE whose fix sits on its local branch (`<NN>-train-<n>-<a>-fix`),
    descending from its base,
    but not on origin (L106: the pre-push hook refused it, the foreman's session ended), else None."""
    at = dt.datetime.fromisoformat(str(o.get("at") or now.isoformat()).replace("Z", "+00:00"))
    if (now - at).total_seconds() < STALE:
        return None
    branch = o["branch"]
    code, local = git(top, "rev-parse", "-q", "--verify", f"refs/heads/{branch}")
    pushed = git(top, "rev-parse", "-q", "--verify", f"refs/remotes/origin/{branch}")[1]
    if code or local == pushed or git(top, "merge-base", "--is-ancestor", o["base"], local)[0]:
        return None
    return act("trains", "fix-unpushed", "wake", o["field"], key=f"unpushed:{o['id']}:{local}",
               text=TEXT["unpushed"].format(id=o["id"], field=o["field"], sha=local[:12], branch=branch))
