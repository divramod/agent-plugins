"""The duty `mainred` (hal2 plan 0360 step 8, D9, D29, D30): a red main is the tollman's, no longer the farmer's.

Reads the farmer's CI scan (ci_scan.py, shared code: the newest run per workflow on the default branch) and takes
its findings of kind `main-red`:
- a failed log that matches the transient patterns (transient.py): `gh run rerun <run> --failed` by code, once per
  run (its key `main-red-rerun:<run>` in the log); nobody is woken
- else, or red again after its one rerun: one wake of the tollman's session with the log's tail, key
  `main-red:<run>`. Its answer is `tollman.py order main` (orders.py, own_fix.py): with a red train standing the fix
  rides in it (D29), with no train it is the first car of the next train. While a train is formed or landing the
  wake waits (that train's own triage reads its red first); while the own fix waits to ride nobody is woken again.
A run whose key is in the log is not read again (no `gh run view` per round).
"""

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import ci_scan
import own_fix
import train_state
import transient
import triage
from tick import act

TEXT = ("main is red: {why} ({url}){again}. Judge the tail (`gh run view {run} --log-failed` has all of it); a real "
        "fault: `tollman.py order main --why <text> --run {url}` (a red train standing: the fix rides in it; no "
        "train: the first car of the next train); a fault outside the code (a runner, a secret): a board note for "
        "the farmer (`board.py post --kind note --from <your field> --to farmer-<repo> --text ...`), which reads it "
        "when it asks.")


def plan(item: dict, ctx: dict, scan: dict | None = None, log_failed=None,
         rows: list[dict] | None = None) -> list[dict]:
    scan = scan if scan is not None else ci_scan.scan(ctx["top"], False)
    log_failed = log_failed or (lambda run: ci_scan.run(["gh", "run", "view", str(run), "--log-failed"], ctx["main"]))
    rows = rows if rows is not None else train_state.lines(ctx["main"])
    train, seen = train_state.standing(rows), {e.get("key") for e in ctx.get("log", [])}
    waits = (train and train["state"] not in ("red", "fixing")) or own_fix.waiting(rows)
    out = []
    for f in scan.get("findings", []):
        run = f["run"]
        if f["kind"] != "main-red" or f"main-red:{run}" in seen:
            continue
        rerun = f"main-red-rerun:{run}"
        tail = (log_failed(run) or "")[-triage.LOG:]
        if rerun not in seen and (match := transient.TRANSIENT.search(tail)):
            out.append(act("mainred", "main-red-rerun", "run", "-", key=rerun,
                           argv=["gh", "run", "rerun", str(run), "--failed"],
                           text=f"reran {f['workflow']} on main (transient: {match.group(0)})"))
        elif not waits:
            again = ", red again after its one rerun" if rerun in seen else ""
            out.append(act("mainred", "main-red", "wake", "-", key=f"main-red:{run}",
                           text=TEXT.format(why=f["why"], url=f.get("url"), run=run, again=again),
                           evidence={"finding": f, "log_tail": tail[-triage.TAIL:]}))
    return out


def handler(item: dict, ctx: dict) -> list[dict]:
    """duty:mainred: the CI scan, then the round's actions."""
    return plan(item, ctx)
