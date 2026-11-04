"""The interrupt's sources of load beyond freeze.py's builds, daemon and VMs (plan 0585), each undone by `done`.

A source is a function `(d, dry) -> {"source", "kinds", "note"}` on interrupt.py's Deps (d.sys runs commands and
sends signals, d.out prints, d.rec is the stop record): it does its actions (or prints them with dry=True, changing
nothing), records each done one with its undo through d.rec.add_actions in freeze.py's shape ({text, kind, do,
undo}) and never raises: a missing CLI, a failing or a timed-out call is one line of output (D6).

Workqueue holders (D2): `hal2-cli-workqueue freeze all` stops every agent session's work (the caller's spared), undo
`thaw all`; a manual freeze of every session that was there before is left as it is, without an undo. `thaw all`
ends every manual hold, so each earlier manual hold of one session gets a row recorded before the freeze, its undo
freezing that session again (done undoes newest first: holders go on, thaw all, then the refreezes). Then every
`freeze serve` holder (each polls, D2's spin) is SIGSTOPped, undo SIGCONT; the hold stays while its holder is
stopped. `serves` alone is the rescan's: holders of sessions start after the freeze.
"""
import json
import os
import re

import freeze
import wq_quiet

PROBE = 5  # `frozen --json` answers in milliseconds; a hung CLI must not hold the dry run (D12)
CALL = 60
REASON = "important interrupt"
SERVE = re.compile(r"(?:^|/)hal2-cli-workqueue\S*\s+freeze\s+serve\b")


def result(source: str, kinds: list, note: dict) -> dict:
    return {"source": source, "kinds": kinds, "note": note}


def why(code: int, err: str) -> str:
    return f"exit {code}{': ' + err.strip()[:200] if err.strip() else ''}"


def load(out: str) -> dict | None:
    try:
        data = json.loads(out)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def holds(d, cli: str) -> list | None:
    """The live holds of `frozen --json`, None when the probe failed or timed out."""
    code, out, err = d.sys.run([cli, "frozen", "--json"], timeout=PROBE)
    data = load(out) if code == 0 else None
    if data is None or not isinstance(data.get("holds"), list):
        d.out(f"workqueue holds not readable ({why(code, err) if code else 'no JSON'}): earlier freezes unknown")
        return None
    return [h for h in data["holds"] if isinstance(h, dict)]


def manual(hs: list, scope: str) -> list:
    return [h for h in hs if h.get("class") == "manual" and h.get("scope") == scope]


def refreeze_rows(d, cli: str, hs: list) -> list:
    """A row per earlier manual hold of one session: nothing done now, done freezes it again after its thaw all.
    A hold with a --max is only reported: it ends by itself, done's thaw all ends it early."""
    rows = []
    for h in manual(hs, "session"):
        name = h.get("session")
        if not name:
            continue
        if h.get("max_min") is not None:
            d.out(f"earlier freeze of {name} ends by itself at {h.get('ends_at')}: done's thaw all ends it early")
            continue
        undo = [cli, "freeze", str(name), "--reason", h.get("reason") or "", "--by", h.get("by") or "user"]
        rows.append({"text": f"keep the earlier workqueue freeze of {name}", "kind": "wq-refreeze",
                     "do": ["true"], "undo": undo})
    return rows


def freeze_all(d, cli: str, hs: list | None, dry: bool) -> tuple:
    """(kinds, note) of `freeze all`; its undo `thaw all` recorded only when this call made the hold."""
    do = [cli, "freeze", "all", "--json", "--reason", REASON]
    if hs is not None and manual(hs, "all"):
        d.out("workqueue freeze all already held: left as it is (done will not thaw it)")
        return [], {"freeze_all": "earlier"}
    if dry:
        d.out(f"would freeze every session's work: {' '.join(do)} (undo: {cli} thaw all)")
        for r in refreeze_rows(d, cli, hs or []):
            d.out(f"would {r['text']}: done runs {' '.join(r['undo'])} after thaw all")
        return ["wq-freeze"], {}
    code, out, err = d.sys.run(do, timeout=CALL)
    data = load(out) if code == 0 else None
    if data is None:
        d.out(f"workqueue freeze all failed ({why(code, err) if code else 'no JSON'}): the interrupt goes on "
              "without it")
        return [], {"freeze_all": "failed", "error": code}
    hold = data.get("hold") if isinstance(data.get("hold"), dict) else {}
    if data.get("state") == "already":
        d.out("workqueue freeze all already held: left as it is (done will not thaw it)")
        return [], {"freeze_all": "earlier", "hold": hold.get("id")}
    if hs is None:
        d.out("done's thaw all ends every manual freeze, also one made before this interrupt")
    refreeze = refreeze_rows(d, cli, hs or [])
    d.rec.add_actions(refreeze + [{"text": "freeze every session's work (workqueue)", "kind": "wq-freeze",
                                   "do": do, "undo": [cli, "thaw", "all"]}])
    d.out(f"froze every session's work: workqueue hold {hold.get('id')} ({hold.get('processes', 0)} processes; "
          f"done runs thaw all)")
    return ["wq-freeze"], {"freeze_all": "set", "hold": hold.get("id"), "refreeze": [r["undo"][2] for r in refreeze]}


def serve_rows(table: dict, keep_pids: set, uid: int | None = None) -> list:
    """The running `freeze serve` holders of the user, as freeze.py rows of kind holder."""
    uid = os.getuid() if uid is None else uid
    return [{"kind": "holder", "pid": p["pid"], "cpu": p["cpu"], "what": p["args"][:200]}
            for p in sorted(table.values(), key=lambda p: p["pid"])
            if SERVE.search(p["args"]) and p["uid"] == uid and p["pid"] not in keep_pids
            and p["stat"][:1] not in freeze.STAT_SKIP]


def holder_action(row: dict) -> tuple:
    return ("STOP", row["pid"]), ("CONT", row["pid"]), f"freeze workqueue holder {row['pid']} ({row['what'][:80]})"


def serves(d, dry: bool, uid: int | None = None) -> list:
    """SIGSTOP every `freeze serve` holder (undo SIGCONT); the kinds of what was (or would be) done."""
    table = freeze.proc_table(d.sys)
    rows = serve_rows(table, freeze.caller_tree(table, d.getpid()), uid)
    done = []
    for row in rows:
        do, undo, text = holder_action(row)
        ok = True if dry else d.sys.kill(row["pid"], do[0])
        d.out(f"{'would ' if dry else ''}{text}: {freeze.show(do)}{'' if ok else '  (failed)'}")
        if ok and not dry:
            done.append({"text": text, "kind": "holder", "do": list(do), "undo": list(undo)})
    if done:
        d.rec.add_actions(done)
    return ["holder"] * (len(rows) if dry else len(done))


def workqueue_holders(d, dry: bool) -> dict:
    """Source 1: freeze all (undo thaw all), then the holders SIGSTOPped (undo SIGCONT)."""
    cli = wq_quiet.find_cli()
    if cli is None:
        d.out(f"{wq_quiet.NAME} not found: no workqueue freeze all (the machine is quieted without it)")
        kinds, note = [], {"cli": None}
    else:
        kinds, note = freeze_all(d, cli, holds(d, cli), dry)
        note["cli"] = cli
    kinds = kinds + serves(d, dry)
    note["holders"] = kinds.count("holder")
    return result("workqueue holders", kinds, note)


SOURCES = (("workqueue holders", workqueue_holders),)
