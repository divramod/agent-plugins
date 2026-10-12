#!/usr/bin/env python3
"""Does the session match the plan's `run` after a clear? `/handoff c`'s step 0, decided without judgment (plan 0016
step 5; plan 0015's D10: before a clear the session wins, after it the plan wins).

  drift.py [--root <checkout>] [--transcript <file>] [--session <id>]
                        step 0 of Continue: prints {action, command, run, live, drift, at, why}
  drift.py --clear [--root <checkout>]
                        the clear-and-continue command, `--effort` from `run` (plan 0016's D8): {action: clear, ...}

The plan is the current one (`plans/CURRENT_PLAN`, where.py); `run: <model> <effort> <window>` is its coordinator's,
the live values are session.py's (the plan skill's; --transcript and --session go to it). `action` is:

- `ok`: nothing to do. No plan, a legacy plan or a subservant's slot (where.py's form `legacy`), no `run`, no
  difference, or only the window differs (the window is no launch flag).
- `switch`: the model or the effort differs; `command` restarts the session at `run` with `/handoff c` as its first
  prompt. The switch is recorded under `$HANDOFF_ROOT/switches/<checkout>.json` (default `~/skills/handoff`) with the
  handoff's `at`, so the next call for the same handoff knows it ran.
- `sync`: it still differs after a switch for the same handoff (`at`): the session's values win, `command` writes them
  into `run` (`plan.py run --sync`); say so in the first report. Never a second switch.

Exit 0 printed, 2 git missing or wrong arguments.
"""

import argparse
import datetime as dt
import json
import os
import re
import shlex
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLAN_SCRIPTS = HERE.parents[1] / "plan" / "scripts"
sys.path.insert(0, str(PLAN_SCRIPTS))
sys.path.insert(0, str(HERE))

import context  # noqa: E402  (the plan skill's)
import envelope  # noqa: E402
import session  # noqa: E402
import where  # noqa: E402

LAUNCH_FIELDS = ("model", "effort")


def data_root() -> Path:
    """The skill's data root (the repo's skill data rule): $HANDOFF_ROOT, else ~/skills/handoff."""
    env = os.environ.get("HANDOFF_ROOT", "").strip()
    return Path(env).expanduser() if env else Path(os.environ.get("HOME", str(Path.home()))) / "skills" / "handoff"


def record_path(root: Path) -> Path:
    """One switch record per checkout, named after its path."""
    return data_root() / "switches" / (re.sub(r"[^A-Za-z0-9._-]+", "-", str(root)).strip("-") + ".json")


def run_words(run: str) -> list[str]:
    words = [w.strip("`") for w in (run or "").split()] + ["", "", ""]
    return ["" if w == "-" else w for w in words[:3]]


def plan_state(root: Path) -> tuple[dict, str, str]:
    """where.py's answer, the record plan's `run` ("" for none or a legacy plan) and its handoff's `at`."""
    found = where.locate(root)
    if found["form"] != "record":
        return found, "", ""
    run = envelope.get((root / found["plan"]).read_text(), "run") or ""
    handoff = root / found["file"]
    at = (envelope.get(handoff.read_text(), "at") or "") if handoff.is_file() else ""
    return found, str(run).strip(), str(at).strip()


def result(action: str, why: str, **fields) -> dict:
    return {"action": action, "command": fields.pop("command", None), "why": why, **fields}


def decide(root: Path, live: dict | None = None) -> dict:
    found, run, at = plan_state(root)
    if found["form"] != "record":
        why = "no plan" if not found["plan"] else "a legacy plan or a subservant's slot: no `run` to restore"
        return result("ok", why, plan=found["plan"], run=None)
    if not run:
        return result("ok", "the plan has no `run`: the session's values stand", plan=found["plan"], run=None)
    live = live if live is not None else session.live()
    drift = context.drift(live, run)
    base = {"plan": found["plan"], "run": run, "at": at, "drift": drift,
            "live": {k: live.get(k) for k in ("model", "effort", "window", "sources")}}
    launch = {k: v for k, v in drift.items() if k in LAUNCH_FIELDS}
    if not launch:
        why = "only the window differs (no launch flag)" if drift else "the session matches `run`"
        return result("ok", why, **base)
    record = record_path(root)
    try:
        previous = json.loads(record.read_text())
    except (OSError, json.JSONDecodeError):
        previous = {}
    if previous.get("at") == at:
        command = f"python3 {shlex.quote(str(PLAN_SCRIPTS / 'plan.py'))} run --sync"
        return result("sync", f"a switch for this handoff (at {at or 'none'}) already ran and {', '.join(launch)} "
                      "still differ: the session's values win", command=command, record=str(record), **base)
    model, effort, _ = run_words(run)
    flags = (["--model", model] if model else []) + (["--effort", effort] if effort else [])
    command = shlex.join(["hal2-cli-agents", "switch", *flags, "--prompt", "/handoff c", "--detach", "--json"])
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({"checkout": str(root), "at": at, "run": run, "drift": drift,
                                  "switched": dt.datetime.now().isoformat(timespec="seconds")}, indent=2) + "\n")
    return result("switch", f"{', '.join(launch)} differ from `run`: restart once at `run`", command=command,
                  record=str(record), **base)


def clear_command(root: Path) -> dict:
    found, run, _ = plan_state(root)
    effort = run_words(run)[1] if run else ""
    flags = ["--effort", effort] if effort else []
    return result("clear", f"--effort from `run` ({effort})" if effort else "no `run`: hal2's own effort",
                  command=shlex.join(["hal2-cli-agents", "clear-and-continue", *flags, "--detach", "--json"]),
                  plan=found["plan"], run=run or None)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, help="the checkout (default: the one of the current directory)")
    ap.add_argument("--clear", action="store_true", help="print the clear-and-continue command")
    ap.add_argument("--transcript", help="the session's transcript (session.py)")
    ap.add_argument("--session", help="the session id (session.py; default $CLAUDE_CODE_SESSION_ID)")
    args = ap.parse_args(argv)
    if not shutil.which("git"):
        print("drift.py: git is missing; run install-prerequisites.sh", file=sys.stderr)
        return 2
    root = (args.root or Path(where.git(None, "rev-parse", "--show-toplevel") or ".")).resolve()
    if args.clear:
        out = clear_command(root)
    else:
        live = session.live(args.transcript or "", args.session or "") if (args.transcript or args.session) else None
        out = decide(root, live)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
