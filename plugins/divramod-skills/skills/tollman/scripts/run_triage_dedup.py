"""The dedup of a placed red before it is ordered (hal2 plan 0490 step 2; D5, D11): a red is matched, in this order,
to a hitched wagon whose commits after the red run touch the red's files (the fix is on its way: no order), to a fix
order that stands open for its owner (orders.py allows one per field: no second one) and to a field whose current
plan already names it. A match is a `record` line that names it, never an order. Pure over data; the one read, the
files a wagon's commits touched, is `touched` (git), injectable.

The data is `result["dedup"]` of run_triage.triage: `orders` (the standing train's open fix orders, `orders` and
`post` of train_state.standing), `wagons` ([{field, head}], `wagons(tickets)` of the queue's ready entries) and
`plans` ({field: its current plan}).
"""

import re

import run_triage
import triage

PATH = re.compile(r"[\w.@-]+(?:/[\w.@-]+)+\.\w+")
MIN_TOKEN = 4  # a plan's slug names a red by a job or spec word of at least this many letters


def wagons(tickets: list[dict]) -> list[dict]:
    """[{field, head, at}] of the queue's tickets that are marked ready (hitched), as the tollman reads them."""
    return [{"field": t["slot"], "head": t["ready"].get("head"), "at": t["ready"].get("at")}
            for t in tickets or [] if t.get("ready") and t.get("slot")]


def touched(main: str, wagon: dict, since: str | None = None) -> list[str]:
    """The files the wagon's commits touch that the barn does not have (those after `since`, an ISO time)."""
    after = [f"--after={since}"] if since else []
    code, text = triage.git(main, "log", "--format=", "--name-only", *after,
                            f"{triage.default_ref(main)}..{wagon.get('head')}")
    return sorted(set(text.split())) if code == 0 and text else []


def red_files(v: dict) -> tuple[set[str], tuple[str, ...]]:
    """(the files a verdict names, the path prefixes it names): its spec or file, the paths in its lines; a
    pipeline red names the workflow and gate folders."""
    e = v.get("evidence") or {}
    exact = {p for p in [e.get("file")] + [m for t in e.get("lines") or [] for m in PATH.findall(t)] if p}
    return exact, (run_triage.PIPELINE if v.get("cause") == "pipeline" else ())


def hits(files: list[str], exact: set[str], prefixes: tuple[str, ...]) -> list[str]:
    return sorted(f for f in files if f.startswith(prefixes) or any(f == p or f.endswith("/" + p) or p.endswith("/" + f)
                                                                   for p in exact))


def wagon_for(v: dict, wagons_: list[dict], since: str | None, main: str, read=touched) -> tuple[dict, list[str]] | None:
    """The first hitched wagon whose commits after the red run touch the red's files, with those files. A car of the
    red run is left out without a `since`: its commits were in the run."""
    exact, prefixes = red_files(v)
    if not exact and not prefixes:
        return None
    cars = set((v.get("evidence") or {}).get("cars") or [])
    for w in wagons_ or []:
        if not since and w.get("field") in cars:
            continue
        files = w.get("files") if w.get("files") is not None else read(main, w, since)
        if found := hits(files, exact, prefixes):
            return w, found
    return None


def order_for(v: dict, orders: list[dict]) -> dict | None:
    """The fix order that stands open for the verdict's owner."""
    return next((o for o in orders or [] if o.get("field") == v.get("owner")), None)


def ordered(v: dict, orders: list[dict]) -> dict | None:
    """The open order that already names this red: one of the same run whose `why` names its job (an early or a
    post-merge order, early_order.py, post_merge.py): one place per red, never a second order (D13)."""
    e = v.get("evidence") or {}
    return next((o for o in orders or [] if e.get("run") and o.get("run") == e["run"] and e.get("job")
                 and e["job"] in str(o.get("why") or "")), None)


def deferred(v: dict, dedup: dict) -> dict | None:
    """The owner's open order of ANOTHER red that this red waits behind (one order per field): told on the board."""
    o = order_for(v, (dedup or {}).get("orders") or [])
    return o if o and not ordered(v, [o]) else None


def words(v: dict) -> set[str]:
    """The words by which a plan's slug can name a red: its bare job and its spec's name."""
    e = v.get("evidence") or {}
    unit = (e.get("unit") or "").split("/")[0]
    spec = (e.get("spec") or "").rsplit("/", 1)[-1].split(".", 1)[0]
    return {w for w in (unit, spec) if len(w) >= MIN_TOKEN}


def plan_for(v: dict, plans: dict) -> tuple[str, str] | None:
    """(field, plan) of a running plan whose slug names the red's job or spec as whole words."""
    for field, plan in sorted((plans or {}).items()):
        slug = "-" + (plan or "").split("-", 1)[-1] + "-"
        if any(f"-{w}-" in slug for w in words(v)):
            return field, plan
    return None


def match(v: dict, dedup: dict, main: str, since: str | None, read=touched) -> str | None:
    """Why this red needs no order of its own (the words of a `record` line), or None."""
    if o := ordered(v, dedup.get("orders") or []):
        return f"fix order {o.get('id', '?')} for {o.get('field')} names it already (this run)"
    if w := wagon_for(v, dedup.get("wagons") or [], since, main, read):
        return f"hitched wagon {w[0]['field']} ({str(w[0].get('head'))[:12]}) touches {', '.join(w[1][:3])}"
    if o := order_for(v, dedup.get("orders") or []):
        return f"fix order {o.get('id', '?')} for {o['field']} stands open (one per field)"
    if p := plan_for(v, dedup.get("plans") or {}):
        return f"field {p[0]} runs plan {p[1]}, which names it"
    return None
