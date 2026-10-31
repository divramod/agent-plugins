"""A red step of a running job, acted on at once (hal2 plan 0490 step 25, D25): the watch's fresh `step-failed` events
(step_red.py) go through the step's triage (run_triage_step.py) and the finished run's dispatch rules
(run_triage_act.py, run_triage_dedup.py, run_triage_text.py) in the same pass; wired by run_triage_wire.started.

- `runner`: a record, nobody; `unsure`, `unplaced`: a record, nothing ordered, the job's end decides (its red goes
  the way of today: early_order.py, post_merge.py, then the finished run's triage, which wakes the session once)
- `car`, `pipeline`: dedup first (an order of this run naming the job, a hitched wagon touching the unit's files, the
  owner's open order, a running plan): a record; else one acked order to a live owner, else a board note. The order
  is keyed `triage:<run>:<bare job>` as the finished run's triage keys its own, and it lands where the job's red
  would put it: before the merge `tollman.py order <car>` (an early order: early_order.py sees it and orders nothing
  at the job's end), after it `--post <train>` (its `run` is the run: post_merge.py and the triage's dedup see it,
  fix_wait counts its fix). A failed order wakes the session (`step-red`)
- the job's end (its `job failed` event): the job's failed log is read (one `gh run view --job <id> --log-failed`,
  only for a job a step order went out for) and the finished run's rule (run_triage.classify) rechecks the step's
  verdict: the same owner, a record; another, one `step-red` wake with both, never a second order (D11)

Each step verdict is kept in run-triage.json (the run's entry, `steps`: key, job, job_id, step, unit, kind, owner,
target, ordered); in smuggle mode nothing is planned (the tollman sleeps). A dry round plans and keeps nothing.
"""

import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import run_triage_act as act_
import run_triage_dedup as dedup_
import run_triage_step as step
import run_triage_text as words
import run_triage_wire as wire
import stack_red
from tick import act

CLI = Path(__file__).with_name("tollman.py")
KIND = "step-red"  # the session's wake (instructions/trains.md)
FAILED = "step-failed"


def record(v: dict, why: str, suffix: str = "step") -> dict:
    return act("trains", "step-record", "record", "-", key=f"{v['key']}:{suffix}", text=f"{words.head(v)}: {why}")


def order(top: str, ev: dict, v: dict, train: dict, standing: dict | None, where: str, pane: str | None) -> dict:
    """The acked order for the step's red to its owner, on the train `where` names (see the module doc)."""
    field, url, rid, bare = v["owner"], ev.get("url") or "", ev["run"], stack_red.bare(ev["job"])
    key = f"triage:{rid}:{bare}"
    why = f"{ev['job']}: step {ev['step']} red while the job runs | {words.why([v])}"[:words.WHY]
    wake = act("trains", KIND, "wake", key=f"{KIND}:{rid}:{bare}", evidence={"run": url, "train": train, "verdict": v},
               text=f"tollman: the fix order to {field} for {words.unit(v)} (step {ev['step']} red while {ev['job']} "
                    f"runs, {url}) failed: judge it, then `python3 {CLI} order <field> [--post {train['train']}] "
                    f"--why ... --run {url}`")
    if where == "current":
        argv = [sys.executable, str(CLI), "order", field, "--why", why, "--run", url, "--repo", top]
        return act("trains", "triage-order", "run", field, key=key, argv=argv, on_fail=[wake],
                   text=f"train {train['train']}: fix order to {field} for {words.unit(v)}, its step red while the job "
                        "runs: fixed in place before the merge")
    send = act("trains", "triage-order", "send", field, pane=pane, key=key if not standing else f"{key}:send",
               text=words.order_text([v], train, url, "red after its merge"))
    if not standing:
        return send
    argv = [sys.executable, str(CLI), "order", field, "--post", train["train"], "--why", why, "--run", url, "--repo",
            top]
    return act("trains", "triage-order", "run", field, key=key, argv=argv, on_fail=[send],
               text=f"train {train['train']}: fix order to {field} for {words.unit(v)}, its step red after the merge "
                    f"(the fix rides train {standing['train']})")


def actions(top: str, main: str, ev: dict, v: dict, train: dict, standing: dict | None, where: str,
            panes: dict | None = None, done=(), dedup: dict | None = None, read=dedup_.touched) -> list[dict]:
    """The pass's actions for one step red's verdict `v` (see the module doc); `done`: the log's keys."""
    kind, out = v["kind"], []
    if kind in act_.QUIET:
        out.append(record(v, f"{kind}: nobody ordered"))
    elif kind not in step.PLACED:
        out.append(record(v, f"{kind}: nothing ordered yet ({v.get('missing')}); the job's end reads its log"))
    elif why := dedup_.match(v, dedup or {}, main, ev.get("created"), read):
        out.append(record(v, f"{kind}: no order, {why}"))
    elif v.get("owner") and v.get("live"):
        out.append(order(top, ev, v, train, standing, where, (panes or {}).get(v["owner"])))
    else:
        out.append(act_.note(top, v, train, ev.get("url") or ""))
    return [a for a in out if a["key"] not in set(done)]


def remember(main: str, ev: dict, v: dict, where: str, ordered: bool) -> None:
    """The step verdict kept in the run's run-triage.json entry (`steps`), once per key."""
    row = {"key": v["key"], "job": ev["job"], "job_id": ev.get("job_id"), "step": ev["step"],
           "unit": v["evidence"]["unit"], "kind": v["kind"], "owner": v.get("owner"), "target": where,
           "ordered": ordered, "at": ev.get("at")}

    def change(e: dict) -> None:
        e.setdefault("url", ev.get("url"))
        e["steps"] = [s for s in e.get("steps") or [] if s.get("key") != row["key"]] + [row]
    wire.update(main, ev["run"], change)


def awake(main: str, doc: dict | None) -> dict | None:
    """The queue's doc (read when None), or None in smuggle mode (minute.awake's rule; minute is not imported)."""
    import modes
    doc = (mtm_scan.run_json(mtm_scan.QUEUE, main) or {}) if doc is None else doc
    return None if modes.asleep(modes.of(doc)) else doc


def on_events(top: str, main: str, fresh: list[dict], watched: dict, dry: bool = False, doc: dict | None = None,
              ctx: dict | None = None, data=None) -> list[dict]:
    """The pass's actions for its fresh `step-failed` events and the `job failed` of a job a step order went out
    for (the recheck); [] without either. `ctx`: the round's {panes, log} (read when None); `data(top, main, train,
    ctx)`: the triage's context (run_triage_step_read.context, a test's fake)."""
    import run_triage_step_read as reads
    steps = [e for e in fresh if e["kind"] == FAILED]
    ends = reads.rechecked(main, fresh, watched)
    if not (steps or ends) or (doc := awake(main, doc)) is None:
        return []
    ctx = ctx if ctx is not None else reads.round_context(top, main)
    train, standing = wire.train_of(reads.rows(main), watched.get("train"))
    tctx = (data or reads.context)(top, main, train, ctx, standing, doc)
    done, out = {e.get("key") for e in ctx.get("log") or [] if e.get("key")}, []
    for ev in steps:
        v, where = step.verdict(ev, tctx), step.target(ev, train, standing)
        planned = actions(top, main, ev, v, train, standing, where, ctx.get("panes") or {}, done, tctx["dedup"])
        out += planned
        if not dry:
            remember(main, ev, v, where, any(a["kind"] == "triage-order" for a in planned))
    for end, kept in ends:
        out += reads.recheck(top, main, end, kept, train, tctx, done)
    return out
