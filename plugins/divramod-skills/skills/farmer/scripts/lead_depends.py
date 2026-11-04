#!/usr/bin/env python3
"""Plan dependencies in the farmer's `lead` round (hal2 plan 0595 step 11, brief 2026-11-03-plan-dependencies point 4).

  wait_of_need(need, ctx)   `waits for 0514 (open)` when a foreman's open dependency holds its next step: the foreman
                            round does not nudge it as idle (its plan waits, nobody forgot it); "" otherwise
  plan(item, ctx)           when a dependency reaches its `until`, one `send` to the dependent field, with an ack id
                            like every instruction (tick.execute -> acks.stamp_send):
                              "plan 0514 is pushed (ab12cd3): merge origin/38 and go on with step 22"
                              "plan 0514 is main (ab12cd3): restock (/mfm) and go on with step 22"
                            The hand relay "38 pushed, 57 merge now" is gone.
  lead_depends.py record ...  the run action after the send: remembers the edge in `depends-told.jsonl`

The graph is `depends_view.read(main)` (`hal2-cli-plans depends list --all --json`), read once per round and kept in
`ctx["depends"]`; nothing of it is computed here, a missing or older CLI = nothing told, nobody held back.

What was told is the keyed log `depends-told.jsonl` of the farmer's state folder (record role-folder-formats; manifest
and schemas/depends-told.schema.json): `{schema 1, at, key, plan, dependent, slot, state, until}`, the last line per key
is the state. An edge is told once, whatever its state later; a field without a live session is told when it has one.
Read-only apart from `record`; no model call.
"""

import argparse
import json
import os
import sys

import depends_view
import mtm_scan
import roles
import roletime
from tick import act, git

LEAD = "farmer (development foreman)"  # duties.LEAD (duties is heavy; test_lead_depends pins it)
FILE = "depends-told.jsonl"
SCHEMA = 1
WINDOW = 30 * 24 * 3600  # the send's key in the farmer's log holds this long
TEXT_PUSHED = (LEAD + ": plan {dep:04d} is {state}{commit}: merge origin/{field} and go on with {step}. Your plan {plan:04d} "
               "waited for it (hal2-cli-plans depends list); this is the farmer's word, no need to ask the user.")
TEXT_MAIN = (LEAD + ": plan {dep:04d} is main{commit}: restock (/mfm) and go on with {step}. Your plan {plan:04d} waited "
             "for it (hal2-cli-plans depends list); this is the farmer's word, no need to ask the user.")


def graph(ctx: dict) -> dict | None:
    """The round's one read of the farm's plan graph, kept in ctx (None: unknown, also kept: not read again)."""
    if "depends" not in ctx:
        ctx["depends"] = depends_view.read(ctx["main"])
    return ctx["depends"]


def wait_of_need(need: dict, ctx: dict) -> str:
    """`waits for 0514 (open)` for the session `need` (a lead_scan entry) when an unreached dependency holds its next
    step, else "". Remembered in `ctx["waits"]` (slot -> text) for the round's summary."""
    number = need.get("plan_number") or depends_view.number_of(need.get("plan"))
    if number is None:
        return ""
    wait = depends_view.wait_of(depends_view.node_of(graph(ctx), number), need.get("next_step"))
    if wait:
        ctx.setdefault("waits", {})[need.get("slot") or "-"] = wait
    return wait


def told(main: str) -> set[str]:
    """The keys in `depends-told.jsonl` (an unreadable line counts for nothing)."""
    f = mtm_scan.state_dir(main) / FILE
    keys = set()
    if f.exists():
        for line in f.read_text().splitlines():
            try:
                keys.add(json.loads(line)["key"])
            except (ValueError, KeyError, TypeError):
                continue
    return keys


def edge_key(dep: int, dependent: int, slot: str) -> str:
    return f"depends:{dep:04d}:{dependent:04d}:{slot}"


def first_step(link: dict) -> str:
    """`step 22` for refs `22-27`, `your plan` when the link holds the whole plan."""
    steps = link.get("steps") or []
    return f"step {str(steps[0]).partition('-')[0]}" if steps else "your plan"


def commit_of(main: str, link: dict) -> str:
    """The short head of the dependency's branch (pushed, hitched) or of the default branch (main); "" when unknown."""
    import lead_marker
    ref = lead_marker.default_ref(main) if link.get("state") == "main" or not link.get("field") \
        else f"origin/{link['field']}"
    return git(main, "rev-parse", "--short", ref)


def plan(item: dict, ctx: dict) -> list[dict]:
    """One `send` (and the run that remembers it) per edge whose dependency has reached its `until` and whose dependent
    field has a live session, not told before (see the module doc)."""
    nodes = graph(ctx)
    if not nodes:
        return []
    done, panes, out = told(ctx["main"]), ctx.get("panes", {}), []
    for node in sorted(nodes.values(), key=lambda n: n["plan"]):
        slot = node.get("field")
        if not slot or not panes.get(slot):
            continue
        for link in node.get("depends_on") or []:
            key = edge_key(link["plan"], node["plan"], slot)
            if not link.get("reached") or key in done:
                continue
            head = commit_of(ctx["main"], link)
            fields = {"dep": link["plan"], "plan": node["plan"], "state": link.get("state"), "field": link.get("field"),
                      "step": first_step(link), "commit": f" ({head})" if head else ""}
            text = (TEXT_MAIN if link.get("state") == "main" else TEXT_PUSHED).format(**fields)
            record = [sys.executable, os.path.abspath(__file__), "record", "--key", key, "--plan", str(link["plan"]),
                      "--dependent", str(node["plan"]), "--slot", slot, "--state", str(link.get("state")),
                      "--until", str(link.get("until")), "--repo", ctx["top"]]
            out.append(act("lead", "depends-reached", "send", slot, pane=panes[slot], text=text, key=key, window=WINDOW))
            out.append(act("lead", "depends-told", "run", slot, argv=record, text=f"{link['plan']:04d} told to {slot}",
                           after=key))
    return out


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--key", required=True)
    r.add_argument("--plan", type=int, required=True)
    r.add_argument("--dependent", type=int, required=True)
    r.add_argument("--slot", required=True)
    r.add_argument("--state", default="")
    r.add_argument("--until", default="")
    r.add_argument("--repo", default=os.getcwd())
    a = p.parse_args(argv)
    entry = {"schema": SCHEMA, "at": roletime.now(), "key": a.key, "plan": a.plan, "dependent": a.dependent,
             "slot": a.slot, "state": a.state, "until": a.until}
    with (roles.state_dir(a.repo, mtm_scan.DATA) / FILE).open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
