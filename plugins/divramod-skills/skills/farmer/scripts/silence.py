#!/usr/bin/env python3
"""Silence for a role's rounds (hal2 plan 0349 step 10, decision D6): `silence` / `unsilence` on `farmer.py` and
`tollman.py`, kept in the marker file `silent` of the role's state folder (gitignored with the rest of it).

A silenced round prints nothing but table lines, `| <role> | <what> | joined <fields> |`: the farmer one per round,
the tollman one per train (`joined`: the fields that rode it). A dry run, `--json` and the foremen stay as
they are. A woken session of a silenced role keeps to the lines too and uses the fewest tool calls
(`silent_lines` is the tollman's own list, `round_lines` the default).
"""

import sys
from pathlib import Path

import due
import roles

FILE = "silent"
MAX_WHAT = 100


def marker(repo: str, wiring: roles.Wiring = roles.FARMER) -> Path:
    return roles.state_dir(repo, due.DATA, wiring.role) / FILE


def on(repo: str, wiring: roles.Wiring = roles.FARMER) -> bool:
    return marker(repo, wiring).exists()


def set_silent(repo: str, wiring: roles.Wiring, value: bool) -> None:
    f = marker(repo, wiring)
    if value:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("on\n")
    else:
        f.unlink(missing_ok=True)


def line(role: str, what: str, joined: list[str] | tuple[str, ...] = ()) -> str:
    """One table line: `| farmer | 3 due, 2 done | joined 07, 09 |` (`joined -` when no field joined)."""
    return f"| {role} | {what.replace(chr(10), ' ')[:MAX_WHAT]} | joined {', '.join(joined) or '-'} |"


def round_lines(r: dict, wiring: roles.Wiring) -> list[str]:
    """The default silent round: one line, the fields the round acted on as `joined`."""
    if r.get("problem"):
        return [line(wiring.role, "problem: " + r["problem"])]
    done = [a for a in r.get("done", []) if a["do"] != "ran"]
    joined = sorted({a["slot"] for a in done if a.get("slot") not in (None, "-") and a["duty"] != "frame"})
    woke = (r.get("woke") or {}).get("pending", 0)
    return [line(wiring.role, f"{len(r.get('due', []))} due, {len(done)} done, {woke} for judgment", joined)]


def run(args, wiring: roles.Wiring, silent: bool) -> int:
    """The verbs `silence` and `unsilence`."""
    set_silent(args.repo, wiring, silent)
    print(f"{wiring.role}: {'silent' if silent else 'not silent'}")
    return 0


if __name__ == "__main__":
    print(__doc__, file=sys.stderr)
