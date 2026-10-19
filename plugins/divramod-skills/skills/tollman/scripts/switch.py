#!/usr/bin/env python3
"""The tollman asleep on its flag (hal2 plan 0375 D4, D19 on plan 0365 D3). The flag is hal2-roles' `sleep.json` in
`roles/tollman/` of the field `tollman-<repo>` (modes.flag reads it); only `hal2-cli-roles sleep tollman on|off`
writes it, and `tollman.py sleep|wake` are thin calls of that.

Asleep on the flag (`plan`, called by modes.sleep): one `asleep` line per round and no train formed or started again.
A train whose landing still runs (its process lives) is watched and settled when it lands, as ever (modes.KEEP); every
other standing train is dropped (`tollman.py drop`): its mark cleared, its worktree removed through the proof, its
cars keep their tickets, places and ready marks. Every hitched field, a car of a dropped train included, is told once
per sleep "land yourself now": `/merge-to-main`, which lands it alone on its own land run in its turn (its entry's
mode production) or smuggles it (smuggle).

  tollman.py sleep|wake [--by <who>] [--why <text>] [--repo <dir>]     the flag (hal2-cli-roles); --by user by default
  tollman.py drop --why <text> [--repo <dir>]                           the standing train dropped (the asleep round)
"""

import subprocess
import sys
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import engine
import kinds
import mtm_scan
import roles
from tick import act

CLI = Path(__file__).with_name("tollman.py")
VERBS = ("sleep", "wake", "drop")
ROLE = "tollman"
ROLES = "hal2-cli-roles"
YEAR = 365 * 24 * 3600  # a sleep's word is never repeated within it (its key names the flag's `at`)
HOW = {kinds.PRODUCTION: "/merge-to-main: it lands alone, on its own land run",
       kinds.SMUGGLE: "/merge-to-main: your entry's mode is smuggle, so it smuggles"}
TEXT = {"alone": "tollman (wagon train): the tollman is asleep since {at} (by {by}): no train carries your hitched crop "
                 "({head}), land yourself now: run {how}. Your field keeps its place in the merge queue and goes alone "
                 "in its turn (hal2 plan 0375 D4); this is the tollman's word, no need to ask the user."}


def hitched(t: dict, own: str, riding: set) -> bool:
    """A field to tell to land itself: hitched, waiting, no servant's (30-99), not the tollman's, no running car."""
    slot = str(t.get("slot") or "")
    return bool(t.get("ready")) and t.get("state", "waiting") == "waiting" and slot != own and slot not in riding \
        and not (slot.isdigit() and 30 <= int(slot) <= 99)


def alone(tickets: list[dict], flag: dict, mode: dict | None, own: str, panes: dict, riding: set,
          after: str | None) -> list[dict]:
    """One `send` per hitched field: land yourself now, by its entry's mode; once per field and sleep."""
    return [act("trains", "land-alone", "send", t["slot"], pane=panes.get(t["slot"]), window=YEAR,
                key=f"alone:{t['slot']}:{flag.get('at')}", **({"after": after} if after else {}),
                text=TEXT["alone"].format(at=flag.get("at"), by=flag.get("by"), head=t["ready"].get("head", "")[:12],
                                          how=HOW[kinds.of(t, mode)]))
            for t in sorted(tickets, key=lambda t: t.get("position", 0)) if hitched(t, own, riding)]


def drop(top: str, train: dict) -> dict:
    argv = [sys.executable, str(CLI), "drop", "--why", "the tollman is asleep", "--repo", top]
    key = f"drop:{train['train']}"
    stuck = act("trains", "train-stuck", "wake", key=f"stuck:{key}",
                text=f"dropping train {train['train']} failed, run `{' '.join(argv[1:])}`")
    return act("trains", "train-drop", "run", "-", key=key, argv=argv, on_fail=[stuck],
               text=f"train {train['train']} dropped: the tollman is asleep, its cars go alone")


def plan(top: str, line: dict, flag: dict, mode: dict | None, tickets: list[dict], train: dict | None, panes: dict,
         inner, keep, alive) -> list[dict]:
    """The asleep round on the flag: the line, a landing train's `keep` actions of `inner()` (the awake plan; its
    process `alive(pid)`, or landed) or the train dropped, then the hitched fields told to land alone."""
    out, after, riding = [line], None, set()
    if train:
        going = [a for a in inner() if a["kind"] in keep]
        running = train["state"] in ("landing", "paused") and alive(train.get("pid"))
        if running or any(a["kind"] == "landed" for a in going):
            out, riding = out + going, {c["field"] for c in train.get("cars", [])}
        else:
            out.append(d := drop(top, train))
            after = d["key"]
    return out + alone(tickets, flag, mode, Path(top).name, panes, riding, after)


def switch(main: str, verb: str, by: str, why: str | None) -> tuple[int, str]:
    """`tollman.py sleep|wake`: hal2-roles' flag through `hal2-cli-roles sleep tollman on|off` (plan 0365 D3)."""
    field = roles.slot_dir(main, ROLE)
    argv = [ROLES, "sleep", ROLE, "on" if verb == "sleep" else "off",
            "--repo", field.name.removeprefix(f"{ROLE}-"), "--worktrees", str(field.parent), "--by", by,
            *(["--why", why] if why and verb == "sleep" else []), "--json"]
    try:
        p = subprocess.run(argv, cwd=main, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)
    return p.returncode, (p.stdout + p.stderr).strip()


def add_parser(sub) -> None:
    for verb in ("sleep", "wake"):
        p = sub.add_parser(verb)
        p.add_argument("--by", default="user")
        p.add_argument("--why")
    sub.add_parser("drop").add_argument("--why", required=True)


def main(args) -> int:
    if args.cmd == "drop":  # the train's worktree goes with it (engine.clear, train_wt.drop)
        code, text = engine.clear(args.repo, args.why)
    else:
        code, text = switch(mtm_scan.main_checkout(args.repo), args.cmd, args.by, args.why)
        text = text if code else f"the tollman is {'asleep' if args.cmd == 'sleep' else 'awake'} now ({text.strip()})"
    print(text, file=sys.stderr if code else sys.stdout)
    return code
