"""The judge (plan 0311 design.md, Judge; D3, D9, D15): one tool-less headless `claude -p` run per new event.

    claude -p "<judge prompt>\\n\\nReply only with the JSON the schema asks for." --safe-mode --tools "" \\
      --model <model> --max-budget-usd <budget> --no-session-persistence --output-format json --json-schema <schema>

stdin is `{farm, watch, title, event}` cut to 32 kB; cwd the watch's state folder; the env without
`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDECODE` and every `CLAUDE_CODE_*` but `CLAUDE_CODE_OAUTH_TOKEN`
(the run pays with the login, D3); 120 s. Every run, and every skip for the daily cap, is one `kind: judge` line in
log.jsonl. The binary: the `claude` argument, else `$LOOKOUT_CLAUDE`, else `claude` on PATH. Stdlib only.
"""

import json
import os
import shutil
from pathlib import Path

import paths
import proc

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["act", "ignore"]},
        "title": {"type": "string"},
        "notify": {"type": "string", "maxLength": 200},
        "data": {"type": "object"},
    },
    "required": ["verdict", "title", "notify"],
}
SUFFIX = "\n\nReply only with the JSON the schema asks for."
DEFAULT_MODEL = "sonnet"
DEFAULT_BUDGET = "0.05"
MAX_BUDGET = 0.50
DEFAULT_DAILY = 1.00
STDIN_LIMIT = 32 * 1024
TIMEOUT = 120
MAX_ATTEMPTS = 3
NOTIFY_LIMIT = 200
SCRUBBED = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDECODE")
KEPT = ("CLAUDE_CODE_OAUTH_TOKEN",)
USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


def claude_binary(claude=None):
    return claude or os.environ.get("LOOKOUT_CLAUDE") or shutil.which("claude") or "claude"


def budget(record):
    """The record's `budget` as the flag's string: default 0.05, at most 0.50 (D9)."""
    try:
        value = float(str(record.get("budget", DEFAULT_BUDGET)))
    except ValueError:
        return DEFAULT_BUDGET
    if value <= 0:
        return DEFAULT_BUDGET
    text = f"{min(value, MAX_BUDGET):.2f}"
    return text if float(text) > 0 else f"{value:g}"  # 0.004 must not become "0.00"


def prompt_text(record):
    """The judge prompt: the record's text, or the file `@<path>` relative to its farm. Raises OSError."""
    judge = str(record.get("judge") or "")
    if judge.startswith("@"):
        path = Path(judge[1:]).expanduser()
        if not path.is_absolute():
            path = Path(record.get("farm") or ".") / path
        return path.read_text(encoding="utf-8")
    return judge


def command(claude, prompt, model, max_budget):
    return [claude, "-p", prompt.rstrip() + SUFFIX, "--safe-mode", "--tools", "", "--model", model,
            "--max-budget-usd", max_budget, "--no-session-persistence", "--output-format", "json",
            "--json-schema", json.dumps(JUDGE_SCHEMA, separators=(",", ":"))]


def scrub_env(env):
    """The env without the API keys (they win over the login) and the session-coupling variables."""
    return {k: v for k, v in env.items()
            if k not in SCRUBBED and (not k.startswith("CLAUDE_CODE_") or k in KEPT)}


def stdin_payload(farm, record, event):
    data = json.dumps({"farm": farm, "watch": record.get("id"), "title": record.get("title"), "event": event},
                      ensure_ascii=False).encode("utf-8")
    if len(data) <= STDIN_LIMIT:
        return data
    return data[:STDIN_LIMIT].decode("utf-8", errors="ignore").encode("utf-8")


def spent_today(now, log=None):
    """The judge runs' cost today (local date), summed from log.jsonl."""
    day = now.date().isoformat()
    return sum(float(line.get("cost_usd") or 0) for line in paths.read_log(log)
               if line.get("kind") == "judge" and str(line.get("at", "")).startswith(day))


def _one_line(text, limit):
    return " ".join(str(text).split())[:limit]


