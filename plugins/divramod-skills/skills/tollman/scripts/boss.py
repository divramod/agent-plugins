"""The merge-to-main boss's rules as code (subskills/merge-to-main-boss, plan 0007 step 2), the tollman's duty
`mtm` since hal2 plan 0294 (the farmer skill's until then).

`plan(snap, ctx)` turns mtm_scan's snapshot into planned actions (see tick.py): what a rule settles is done by code,
messages are templates, and what needs judgment (a merge train, what an idle worktree waits for, an unclear flaky test,
a long landing) becomes a `wake` item with the finding as evidence. Keys and windows go to tick.fresh, which drops
what an earlier round did and what concerns a worktree waiting for the user. Every action carries a `key`; a key already in
the role's log within its window is not done again, so a quiet queue gives a quiet round.

State (flaky.md, last-scan.json, the scan's paused.json and priority.json) is the folder of the role the round runs
for: `ctx["wiring"]`'s, the tollman's without one, never the farmer's.
"""

import datetime as dt
import json
import re
import sys
from pathlib import Path

import farmer_frame
import mtm_scan
import transplant_mark
from tick import act

ROLE = "tollman"  # whose state folder and name, when the round's ctx names no wiring
BOSS = ROLE + " (merge-to-main boss)"
REWAKE = dt.timedelta(hours=1)  # the same judgment item wakes the model at most hourly
ORPHAN = dt.timedelta(hours=3)
STATE_WAKE = dt.timedelta(hours=24)  # an unchanged work-not-queued state wakes the model at most once a day
COMMITS = re.compile(r"^(\d+) commits? not on main, plan ([^\s,]+)")
JUDGE = ("active-long", "work-not-queued", "long-queue", "paused")
LANDS = ("held-idle", "reserved-idle", "red-holder", "waiter-gone")  # the kinds whose text tells a worktree to land or queue
TEXT = {
    "held-idle": BOSS + ": your failed landing holds the merge queue ({failure}). Fix the cause and rerun the "
                        "landing now (/merge-to-main). A test that fails only under load: say so in one line.",
    "red-holder": BOSS + ": your red {what} holds the merge queue ({failure}, attempt {attempts}) and blocks every newcomer. "
                         "Fix the reasons, commit and run it again now ({rerun}), as often as it takes until it lands; "
                         "your place is given up only on the user's or the farmer's word. A test that fails only under "
                         "load: say so in one line.",
    "reserved-idle": BOSS + ": you reserved the merge queue for your plan's finish and nothing lands. Finish and "
                            "land now (/merge-to-main).",
    "released": BOSS + ": your held landing has no session, so I released the merge queue. Fix it, then /merge-to-main "
                       "again to requeue.",
    "moves": BOSS + ": the merge queue moves again ({slot} was released).",
    "pause": BOSS + ": a landing runs ({slot}) and the load is high. Pause builds, tests, Docker builds and "
                    "benchmarks (/pause) until I say go.",
    "go": BOSS + ": go: /continue",
    "waiter-gone": BOSS + ": your merge-queue ticket has no live `reserve` process. Rerun `hal2-cli-git worktree "
                          "reserve --max-wait 25m --json` in a loop until it is your turn.",
}


def when(entry: dict) -> dt.datetime:
    return dt.datetime.fromisoformat(entry["at"])


def role_of(ctx: dict) -> str:
    return ctx["wiring"].role if ctx.get("wiring") else ROLE


def guarded_start(slot: str, w: dict, ctx: dict) -> list[str]:
    """The orphan start as orphan_start.py runs it (hal2 plan 0412, D3): the agents list is asked again right when the
    action is carried out and the start runs only into a field with no live session, a terminal host's included."""
    return [sys.executable, str(Path(__file__).resolve().parent / "orphan_start.py"), "--path", w.get("path", ""),
            "--slot", slot, "--main", ctx["main"], "--role", role_of(ctx), "--", "hal2-cli-git", "worktree", "run",
            slot, "--agent", "claude", "--detach", "--prompt", "/handoff c"]


def has_handoff(checkout: Path, plan: str) -> bool:
    """Is there a handoff `/handoff c` can continue from: the current plan's own, or the checkout's root file?"""
    own = checkout / "plans" / plan / "handoff.md" if plan and "/" not in plan else None
    return bool(own and own.is_file()) or (checkout / "HANDOFF.md").is_file()


