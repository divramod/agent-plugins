#!/usr/bin/env python3
"""Every farmer instruction carries an id and asks for an ack (hal2 plan 0137, the user's point 5, 2026-10-05).

  acks.py instruct <slot> <text> [--decision <id>]... [--repo <dir>] [--json]
      stamp a message the farmer sends itself (SendMessage): prints it with its id, logs the `ask-ack`; with
      --decision (a prefix of a `decision` entry's id) also a `decision-link`, so a servant naming the user's
      decision by this id has it in a decision check (skills plan 0010)
  acks.py ack <id> started|done|refused [<why>...] [--repo <dir>]
      record a session's ack when its message arrives
  acks.py open [--repo <dir>] [--json]
      the instructions still waiting for an ack

The tick stamps every templated send (`stamp_send`) and plans the follow-up (`plan`): no ack within ACK_AFTER, the
instruction is sent once more; still none ACK_AFTER later, the farmer is woken (`no-ack`) with the screen; a
`refused` ack always wakes it. `started` stops the clock, `done` closes the instruction. State: the log's `ask-ack`,
`ack` and `ack-resend:<id>` entries.
"""

import argparse
import datetime as dt
import json
import os
import re
import sys

import decision_log
import deliver
import mtm_scan

ACK_AFTER = dt.timedelta(minutes=10)
STATUSES = ("started", "done", "refused")
REPLY = "Reply `ack {id}: started|done|refused <why>` by SendMessage to the farmer session."
FARMER = re.compile(r"^farmer(?: \[[^\]]+\])?(?=( \([^)]*\))?: )")
STAMPED = re.compile(r"^farmer \[([^\]]+)\]")


def next_id(log: list[dict], slot: str) -> str:
    """`<slot>-<n>`: n counts the slot's instructions so far."""
    return f"{slot}-{1 + sum(1 for e in log if e.get('kind') == 'ask-ack' and e.get('slot') == slot)}"


def stamp(text: str, ack_id: str) -> str:
    """The id on the first line (`farmer [<id>]: ...`, a role kept: `farmer [<id>] (lead): ...`), the reply asked
    for on the last."""
    body = FARMER.sub(f"farmer [{ack_id}]", text, count=1) if FARMER.match(text) else f"farmer [{ack_id}]: {text}"
    return f"{body}\n{REPLY.format(id=ack_id)}"


def stamped_id(text: str) -> str | None:
    m = STAMPED.match(text or "")
    return m.group(1) if m else None


def ask_entry(slot: str, ack_id: str, text: str, pane: str | None, by: str) -> dict:
    return {"kind": "ask-ack", "slot": slot, "what": text.splitlines()[0][:200], "note": "", "id": ack_id,
            "text": text, "pane": pane or "", "by": by}


def stamp_send(a: dict, main: str) -> None:
    """Give a planned send its id and log the `ask-ack` (tick.execute, before it types). Re-sends keep theirs."""
    if a.get("ack_id"):
        return
    ack_id = next_id(mtm_scan.entries(mtm_scan.state_dir(main) / "log.jsonl"), a["slot"])
    a.update(ack_id=ack_id, text=stamp(a["text"], ack_id))
    mtm_scan.log(main, ask_entry(a["slot"], ack_id, a["text"], a.get("pane"), "tick"))


def instructions(log: list[dict]) -> dict[str, dict]:
    """Every instruction by id with its acks and when it was re-sent."""
    out: dict[str, dict] = {}
    for e in log:
        kind, at = e.get("kind"), dt.datetime.fromisoformat(e["at"])
        if kind == "ask-ack" and e.get("id"):
            out.setdefault(e["id"], {"acks": [], "resent": None}).update(
                id=e["id"], slot=e.get("slot", ""), at=at, text=e.get("text") or e.get("what", ""),
                pane=e.get("pane") or "")
        elif kind == "ack" and e.get("id") in out:
            out[e["id"]]["acks"].append({"at": at, "status": e.get("what", ""), "why": e.get("note", "")})
        elif (e.get("key") or "").startswith("ack-resend:") and e["key"][11:] in out:
            out[e["key"][11:]]["resent"] = at
    return out