def parse_result(out):
    """The verdict from claude's JSON result: ({verdict, title, notify, data}, None) or (None, reason)."""
    try:
        result = json.loads(out)
    except ValueError:
        return None, "bad json"
    if not isinstance(result, dict):
        return None, "bad json"
    if result.get("is_error") or result.get("subtype") != "success":
        return None, str(result.get("subtype") or "error")
    answer = result.get("structured_output")
    if not isinstance(answer, dict):
        return None, "no structured_output"
    title = answer.get("title")
    if answer.get("verdict") not in ("act", "ignore") or not isinstance(title, str) or not title.strip():
        return None, "schema"
    data = answer.get("data") if isinstance(answer.get("data"), dict) else {}
    return {"verdict": answer["verdict"], "title": _one_line(title, NOTIFY_LIMIT),
            "notify": _one_line(answer.get("notify") or title, NOTIFY_LIMIT), "data": data}, None


def _log_line(farm, record, event, model, now, result=None, subtype=None, verdict=None):
    usage = (result or {}).get("usage") or {}
    line = {"kind": "judge", "at": now.isoformat(), "farm": farm, "watch": record.get("id"), "event": event.get("id"),
            "model": model, "cost_usd": float((result or {}).get("total_cost_usd") or 0),
            "ms": (result or {}).get("duration_ms"), "turns": (result or {}).get("num_turns"),
            "subtype": subtype or (result or {}).get("subtype"), "verdict": verdict}
    line.update({k: usage.get(k) for k in USAGE_KEYS})
    return line


def _raw_result(out):
    try:
        result = json.loads(out)
    except ValueError:
        return None
    return result if isinstance(result, dict) else None


def judge(record, farm, event, watch_dir, *, claude=None, env=None, now=None, settings=None, log=None):
    """Judge one event. Returns {ok: True, verdict, title, notify, data}, or {ok: False, reason, skipped}:
    `skipped` is True when the daily cap stopped the run (the find goes on unjudged at once, D9)."""
    now = now or paths.now()
    settings = paths.load_settings() if settings is None else settings
    model = str(record.get("model") or DEFAULT_MODEL)
    cap = float(settings.get("daily_budget_usd", DEFAULT_DAILY))
    if spent_today(now, log) >= cap:
        paths.append_log(_log_line(farm, record, event, model, now, subtype="daily_cap"), log)
        return {"ok": False, "reason": "daily cap", "skipped": True}
    try:
        prompt = prompt_text(record)
    except (OSError, ValueError) as exc:  # a missing, unreadable or non-UTF-8 prompt file
        paths.append_log(_log_line(farm, record, event, model, now, subtype="prompt_missing"), log)
        return {"ok": False, "reason": f"prompt: {exc}", "skipped": False}
    Path(watch_dir).mkdir(parents=True, exist_ok=True)
    run = proc.run(command(claude_binary(claude), prompt, model, budget(record)), cwd=str(watch_dir),
                   env=scrub_env(dict(os.environ) if env is None else env),
                   stdin=stdin_payload(farm, record, event), timeout=TIMEOUT)
    if run["error"] or run["timed_out"]:
        subtype = "timeout" if run["timed_out"] else "error"
        paths.append_log(_log_line(farm, record, event, model, now, subtype=subtype), log)
        return {"ok": False, "reason": run["error"] or "timeout", "skipped": False}
    answer, reason = parse_result(run["out"])
    raw = _raw_result(run["out"])
    paths.append_log(_log_line(farm, record, event, model, now, raw, subtype=None if raw else "bad_json",
                               verdict=answer and answer["verdict"]), log)
    if answer is None:
        return {"ok": False, "reason": reason, "skipped": False}
    return dict(answer, ok=True)


def unjudged(event):
    """The find of an event no judge ruled on: its own summary is the title (D15)."""
    summary = _one_line(event.get("summary", ""), NOTIFY_LIMIT)
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    return {"verdict": "act", "title": summary, "notify": summary, "data": data}
