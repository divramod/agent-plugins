"""The Mac's host-side delivery as a farmer finding (hal2 plan 0728 D20 (1)): deliver-pull-macos replaced the land run's
f2 job, so its red no longer shows as a red box in a run; the tick reads the unit's `status --json` and reports it.

Run by the `ci` duty (`duties.plan_ci`), read-only. It calls `code/python/scripts/deliver-pull-macos/main.py status
--json` of the main checkout (the yard, where main's code is) on macOS only, and reads the object by its `schema`
number (1; record cross-unit-formats-have-a-schema), never by a regex or by a copy of the unit's types. Findings:

  red        `result` is "red": one wake (the reason, the log) and one push-only `alarm.py deliver-red`, each keyed by
             the delivered sha, so a red sha reaches the user once (alarm.py's way: the farmer's log remembers the key;
             a later sha that is red pushes again)
  agent-down `agent.loaded` is false: a wake at most once a day, with the command that loads it again
  schema     a `schema` this reader does not know: one wake per schema number (the unit changed its shape)

Nothing here writes: no yard, no state file of its own. `runner(argv, cwd) -> (exit code, stdout)` and `system` are for
tests. Never raises: an unreadable or missing status is no finding (the unit may not exist in an old main).
"""

import json
import platform
import subprocess
import sys
from pathlib import Path

import bounded
from tick import act

SCHEMA = 1
UNIT = "code/python/scripts/deliver-pull-macos/main.py"
ALARM = Path(__file__).resolve().parent / "alarm.py"
CASE = "deliver-red"  # not one of alarm.STUCK: a push, no ring
DAY = 24 * 3600
LOAD = f"python3 {UNIT} install"


def call(argv: list[str], cwd: str) -> tuple[int, str]:
    try:
        p = bounded.run(argv, cwd=cwd, timeout=30, retry=False)
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return p.returncode, p.stdout


def read(main: str, runner=None, system: str | None = None):
    """The unit's status object, or None (not a Mac, no unit, a failed call, not a JSON object)."""
    if (system or platform.system()) != "Darwin" or not (Path(main) / UNIT).is_file():
        return None
    code, out = (runner or call)([sys.executable, str(Path(main) / UNIT), "status", "--json"], main)
    try:
        doc = json.loads(out) if code == 0 else None
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def text_of(value, limit: int = 300) -> str:
    return " ".join(str(value or "").split())[:limit]


def plan(ctx: dict, runner=None, system: str | None = None) -> list[dict]:
    """The delivery's acts for this round (see the module doc); [] when all is well or nothing can be read."""
    main = ctx.get("main") or ""
    doc = read(main, runner, system) if main else None
    if doc is None:
        return []
    if doc.get("schema") != SCHEMA:
        return [act("delivery", "schema", "wake", key=f"deliver-schema:{doc.get('schema')}",
                    text=f"deliver-pull-macos status has schema {doc.get('schema')!r}, the farmer reads {SCHEMA}: "
                         f"teach farmer/scripts/deliver_watch.py the new shape", evidence={"schema": doc.get("schema")})]
    out = []
    agent = doc.get("agent") if isinstance(doc.get("agent"), dict) else {}
    if doc.get("result") == "red":
        sha = text_of(doc.get("sha") or doc.get("started") or "unknown", 60)
        why = text_of(doc.get("reason")) or "a step failed"
        where = f", log {text_of(doc.get('log'))}" if doc.get("log") else ""
        line = f"the Mac's delivery of {sha[:10]} is red: {why}{where}"
        out.append(act("delivery", "red", "wake", key=f"deliver-red:{sha}", text=line,
                       evidence={k: doc.get(k) for k in ("sha", "run", "reason", "log", "steps")}))
        out.append(act("delivery", "alarm", "run", key=f"deliver-alarm:{sha}", text=f"alarm: {line}",
                       argv=[sys.executable, str(ALARM), CASE, line, "--repo", main]))
    if agent.get("loaded") is False:
        out.append(act("delivery", "agent-down", "wake", key="deliver-agent-down", window=DAY,
                       text=f"the delivery agent local.hal2.deliver-pull is not loaded, so main is not delivered to "
                            f"this Mac: run `{LOAD}` in the main checkout (the yard's /mfm does it too)"))
    return out
