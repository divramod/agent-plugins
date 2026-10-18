"""The merge queue's mode (hal2 plan 0360 step 25, D74 to D76): `hal2-cli-git worktree queue --json` carries
`mode: {mode, by, at, why}`, `production` (the default, also without the key) or `smuggle`. Only the user switches it
(`hal2-cli-git worktree queue mode smuggle --by user`, or the farmer relaying the user's word).

In smuggle mode the tollman sleeps (its modes.py) and `/merge-to-main` smuggles instead of hitching; the farmer's `lead` round
tells every finished, harvested field (a hitched ticket waiting in the queue, no servant's, no train's car, not the
tollman's own field) "smuggle mode: run /merge-to-main now", once per field and mode period (the key carries the mode's `at`),
without asking the user (D75 3). The tollman's modes.py reads the mode through `of` too.

Each entry has its own mode too (hal2 plan 0365 D5, D9): `queue --json` gives it as `mode` (none: the queue's) and
`effective_mode`; the `lead` duty tells exactly the hitched fields whose effective mode is smuggle, in production mode too
(an entry set to smuggle), and none whose effective mode is production, in smuggle mode too. An older hal2-cli-git
without the fields reads as the queue's mode.
"""

import duties
import mtm_scan
from tick import act

PRODUCTION, SMUGGLE = "production", "smuggle"
PERIOD = 30 * 24 * 3600  # a smuggle period's word is never repeated within it (its key names the period)
QUEUE = ["hal2-cli-git", "worktree", "queue", "--json"]
LEAD = duties.LEAD
TEXT = (LEAD + ": smuggle mode: run /merge-to-main now. The merge queue is in smuggle mode since {at} (by {by}): the tollman "
        "carries no train of a smuggle-mode crop, so your hitched crop ({head}) is smuggled: /merge-to-main reads the mode and runs the "
        "smuggle itself (hal2 plan 0360 D75, D76); this is the farmer's word, no need to ask the user.")

TEXT_OWN = (LEAD + ": smuggle mode: run /merge-to-main now. Your entry in the merge queue is set to smuggle (the user's word): "
            "the tollman leaves your hitched crop ({head}) out of its trains, so /merge-to-main reads your slot's mode and "
            "runs the smuggle itself (hal2 plan 0365 D5, D9); this is the farmer's word, no need to ask the user.")


def of(doc: dict | None) -> dict:
    """The queue's mode from `queue --json`: {mode, by, at, why}; production when the key is missing or empty."""
    mode = (doc or {}).get("mode") or {}
    return mode if mode.get("mode") else {"mode": PRODUCTION, "by": None, "at": None, "why": None}


def smuggle(mode: dict) -> bool:
    return mode.get("mode") == SMUGGLE


def effective(entry: dict, mode: dict) -> str:
    """An entry's effective mode: `effective_mode`, else its own `mode`, else the queue's (plan 0365 D5)."""
    return entry.get("effective_mode") or entry.get("mode") or mode.get("mode") or PRODUCTION


def hitched(entry: dict) -> bool:
    """A hitched entry still waiting: its harvest is ready, no landing of it has started."""
    return bool(entry.get("ready")) and entry.get("state", "waiting") == "waiting"


def harvested(t: dict) -> bool:
    """A finished field that waits for a train: hitched, waiting, no train's car, no servant's, no role's field."""
    slot = str(t.get("slot") or "")
    return bool(t.get("ready")) and t.get("state", "waiting") == "waiting" and not t.get("rides_with") \
        and not t.get("train") and slot.isdigit() and int(slot) < 30


def plan(item: dict, ctx: dict, doc: dict | None = None) -> list[dict]:
    """One `send` per harvested field whose effective mode is smuggle (see the module doc); `doc` is `queue --json`
    (read when None). The key names the period: the queue's mode `at`, or for an entry's own mode its ticket."""
    doc = doc if doc is not None else mtm_scan.run_json(QUEUE, ctx["main"]) or {}
    mode = of(doc)
    out = []
    for t in doc.get("queue", []):
        if not harvested(t) or effective(t, mode) != SMUGGLE:
            continue
        own = t.get("mode") == SMUGGLE
        period = f"entry{t.get('seq')}" if own else mode.get("at")
        out.append(act("lead", "smuggle-mode", "send", t["slot"], pane=ctx.get("panes", {}).get(t["slot"]),
                       key=f"smuggle-mode:{t['slot']}:{period}", window=PERIOD,
                       text=(TEXT_OWN if own else TEXT).format(at=mode.get("at"), by=mode.get("by"),
                                                                head=t["ready"].get("head", "")[:12])))
    return out


def plan_lead(item: dict, ctx: dict, doc: dict | None = None, scan: dict | None = None) -> list[dict]:
    """duty:lead: the development foreman's round (duties.plan_lead), then the smuggle mode's word (`plan`)."""
    return duties.plan_lead(item, ctx, scan) + plan(item, ctx, doc)
