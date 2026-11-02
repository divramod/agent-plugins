#!/usr/bin/env python3
"""Reach the user when the farm is stuck (hal2 plan 0570 step 4, D5, D7, D13): the four stuck cases ring the user's
iPhone through `hal2-cli-ring` (Find My, the reason on its screen) AND always push the reason (notice.py, D15), whatever
the ring's exit; every other case only pushes.

  alarm.py <case> "<reason>" [--repo <dir>] [--slot <NN>] [--json]
      case: dialog (a dialog no rule may approve), runner-down (a runner down >30 min), main-red (main red >30 min),
      question-blocks (a question only the user can answer blocks a field); any other case only pushes.
      Exit 0 when the ring or the push reached the user, 1 when neither did, 2 on usage.

    alarm(case, reason, repo, slot="", runner=None, which=None, push=None) -> dict

The ring runs `hal2-cli-ring ring --from farmer-<project> --json -- <reason>` (the reason one argument after `--`, so
a leading `-` stays text), bounded at 60 s. The result's `ring` is `rung` (exit 0), `held` (3: one ring per 30 min,
shared by every farm), `login` (4: the user runs `hal2-cli-ring login`), `timeout` (no answer in 60 s), `missing` (no
CLI) or `failed` (1, any other code), None for a case that is not stuck; a stuck case ALWAYS pushes the reason too
(the ring's cause is added to the push text when the ring did not go out), `pushed` says whether that push went out;
`outcome` is the ring's state and the push's (`rung, pushed`, `held, pushed`, `failed, push-failed`), for a case that
is not stuck `pushed` or `push-failed`; `why` names the ring's cause. Every call writes one `alarm` line
into the farmer's journal (log.jsonl, mtm_scan.log): the case, the reason on one line cut to 500 characters, the
outcome; never a secret (the argv holds only the reason and the role's field). Tests inject `runner(argv, timeout) ->
(code | None, error text)`, `which` and `push`. Stdlib only. Never raises.
"""

import argparse
import json
import shutil
import subprocess
import sys

import mtm_scan
import notice
import roles

STUCK = ("dialog", "runner-down", "main-red", "question-blocks")
RING = "hal2-cli-ring"
TIMEOUT = 60
REASON_LIMIT = 500
EXIT_WHY = {3: "held back: one ring per 30 min (hal2-cli-ring log)",
            4: "login needed: the user runs `hal2-cli-ring login`",
            1: "the ring failed"}
STATE = {0: "rung", 3: "held", 4: "login"}  # None: `timeout` or `missing`; any other exit: `failed`


def run(argv: list[str], timeout: int = TIMEOUT) -> tuple[int | None, str]:
    """Run the ring to its end, at most `timeout` seconds: (exit code, error text); None on a timeout or start
    failure. The default runner."""
    try:
        done = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout} s"
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return done.returncode, done.stderr.decode("utf-8", errors="replace")[-300:]


def who(repo: str) -> str:
    """The ringing role's field, `farmer-<project>` (roles.slot_name), shown on the phone as the caller."""
    try:
        return roles.slot_name(repo)
    except Exception:  # an unreadable repository still rings, as plain `farmer`
        return roles.ROLE


def ring_argv(reason: str, frm: str, binary: str = RING) -> list[str]:
    """Flags first, then `--` and the reason as one argument (the order hal2_core::cli builds argv in)."""
    return [binary, "ring", "--from", frm, "--json", "--", reason]


def ring(reason: str, frm: str, runner=None, which=None) -> tuple[bool, int | None, str]:
    """(rung, exit code, why) of one ring; never raising."""
    binary = (which or shutil.which)(RING)
    if not binary:
        return False, None, f"{RING} is not installed"
    code, err = (runner or run)(ring_argv(reason, frm, binary), TIMEOUT)
    if code == 0:
        return True, 0, "rung"
    if code is None:
        return False, None, notice.one_line(f"{RING} did not run: {err}", 300)
    why = EXIT_WHY.get(code, f"{RING} exit {code}")
    tail = notice.one_line(err, 200)
    return False, code, why + (f" ({tail})" if tail and code not in (3, 4) else "")


def journal(repo: str, entry: dict) -> str | None:
    """One `alarm` line in the farmer's log; the error text instead of raising."""
    try:
        mtm_scan.log(repo, entry)
        return None
    except Exception as exc:
        return notice.one_line(f"{type(exc).__name__}: {exc}", 300)


def alarm(case: str, reason: str, repo: str, slot: str = "", runner=None, which=None, push=None) -> dict:
    """Ring for a stuck case and always push the reason too (D7, D15); only push for any other case."""
    case = notice.one_line(case, 40)
    text = notice.one_line(reason, REASON_LIMIT) or case
    frm = who(repo)
    stuck = case in STUCK
    state, code, why = None, None, "not a stuck case: a push only"
    if stuck:
        try:
            rang, code, why = ring(text, frm, runner, which)
        except Exception as exc:  # the push must still go out
            rang, code, why = False, None, notice.one_line(f"{type(exc).__name__}: {exc}", 300)
        state = STATE.get(code) or ("missing" if "not installed" in why else "timeout" if code is None and
                                    "timed out" in why else "failed")
    rang = state == "rung"
    body = f"{text} (no ring: {why})" if stuck and not rang else text
    sent = (push or notice.send)(f"{frm}: {case}", body)
    pushed = bool(sent and sent.get("ok"))
    outcome = ", ".join(x for x in (state, "pushed" if pushed else "push-failed") if x)
    result = {"case": case, "stuck": stuck, "ring": state, "rang": rang, "exit": code, "pushed": pushed,
              "outcome": outcome, "why": why, "push": sent, "from": frm, "reason": text}
    note = why if pushed else f"{why}; push failed: {(sent or {}).get('error')}"
    result["journal_error"] = journal(repo, {"kind": "alarm", "slot": slot, "what": f"{case}: {text}",
                                             "note": f"{outcome}: {note}"})
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="alarm.py",
                                description="Ring the user for a stuck case and push the reason, else only push.")
    p.add_argument("case", help=f"one of {', '.join(STUCK)} rings; any other only pushes")
    p.add_argument("reason", help="what is stuck and what the user must do, shown on the phone")
    p.add_argument("--repo", default=".")
    p.add_argument("--slot", default="", help="the field it concerns, for the journal")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    result = alarm(args.case, args.reason, args.repo, args.slot)
    if args.json:
        print(json.dumps(result))
    else:
        print(f"{result['outcome']}: {result['case']}: {result['why']}")
    return 0 if result["rang"] or result["pushed"] else 1


if __name__ == "__main__":
    sys.exit(main())