class Planner:
    def __init__(self, snap: dict, ctx: dict):
        self.snap, self.ctx, self.now, self.log = snap, ctx, ctx["now"], ctx["log"]
        self.wt = {w["slot"]: w for w in snap["worktrees"]}
        self.queue = snap["queue"]
        self.out: list[dict] = []
        self.told: set[str] = set()

    def add(self, kind: str, do: str, slot: str = "-", window: dt.timedelta | None = None, **fields) -> None:
        if window:
            fields["window"] = window.total_seconds()
        self.out.append(act("mtm", kind, do, slot, **fields))

    def tell(self, slot: str, kind: str, text: str, key: str, window: dt.timedelta = REWAKE, **fields) -> None:
        self.add(kind, "send", slot, window, pane=self.wt.get(slot, {}).get("pane"), text=text, key=key, **fields)

    def ticket(self, slot: str) -> dict:
        return next((t for t in self.queue if t["slot"] == slot), {})

    def priority(self, f: dict) -> None:
        """hal2 orders the queue and keeps a listed worktree's place (`worktree queue order`, set by adapt-merge-queue or
        the role's `first`): the tick never re-ranks, it only takes a landed worktree off priority.json and tells the
        user. The run has a key (D22: every action carries one), fresh every hour like its notice."""
        slot = f["slot"]
        landed = any(x["slot"] == slot and x["outcome"] == "landed" for x in self.snap["landings"])
        if landed and not self.ticket(slot) and not self.wt.get(slot, {}).get("ahead"):
            role = role_of(self.ctx)
            self.add("priority-done", "run", slot, dt.timedelta(hours=1), key=f"priority-off:{slot}",
                     argv=[sys.executable, str(farmer_frame.SCRIPTS / "mtm_scan.py"), "priority", "--done", slot,
                           "--repo", self.ctx["main"], "--role", role], text=f"priority {slot} landed: done")
            self.add("priority-done", "notify", slot, text=f"{role}: your priority worktree {slot} has landed",
                     key=f"priority-done:{slot}", window=dt.timedelta(hours=1))

    def reservation(self, f: dict) -> None:
        """The queue waits at the front for a reservation without progress: the user decides, nothing is released."""
        self.add(f["kind"], "notify", f["slot"], text=f"{role_of(self.ctx)}: {f['why']}",
                 key=f"reservation-waits:{f['slot']}:{f.get('seq')}", window=dt.timedelta(hours=6))

    def red(self, f: dict) -> None:
        """A red holder (a failed smuggle or landing, plan 0370 D1, D6) is never released by a script: its session is
        woken (again every hour) to fix the reasons and rerun; one without a session is reported to the farmer, who or
        the user alone gives the place up (`worktree release --by farmer`)."""
        slot, seq = f["slot"], self.ticket(f["slot"]).get("seq")
        if self.wt.get(slot, {}).get("agent_state") not in (None, "ended"):
            rerun = "/smuggle" if f.get("what") == "smuggle" else "/merge-to-main"
            text = TEXT["red-holder"].format(what=f.get("what") or "landing", failure=f.get("failure") or f["why"],
                                             attempts=f.get("attempts") or 1, rerun=rerun)
            self.tell(slot, f["kind"], text, f"wake:{slot}:{seq}", REWAKE)
            return
        self.add(f["kind"], "notify", slot, dt.timedelta(hours=6), key=f"red-holder-gone:{slot}:{seq}",
                 text=f"{role_of(self.ctx)}: {slot}'s red {f.get('what')} holds the merge queue and has no session "
                      f"({f['why']}): start one (/handoff c) to fix and rerun; only you or the user release it "
                      f"(`hal2-cli-git worktree release {slot} --by farmer`)")

    def held(self, f: dict) -> None:
        """A held queue nobody moves, not red (a red holder is `red`'s). A holder with a live session is woken (again
        every hour) and never released: a landing keeps the queue until its fix lands (the user, 2026-10-06: "run
        landing until everything is fixed and merged and then release"). Only a holder without a session is released."""
        slot, seq = f["slot"], self.ticket(f["slot"]).get("seq")
        key, w = f"wake:{slot}:{seq}", self.wt.get(slot, {})
        if w.get("agent_state") not in (None, "ended"):
            text = TEXT[f["kind"]].format(failure=f.get("failure") or f["why"])
            self.tell(slot, f["kind"], text, key, REWAKE)
            return
        release = f"release:{slot}:{seq}"
        self.add("release", "run", slot, dt.timedelta(days=7), key=release,
                 argv=["hal2-cli-git", "worktree", "release", slot, "--by", "tollman", "--json"], text=f"released the queue held by {slot}",
                 why="no session")
        self.tell(slot, "released", TEXT["released"], f"released:{slot}:{seq}", dt.timedelta(days=7), after=release)
        for t in self.queue:
            if t["state"] == "waiting":
                self.tell(t["slot"], "moves", TEXT["moves"].format(slot=slot), f"moves:{slot}:{seq}:{t['slot']}",
                          after=release)

    def load_high(self, f: dict) -> None:
        landing = self.ticket(f["slot"]).get("landing")
        for slot in f.get("busy_slots", []):
            self.tell(slot, "pause", TEXT["pause"].format(slot=f["slot"]), f"pause:{landing}:{slot}",
                      dt.timedelta(days=1))

    def go(self) -> None:
        """Worktrees paused for a landing that no longer runs get their go."""
        head = self.queue[0] if self.queue else {}
        running = head.get("landing") if head.get("state") == "active" else None
        cutoff = self.now - dt.timedelta(hours=12)
        for e in self.log:
            key = e.get("key", "")
            if not key.startswith("pause:") or when(e) < cutoff:
                continue
            _, landing, slot = key.split(":", 2)
            if landing != str(running):
                self.tell(slot, "go", TEXT["go"], f"go:{landing}:{slot}", dt.timedelta(days=1))

    def flaky(self, f: dict) -> None:
        test = f["test"]
        flaky_md = mtm_scan.state_dir(self.ctx["main"], role_of(self.ctx)) / "flaky.md"
        if flaky_md.exists() and test in flaky_md.read_text():
            return
        load = any(test in x["tests"] and x["load_hint"] for x in self.snap["landings"])
        if load:  # a brief in the farmer's delegation ledger, never a message to the farmer (plan 0360 D30)
            evidence = {"finding": f, "landings": [x for x in self.snap["landings"] if test in x["tests"]]}
            argv = [sys.executable, str(Path(__file__).resolve().parent / "flaky_brief.py"), "place",
                    "--repo", self.ctx.get("top") or self.ctx["main"], "--test", test, "--slot", f["slot"],
                    "--why", f.get("why", ""), "--evidence", json.dumps(evidence, default=str),
                    "--role", role_of(self.ctx)]
            fail = act("mtm", "flaky-brief-failed", "wake", f["slot"], key=f"flaky-brief-failed:{test}",
                       text=f"the load-flaky test {test}'s brief was not placed in the farmer's ledger: place it by "
                            f"hand (flaky_brief.py place, instructions/mtm.md)", evidence=f)
            self.add("flaky", "run", f["slot"], dt.timedelta(days=7), key=f"flaky:{test}", argv=argv,
                     text=f"disable the load-flaky test {test}: a brief in the farmer's delegation ledger",
                     on_fail=[fail])
        else:
            self.add("flaky", "wake", f["slot"], REWAKE, key=f"flaky:{test}", text=f"flaky or real? {f['why']}",
                     evidence=f)

    def subservant(self, f: dict) -> None:
        """A parallel plan's servant (plans/LEAD) never lands: its merge-queue ticket wakes the tollman, the
        worktree never gets the /merge-to-main text and is never released by rule."""
        lead = f.get("lead") or self.wt.get(f["slot"], {}).get("lead")
        why = f["why"] if f["kind"] == "subservant-holds" else f"{mtm_scan.subservant(lead)}: {f['why']}"
        self.add("subservant-holds", "wake", f["slot"], REWAKE, key=f"subservant-holds:{f['slot']}", text=why,
                 evidence={**f, "lead": lead})

    def stale_transplant(self, mark: transplant_mark.Mark) -> None:
        """An open transplant past an hour: one note for the farmer (a `record`, board.sync's `note`; never a `send`,
        plan 0360 step 8, D9), keyed by the transplant (from, to, prepared), so the frame writes it once and not
        every round; both of its fields give the same key, planned once."""
        if not mark.stale or mark.key in self.told:
            return
        self.told.add(mark.key)
        self.add("transplant-stale", "record", mtm_scan.roles.slot_name(self.ctx["main"]), dt.timedelta(days=7),
                 key=mark.key, text=mark.report())

    def orphan(self, f: dict) -> None:
        """Orphaned work with a handoff (the plan's plans/<plan>/handoff.md, hal2 plan 0206, or the root HANDOFF.md)
        gets a session with /handoff c, else the tollman is woken. A servant's
        (plans/LEAD) restart is the same /handoff c, which continues its one step; never /merge-to-main. A servant whose work
        is all in its foreman's branch (no `missing`) is done: never restarted. One with a broken marker wakes the
        tollman: its foreman is unknown. A field in an open transplant (hal2 plan 0286: the source or the target of
        one `prepared` or `driven`, D29) is no orphan however old the transplant: it drives the field, so never a
        `/handoff c` or a wake (a driven source's work has moved). One older than an hour is a note for the farmer
        once instead (`stale_transplant`)."""
        slot, w = f["slot"], self.wt.get(f["slot"], {})
        lead = w.get("lead") or f.get("lead")
        if lead and not w.get("missing"):
            return
        mark = transplant_mark.of(slot, w.get("path", ""), self.ctx.get("transplants", []), self.now)
        if mark:
            self.stale_transplant(mark)
            return
        if lead and lead.get("bad"):
            self.add("orphan", "wake", slot, REWAKE, key=f"orphan:{slot}", text=f"orphaned work: {f['why']}",
                     evidence=f)
        elif (w.get("plan") or lead) and has_handoff(Path(w.get("path", "")), w.get("plan") or ""):
            self.add("orphan", "run", slot, ORPHAN, key=f"orphan:{slot}", argv=guarded_start(slot, w, self.ctx),
                     text=f"started a session in {slot} with /handoff c")
        else:
            self.add("orphan", "wake", slot, REWAKE, key=f"orphan:{slot}", text=f"orphaned work: {f['why']}",
                     evidence=f)

    def state_of(self, f: dict) -> tuple[str, str]:
        """(ahead, plan) of a work-not-queued finding: the commits not on main and the plan, from its text."""
        m = COMMITS.match(f.get("why", ""))
        w = self.wt.get(f["slot"], {})
        return (m.group(1), m.group(2)) if m else (str(w.get("ahead", "")), w.get("plan") or "-")

    def refused_at(self, slot: str, ahead: str) -> bool:
        """Did the field's last ack refuse (the board's `ack` lines come from the log's) with no new commit since?
        The commits then are those of the last work-not-queued wake before the ack (its text starts with them)."""
        acks = [e for e in self.log if e.get("kind") == "ack" and e.get("slot") == slot]
        if not acks or acks[-1].get("what") != "refused":
            return False
        at = when(acks[-1])
        before = [e for e in self.log if e.get("kind") == "work-not-queued" and e.get("slot") == slot
                  and e.get("what") and when(e) <= at]
        m = COMMITS.match(before[-1]["what"]) if before else None
        return bool(m and m.group(1) == ahead)

    def work_not_queued(self, f: dict) -> None:
        """One wake per state, not per hour (hal2 plan 0333 step 5): keyed by field, commits and plan for a day, and
        none at all for a field that refused (it waits on the user) while it has no new commit."""
        ahead, plan = self.state_of(f)
        if self.refused_at(f["slot"], ahead):
            return
        self.add(f["kind"], "wake", f["slot"], STATE_WAKE, key=f"work-not-queued:{f['slot']}:{ahead}:{plan}",
                 text=f["why"], evidence=f)

    def run(self) -> list[dict]:
        for f in self.snap["findings"]:
            kind = f["kind"]
            if kind == "subservant-holds" or (kind in LANDS and self.wt.get(f["slot"], {}).get("lead")):
                self.subservant(f)
            elif kind == "priority":
                self.priority(f)
            elif kind == "reservation-waits":
                self.reservation(f)
            elif kind == "red-holder":
                self.red(f)
            elif kind in ("held-idle", "reserved-idle"):
                self.held(f)
            elif kind == "load-high":
                self.load_high(f)
            elif kind == "waiter-gone":
                seq = self.ticket(f["slot"]).get("seq")
                self.tell(f["slot"], kind, TEXT[kind], f"waiter:{f['slot']}:{seq}", dt.timedelta(hours=2))
            elif kind == "flaky-candidate":
                self.flaky(f)
            elif kind == "work-without-agent":
                self.orphan(f)
            elif kind == "work-not-queued":
                self.work_not_queued(f)
            elif kind in JUDGE:
                self.add(kind, "wake", f["slot"], REWAKE, key=f"{kind}:{f['slot']}", text=f["why"], evidence=f)
        self.go()
        return self.out


def plan(snap: dict, ctx: dict) -> list[dict]:
    return Planner(snap, ctx).run()


def handler(item: dict, ctx: dict) -> list[dict]:
    """duty:mtm: scan (no fetch in a dry run), keep the scan for the role's status, plan."""
    role = role_of(ctx)
    snap = mtm_scan.snapshot(ctx["top"], 24, fetch=not ctx["dry"], role=role)
    if any(f["kind"] == "work-without-agent" for f in snap["findings"]):  # the transplants matter to an orphan only
        ctx = {**ctx, "transplants": transplant_mark.history(ctx["main"])}
    if not ctx["dry"]:
        (mtm_scan.state_dir(ctx["main"], role) / "last-scan.json").write_text(json.dumps(snap, indent=1))
    return plan(snap, ctx)
