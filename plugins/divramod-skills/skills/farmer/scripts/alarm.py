#!/usr/bin/env python3
"""Reach the user when the farm is stuck (hal2 plan 0570 step 4, D5, D7, D13): the four stuck cases ring the user's
iPhone through `hal2-cli-ring` (Find My, the reason on its screen) AND always push the reason (notice.py, D15), whatever
the ring's exit; every other case only pushes.

  alarm.py <case> "<reason>" [--repo <dir>] [--slot <NN>] [--json]
      case: dialog (a dialog no rule may approve), runner-down (a runner down >30 min), main-red (main red >30 min),
      question-blocks (a question only the user can answer blocks a field); any other case only pushes.
      Exit 0 when the ring or the push reached the user, 1 when neither did, 2 on usage.

    alarm(case, reason, repo, slot="", runner=None, which=None, push=None) -> dict

The ring runs `hal2-cli-ring ring --from farmer-<project> --json --no-record -- <reason>` (the reason one argument
after `--`, so a leading `-` stays text; `--no-record`: the alarm writes the notification itself, see below), bounded
at 60 s. The result's `ring` is `rung` (exit 0), `silent` (exit 0, the ring switch is `silent`: the reason on the
phone without sound), `off` (exit 0, the switch is `off`: no Find My call, plan 0606 D7; the push still goes out),
`held` (3: one ring per 30 min,
shared by every farm), `login` (4: the user runs `hal2-cli-ring login`), `timeout` (no answer in 60 s), `missing` (no
CLI) or `failed` (1, any other code), None for a case that is not stuck; a stuck case ALWAYS pushes the reason too
(the ring's cause is added to the push text when the ring did not go out), `pushed` says whether that push went out;
`outcome` is the ring's state and the push's (`rung, pushed`, `off, pushed`, `held, pushed`, `failed,
push-failed`), for a case that
is not stuck `pushed` or `push-failed`; `why` names the ring's cause. Every call writes one `alarm` line
into the farmer's journal (log.jsonl, mtm_scan.log): the case, the reason on one line cut to 500 characters, the
outcome; never a secret (the argv holds only the reason and the role's field). After ring and push it records ONE
notification (plan 0606 D10): `hal2-cli-ring notifications add --from farmer-<project> --role farmer --farm
<project> --case <case> --channel ring:<outcome> --channel push:<sent|failed> -- <reason>`; a missing CLI or a failed
`add` is noted in the result (`record_error`) and never fails the alarm. Tests inject `runner(argv, timeout) ->
(code | None, error text[, stdout])`, `which`, `push` and `record(argv) -> error text | None`. Stdlib only. Never
raises.
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
MUTED = ("silent", "off")  # exit 0 with `outcome` silent or off in the ring's --json (plan 0606 D7)
# The ring state as the notifications store names the ring channel's outcome (hal2-cli-ring notifications add).
CHANNEL = {"rung": "rung", "silent": "silent", "off": "off", "held": "held", "login": "refused"}


def run(argv: list[str], timeout: int = TIMEOUT) -> tuple[int | None, str, str]:
    """Run the ring to its end, at most `timeout` seconds: (exit code, error text, stdout); None on a timeout or
    start failure. The default runner."""
    try:
        done = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout} s", ""
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"{type(exc).__name__}: {exc}", ""
    return (done.returncode, done.stderr.decode("utf-8", errors="replace")[-300:],
            done.stdout.decode("utf-8", errors="replace")[-2000:])


def who(repo: str) -> str:
    """The ringing role's field, `farmer-<project>` (roles.slot_name), shown on the phone as the caller."""
    try:
        return roles.slot_name(repo)
    except Exception:  # an unreadable repository still rings, as plain `farmer`
        return roles.ROLE


def ring_argv(reason: str, frm: str, binary: str = RING) -> list[str]:
    """Flags first, then `--` and the reason as one argument (the order hal2_core::cli builds argv in)."""
    return [binary, "ring", "--from", frm, "--json", "--no-record", "--", reason]


def muted(out: str) -> str | None:
    """`silent` or `off` when the ring's --json says its switch muted it (exit 0), else None (a rung ring)."""
    try:
        doc = json.loads(out)
    except (TypeError, ValueError):
        return None
    word = doc.get("outcome") if isinstance(doc, dict) else None
    return word if word in MUTED else None


