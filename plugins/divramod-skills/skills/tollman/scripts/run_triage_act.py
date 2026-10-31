"""The dispatch of a finished land run's triage (hal2 plan 0490 step 2; D5, D11, D12): step 1's verdicts
(run_triage.triage) as the round's planned actions, the dicts `tick.act` builds and `tick.execute` runs. Pure
planning over data; step 3 wires it. By kind:

- `needs-red`, `runner`, `flake`: a `record` line, nobody ordered; a budget flake red before (L13): the flaky brief
- `repeat`, `file`, `pipeline`, `car` with a live owner: matched first (run_triage_dedup.match: a hitched wagon whose
  commits touch the red's files, an open fix order, a running plan) and then a `record` naming the match; else ONE
  acked order per owner field, keyed `triage:<run id>:<bare job>`, so a later round never sends it twice. A train
  stands: `tollman.py order <field> --post <train> --why ... --run <url>` (orders.py acks it; a failed order falls
  back to the same text sent to the field); none stands: the text sent to the field's foreman. Every order's text
  carries each red's evidence and its "reproduce first" command (the tollman never reproduces itself, D12)
- an owner without a live session, or none: one board note per red (board.py, `note`), nobody sent
- `unsure` (what is missing named) and `unplaced`: the red is a `record` and joins the run's ONE wake of the
  session, keyed `triage-wake:<run id>`; nothing is ordered for them (D11)

An action whose key is in `done` (the tollman's log) is left out. No order leaves without a key.
"""

import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path; board.py lives there)
import run_triage_dedup as dedup_
import run_triage_text as words
import stack_red
from tick import act

CLI = Path(__file__).with_name("tollman.py")
QUIET = ("needs-red", "runner", "flake")  # nobody is sent for these
WAKED = ("unsure", "unplaced")  # the one wake of the run


def record(v: dict, why: str) -> dict:
    return act("trains", "triage-record", "record", "-", key=f"{v['key']}:record",
               text=f"{words.head(v)}: {why}")


def flaky(top: str, v: dict, train: dict) -> dict:
    """L13: a budget flake the second time (red the same way in run `repeat_of`): the flaky brief to the farmer
    (flaky_brief.py, keyed `flaky:<test>` there: one brief per test), never an order."""
    e = v["evidence"]
    test = (e.get("tests") or [e["unit"]])[0]
    argv = [sys.executable, str(CLI.with_name("flaky_brief.py")), "place", "--repo", top, "--test", test, "--slot",
            train.get("carrier") or Path(top).name, "--why", f"{words.first(v)} (red the same way in run "
            f"{e.get('repeat_of')})"]
    return act("trains", "triage-flaky", "run", "-", key=f"{v['key']}:flaky", argv=argv,
               text=f"{words.head(v)}: missed its budget twice, the flaky brief to the farmer")


def note(top: str, v: dict, train: dict, url: str, who: str | None = None) -> dict:
    """The board note of a red nobody can be sent for: no owner, its owner has no live session, or (`who`) it waits
    behind its owner's open order of another red."""
    to = v.get("owner") or "-"
    argv = [sys.executable, str(farmer_frame.SCRIPTS / "board.py"), "post", "--kind", "note", "--from",
            Path(top).name, "--to", to, "--train", train["train"], "--repo", top, "--text", words.note(v, url, who)]
    who = who or ("owner " + to + " has no live session" if v.get("owner") else "no owner")
    return act("trains", "triage-note", "run", "-", key=f"{v['key']}:note", argv=argv,
               text=f"{words.head(v)}: board note, {who}")


def order(top: str, field: str, reds: list[dict], train: dict, url: str, key: str, standing: dict | None,
          pane: str | None) -> dict:
    """The acked order to `field` for its reds (see the module doc)."""
    send = act("trains", "triage-order", "send", field, pane=pane, key=key if not standing else f"{key}:send",
               text=words.order_text(reds, train, url))
    if not standing:
        return send
    argv = [sys.executable, str(CLI), "order", field, "--post", train["train"], "--why", words.why(reds), "--run", url,
            "--repo", top]
    return act("trains", "triage-order", "run", field, key=key, argv=argv, on_fail=[send],
               text=f"train {train['train']}: fix order to {field} for {words.names(reds)} of run {url.rsplit('/', 1)[-1]}"
                    f" (the fix rides train {standing['train']})")


def keys(groups: dict[str, list[dict]], rid: str) -> dict[str, str]:
    """{field: `triage:<run id>:<bare job of its first red>`}; a second order with a taken key adds `:<field>`."""
    out: dict[str, str] = {}
    for field, reds in groups.items():
        key = f"triage:{rid}:{stack_red.bare(reds[0]['evidence']['job'])}"
        out[field] = f"{key}:{field}" if key in out.values() else key
    return out


def actions(top: str, main: str, result: dict, train: dict, standing: dict | None = None, panes: dict | None = None,
            done=(), read=dedup_.touched) -> list[dict]:
    """The round's actions for `result` (run_triage.triage's) of `train`'s land run; `standing`: the train that
    stands now (else None: the orders are sent); `panes`: {field: pane}; `done`: the log's keys; `read(main, wagon,
    since)`: the files a wagon's commits touch."""
    run, panes = result["run"], panes or {}
    rid, url = str(run.get("id")), run.get("url") or ""
    dedup, out, groups, waked = result.get("dedup") or {}, [], {}, []
    for v in result["verdicts"]:
        kind = v["kind"]
        if kind in QUIET:
            out.append(record(v, f"{kind}: nobody ordered"))
            out += [flaky(top, v, train)] * bool(kind == "flake" and v["evidence"].get("budget")
                                                  and v["evidence"].get("repeat_of"))
        elif kind in WAKED or kind not in ("repeat", "file", "pipeline", "car"):
            waked.append(v)
            out.append(record(v, f"{kind}: nothing ordered ({v.get('missing') or 'the code cannot place it'}); "
                                 "the one wake of this run judges it"))
        elif why := dedup_.match(v, dedup, main, run.get("at"), read):
            out.append(record(v, f"{kind}: no order, {why}"))
            if why.startswith("fix order") and (o := dedup_.deferred(v, dedup)):  # waits behind another red's order
                out.append(note(top, v, train, url, f"deferred behind {o.get('field')}'s open fix order "
                                                    f"{o.get('id', '?')} (one per field)"))
        elif v.get("owner") and v.get("live"):
            groups.setdefault(v["owner"], []).append(v)
        else:
            out.append(note(top, v, train, url))
    for field, key in keys(groups, rid).items():
        out.append(order(top, field, groups[field], train, url, key, standing, panes.get(field)))
    if waked:
        out.append(act("trains", "triage-wake", "wake", key=f"triage-wake:{rid}", evidence={"run": url, "train": train,
                       "verdicts": waked}, text=words.wake_text(waked, train, url)))
    return [a for a in out if a["key"] not in set(done)]