def plan(log: list[dict], now: dt.datetime, panes: dict, capture=None) -> list[dict]:
    """The round's ack follow-ups: re-send once, then wake; a refusal wakes at once."""
    from tick import act  # the tick imports this module
    capture = capture or (lambda pane: deliver.cli("capture", pane)[1][-3000:] if pane else "")
    out = []
    for i in instructions(log).values():
        if "slot" not in i:
            continue
        last = i["acks"][-1]["status"] if i["acks"] else None
        pane = panes.get(i["slot"]) or i["pane"]
        if last == "refused":
            out.append(act("ack", "refused", "wake", i["slot"], key=f"ack-refused:{i['id']}",
                           text=f"{i['id']} refused: {i['acks'][-1]['why']}", evidence={"instruction": i["text"]}))
        elif last is None and i["resent"] is None and now - i["at"] >= ACK_AFTER:
            out.append(act("ack", "resend", "send", i["slot"], pane=pane, key=f"ack-resend:{i['id']}",
                           ack_id=i["id"], text=i["text"]))
        elif last is None and i["resent"] and now - i["resent"] >= ACK_AFTER:
            out.append(act("ack", "no-ack", "wake", i["slot"], key=f"ack-wake:{i['id']}",
                           text=f"no ack for {i['id']} after a re-send",
                           evidence={"instruction": i["text"], "screen": capture(pane)}))
    return out


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    ins = sub.add_parser("instruct")
    ins.add_argument("slot")
    ins.add_argument("text")
    ins.add_argument("--decision", action="append", default=[])
    ack = sub.add_parser("ack")
    ack.add_argument("id")
    ack.add_argument("status", choices=STATUSES)
    ack.add_argument("why", nargs="*")
    op = sub.add_parser("open")
    for s in (ins, ack, op):
        s.add_argument("--repo", default=os.getcwd())
        s.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    main_dir = mtm_scan.main_checkout(args.repo)
    log = mtm_scan.entries(mtm_scan.state_dir(main_dir) / "log.jsonl")
    if args.cmd == "instruct":
        try:
            relays = [decision_log.find(log, d)["id"] for d in args.decision]
        except ValueError as e:
            print(f"acks.py instruct --decision {e}", file=sys.stderr)
            return 1
        ack_id = next_id(log, args.slot)
        text = stamp(args.text, ack_id)
        mtm_scan.log(main_dir, ask_entry(args.slot, ack_id, text, None, "farmer"))
        for d in relays:
            mtm_scan.log(main_dir, {"kind": "decision-link", "slot": args.slot, "what": f"{d} relayed as {ack_id}",
                                    "note": "", "decision": d, "ack": ack_id, "by": "farmer"})
        print(json.dumps({"id": ack_id, "text": text}) if args.json else text)
    elif args.cmd == "ack":
        known = instructions(log).get(args.id)
        mtm_scan.log(main_dir, {"kind": "ack", "slot": (known or {}).get("slot", ""), "what": args.status,
                                "note": " ".join(args.why), "id": args.id, "by": "farmer"})
        if not known:
            print(f"acks.py: no instruction {args.id} in the log (recorded anyway)", file=sys.stderr)
    else:
        rows = [{"id": i["id"], "slot": i["slot"], "at": i["at"].isoformat(), "acks": [a["status"] for a in i["acks"]],
                 "what": i["text"].splitlines()[0]} for i in instructions(log).values()
                if "slot" in i and not any(a["status"] in ("done", "refused") for a in i["acks"])]
        print(json.dumps(rows, indent=1) if args.json else "\n".join(
            f"{r['id']:8} {r['at'][11:16]} {','.join(r['acks']) or 'no ack'}: {r['what'][:100]}" for r in rows)
            or "nothing waits for an ack")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
