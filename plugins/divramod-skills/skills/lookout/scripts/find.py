"""The find path (plan 0311 design.md, Find; D7, D12, D16): what the tick does per new event.

In this order, each step marked in the watch's state.json (a pending entry keeps the find and its step) so a retry
never doubles one:

1. record  - the find line into `state/<farm>/finds.jsonl` (written first, so a later failure keeps it);
2. apply   - the record's optional farm command, the find JSON on stdin; failing, retried 3 times, then an "apply
             failed" daybook item and on;
3. daybook - the item, ONLY through `daybook.py --farm <farm> jot` (D16), never a day file; a failing or missing
             daybook is logged, the notification says so, the record stays;
4. notify  - `notify.send`, once; a failing backend is logged, never retried, never loses 1-3.

`process` mutates the watch's `state` (the tick saves it) and returns {status: done|pending, find, last_result,
steps}; the tick writes the record's `state: found` and `last_result`. A daybook missing here is not an error.
No session is woken (D7). Stdlib only.
"""

import json
import os
import shlex
import sys
from pathlib import Path

import notify
import paths
import proc
import watchstate

STEPS = ("record", "apply", "daybook", "notify")
MAX_APPLY = 3
APPLY_TIMEOUT = 60
DAYBOOK_TIMEOUT = 30


def finds_path(farm):
    return paths.state_root() / "state" / farm / "finds.jsonl"


def read_finds(farm, since=None):
    """The farm's find lines (a broken line is skipped), optionally those at or after the ISO time `since`."""
    path = finds_path(farm)
    if not path.exists():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(raw)
        except ValueError:
            continue
        if isinstance(item, dict) and (not since or str(item.get("at", "")) >= since):
            out.append(item)
    return out


def find_line(record, event, verdict, judged, now):
    return {"at": now.isoformat(), "watch": record.get("id"), "event": event.get("id"), "judged": bool(judged),
            "verdict": verdict.get("verdict", "act"), "title": verdict.get("title") or event.get("summary", ""),
            "notify": verdict.get("notify") or event.get("summary", ""), "data": verdict.get("data") or {}}


def daybook_script(explicit=None):
    """The daybook CLI: `explicit`, `$LOOKOUT_DAYBOOK`, the daybook skill beside this one, else the installed one."""
    here = Path(__file__).resolve().parent
    for candidate in (explicit, os.environ.get("LOOKOUT_DAYBOOK"), here.parents[1] / "daybook" / "scripts" / "daybook.py",
                      Path.home() / ".claude" / "skills" / "daybook" / "scripts" / "daybook.py"):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def jot(farm, text, daybook=None, runner=proc.run):
    """One daybook item through `daybook.py --farm <farm> jot`. Returns (ok, error)."""
    script = daybook_script(daybook)
    if script is None:
        return False, "daybook.py not found"
    text = " ".join(text.split()).lstrip("-").strip()
    cwd = farm if os.path.isdir(farm) else None
    run = runner([sys.executable, str(script), "--farm", farm, "jot", text], cwd=cwd, env=dict(os.environ),
                 timeout=DAYBOOK_TIMEOUT)
    if run["error"] or run["timed_out"] or run["code"] != 0:
        return False, run["error"] or ("timeout" if run["timed_out"] else proc.tail(run["err"], 300).strip() or
                                       f"exit {run['code']}")
    return True, None


def _apply(record, farm, line, runner):
    argv = [sys.executable if part == "{python}" else part for part in shlex.split(str(record["apply"]))]
    env = dict(os.environ, LOOKOUT_FARM=farm, LOOKOUT_WATCH=str(record.get("id")))
    run = runner(argv, cwd=record.get("farm") or None, env=env, stdin=json.dumps(line).encode("utf-8"),
                 timeout=APPLY_TIMEOUT)
    if run["error"] or run["timed_out"] or run["code"] != 0:
        return False, run["error"] or ("timeout" if run["timed_out"] else proc.tail(run["err"], 300).strip() or
                                       f"exit {run['code']}")
    return True, None


def _keep(state, event, step, attempts, line):
    watchstate.set_pending(state, event, step, attempts)
    state["pending"][-1]["find"] = line


def _pending(state, event):
    return next((p for p in state["pending"] if p["event"]["id"] == event["id"] and p.get("find")), None)


def process(record, farm, event, verdict, state, *, judged=True, now=None, settings=None, daybook=None,
            notifier=notify.send, runner=proc.run, log=None):
    """Run the find path for one event; `verdict` is the judge's answer (or `judge.unjudged(event)`), ignored when
    the event is pending at a later step from an earlier call (the pending entry's find is used)."""
    now = now or paths.now()
    settings = paths.load_settings() if settings is None else settings
    watch = str(record.get("id"))
    waiting = _pending(state, event)
    line = waiting["find"] if waiting else find_line(record, event, verdict, judged, now)
    start = STEPS.index(waiting["step"]) if waiting and waiting["step"] in STEPS else 0
    attempts = waiting["attempts"] if waiting else 0
    root = str(record.get("farm") or farm)  # the checkout the daybook belongs to
    steps = {}

    def note(step, ok, error=None):
        steps[step] = {"ok": ok, "error": error}
        paths.append_log({"kind": "find", "at": now.isoformat(), "farm": farm, "watch": watch,
                          "event": event.get("id"), "step": step, "ok": ok, "error": error}, log)

    def result(status):
        return {"status": status, "find": line, "last_result": line["title"], "steps": steps}

    if start <= 0:
        try:
            path = finds_path(farm)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
            note("record", True)
        except OSError as exc:
            note("record", False, str(exc))
            _keep(state, event, "record", attempts + 1, line)
            return result("pending")
    if start <= 1 and record.get("apply"):
        ok, error = _apply(record, farm, line, runner)
        note("apply", ok, error)
        if not ok:
            tries = (attempts if start == 1 else 0) + 1
            if tries < MAX_APPLY:
                _keep(state, event, "apply", tries, line)
                return result("pending")
            jot(root, f"apply failed: {line['title']} [lookout:{watch}]", daybook, runner)
    daybook_error = None
    if start <= 2:
        ok, daybook_error = jot(root, f"{line['title']} [lookout:{watch}]", daybook, runner)
        note("daybook", ok, daybook_error)
    body = line["notify"] + (" (no daybook item: " + daybook_error + ")" if daybook_error else "")
    backends = notify.backends_for(record, settings)
    try:
        results = notifier(line["title"], body, farm, watch, backends)
    except Exception as exc:  # a notifier that raises is still only a log line
        results = [{"backend": "?", "ok": False, "error": str(exc)}]
    for item in results:
        note(f"notify:{item['backend']}", item["ok"], item["error"])
    watchstate.deliver(state, event["id"], now)
    return result("done")