def ring(reason: str, frm: str, runner=None, which=None) -> tuple[str | None, int | None, str]:
    """(state, exit code, why) of one ring; state is `rung`, `silent` or `off` for exit 0, else None; never raising."""
    binary = (which or shutil.which)(RING)
    if not binary:
        return None, None, f"{RING} is not installed"
    code, err, *rest = (runner or run)(ring_argv(reason, frm, binary), TIMEOUT)
    if code == 0:
        state = muted(rest[0] if rest else "") or "rung"
        return state, 0, {"rung": "rung", "silent": "silent: the ring switch is silent (no sound)",
                          "off": "the ring switch is off"}[state]
    if code is None:
        return None, None, notice.one_line(f"{RING} did not run: {err}", 300)
    why = EXIT_WHY.get(code, f"{RING} exit {code}")
    tail = notice.one_line(err, 200)
    return None, code, why + (f" ({tail})" if tail and code not in (3, 4) else "")


def record(argv: list[str], timeout: int = TIMEOUT) -> str | None:
    """Run `notifications add`; the error text, None when it worked. The default recorder (never raising)."""
    try:
        code, err, *_ = run(argv, timeout)
    except Exception as exc:  # also a test's guard against a real call
        return notice.one_line(f"{type(exc).__name__}: {exc}", 300)
    return None if code == 0 else notice.one_line(f"{RING} notifications add: exit {code}: {err}", 300)


def record_argv(binary: str, frm: str, project: str, case: str, channels: list[str], reason: str) -> list[str]:
    """`notifications add` for the alarm's one notification (plan 0606 D10): flags first, `--`, the reason."""
    argv = [binary, "notifications", "add", "--from", frm, "--role", roles.ROLE, "--farm", project, "--case", case]
    for channel in channels:
        argv += ["--channel", channel]
    return argv + ["--", reason]


def journal(repo: str, entry: dict) -> str | None:
    """One `alarm` line in the farmer's log; the error text instead of raising."""
    try:
        mtm_scan.log(repo, entry)
        return None
    except Exception as exc:
        return notice.one_line(f"{type(exc).__name__}: {exc}", 300)


def record_notification(frm: str, case: str, text: str, state: str | None, pushed: bool, which=None,
                        record_fn=None) -> str | None:
    """Record the alarm's ONE notification (ring channel when it was a stuck case, push channel always); the error
    text when it could not be recorded, None otherwise. Never raises, never fails the alarm."""
    try:
        binary = (which or shutil.which)(RING)
        if not binary:
            return f"{RING} is not installed: nothing recorded"
        channels = ([f"ring:{CHANNEL.get(state, 'failed')}"] if state else []) + \
                   [f"push:{'sent' if pushed else 'failed'}"]
        project = frm.split("-", 1)[1] if "-" in frm else frm
        return (record_fn or record)(record_argv(binary, frm, project, case, channels, text))
    except Exception as exc:
        return notice.one_line(f"{type(exc).__name__}: {exc}", 300)


def alarm(case: str, reason: str, repo: str, slot: str = "", runner=None, which=None, push=None,
          record_fn=None) -> dict:
    """Ring for a stuck case and always push the reason too (D7, D15); only push for any other case. One
    notification with both channels is recorded after both ran (plan 0606 D10)."""
    case = notice.one_line(case, 40)
    text = notice.one_line(reason, REASON_LIMIT) or case
    frm = who(repo)
    stuck = case in STUCK
    state, code, why = None, None, "not a stuck case: a push only"
    if stuck:
        try:
            state, code, why = ring(text, frm, runner, which)
        except Exception as exc:  # the push must still go out
            state, code, why = None, None, notice.one_line(f"{type(exc).__name__}: {exc}", 300)
        state = state or STATE.get(code) or ("missing" if "not installed" in why else "timeout" if code is None and
                                             "timed out" in why else "failed")
    rang = state in ("rung", "silent")  # silent reached the phone, without sound; off did not
    body = f"{text} (no ring: {why})" if stuck and state not in ("rung", "silent") else text
    sent = (push or notice.send)(f"{frm}: {case}", body)
    pushed = bool(sent and sent.get("ok"))
    outcome = ", ".join(x for x in (state, "pushed" if pushed else "push-failed") if x)
    result = {"case": case, "stuck": stuck, "ring": state, "rang": rang, "exit": code, "pushed": pushed,
              "outcome": outcome, "why": why, "push": sent, "from": frm, "reason": text}
    note = why if pushed else f"{why}; push failed: {(sent or {}).get('error')}"
    result["record_error"] = record_notification(frm, case, text, state if stuck else None, pushed, which, record_fn)
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
