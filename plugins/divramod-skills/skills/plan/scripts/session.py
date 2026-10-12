#!/usr/bin/env python3
"""The running Claude Code session's live model, effort and context window, each with where it came from.

  session.py [--transcript <file>] [--session <id>]

The session is $CLAUDE_CODE_SESSION_ID (or --session), its transcript ~/.claude/projects/*/<session>.jsonl (or
--transcript). Only the main chain counts: a subagent's entries (`isSidechain`) never do, so a subagent running this
script reads its parent session's values.

- model: the later of the transcript's last main-chain `requestedModel` (it carries `[1m]` when asked for) and its
  last `/model` switch ("Set model to `Opus 5.5 (1M context)`"), else the `--model` of the `claude` process running
  this script (its nearest `claude` ancestor, else $CLAUDE_PID), else $ANTHROPIC_MODEL, else ~/.claude/settings.json
  `model`.
- effort: the later of the transcript's last main-chain `effort` and its last `/effort` ("Set effort level to max"),
  else $CLAUDE_EFFORT (inside a subagent it is the subagent's own, which is why the transcript comes first), else the
  process's `--effort`, else settings.json `modelSettings.<model id>.effortLevel`, else its `effortLevel`.
- window: $CLAUDE_CONTEXT_WINDOW, else 200k under CLAUDE_CODE_DISABLE_1M_CONTEXT=1, else 1m for `[1m]` or
  "1M context" in the model, else 1m for a 5.x model (the aliases `opus`, `sonnet`, `haiku`, `fable`, the ids
  `claude-<family>-5-*`, the names "Opus 5.5"), else 200k; more tokens in use than that means the 1m window.

Prints JSON: {"model", "effort", "window" (`200k`, `1m`), "window_tokens", "used", "transcript",
"sources": {"model", "effort", "window"}}. A value nothing names is "" with the source "default". Exits 0 unless the
arguments are wrong. context.py and plan.py import it (`scan`, `values`, `live`).
"""
import argparse
import functools
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_WINDOW = 200_000
LARGE_WINDOW = 1_000_000
FAMILIES = ("opus", "sonnet", "haiku", "fable")
MODEL_SWITCH = re.compile(r"<local-command-stdout>Set model to (.+?)(?: and saved|</local-command-stdout>)")
EFFORT_SWITCH = re.compile(r"<local-command-stdout>Set effort level to ([a-z]+)")
FIVE_X = re.compile(r"^(?:(?:opus|sonnet|haiku|fable)|claude-(?:opus|sonnet|haiku|fable)-5(?:-.*)?|"
                    r"(?:opus|sonnet|haiku|fable) 5(?:\.\d+)?\b.*)$")
DISPLAY_NAME = re.compile(r"^(opus|sonnet|haiku|fable) (\d+)(?:\.(\d+))?")
DEFAULT = "default"


def find_transcript(session: str, projects: Path) -> Path | None:
    matches = sorted(projects.glob(f"*/{session}.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(block.get("text", "") for block in content if isinstance(block, dict))
    return ""


def scan(transcript: Path) -> dict:
    """One pass over the transcript's main chain: tokens in context after the last assistant call (`used`, None
    without one) and the last value of `requested_model`, `model_switch`, `effort` and `effort_switch`, each as
    (value, line number) or None."""
    found = {"used": None, "requested_model": None, "model_switch": None, "effort": None, "effort_switch": None}
    with transcript.open(encoding="utf-8", errors="replace") as lines:
        for number, line in enumerate(lines):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict) or entry.get("isSidechain"):
                continue
            if entry.get("type") == "user":
                content = text_of((entry.get("message") or {}).get("content"))
                switch = MODEL_SWITCH.search(content)
                if switch:
                    found["model_switch"] = (switch.group(1).strip("` "), number)
                switch = EFFORT_SWITCH.search(content)
                if switch:
                    found["effort_switch"] = (switch.group(1), number)
                continue
            if entry.get("type") != "assistant":
                continue
            if entry.get("requestedModel"):
                found["requested_model"] = (str(entry["requestedModel"]), number)
            if entry.get("effort"):
                found["effort"] = (str(entry["effort"]), number)
            usage = (entry.get("message") or {}).get("usage")
            if usage:
                found["used"] = sum(int(usage.get(key) or 0) for key in (
                    "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens"))
    return found


def later(first: tuple | None, second: tuple | None) -> tuple | None:
    """The (value, line) of the two that comes later in the transcript; None when both are None."""
    candidates = [c for c in (first, second) if c]
    return max(candidates, key=lambda c: c[1]) if candidates else None


def claude_args() -> list[str] | None:
    """The arguments of the `claude` process running this script: its nearest `claude` ancestor, else the process
    $CLAUDE_PID names; None without one (or without `ps`)."""
    if not shutil.which("ps"):
        return None
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,args="], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    table = {}
    for line in out.stdout.splitlines():
        fields = line.split(None, 2)
        if len(fields) == 3 and fields[0].isdigit() and fields[1].isdigit():
            table[int(fields[0])] = (int(fields[1]), fields[2].split())
    is_claude = lambda args: any(Path(arg).name == "claude" for arg in args[:2])
    pid, seen = os.getpid(), set()
    while pid in table and pid not in seen:
        seen.add(pid)
        ppid, args = table[pid]
        if is_claude(args):
            return args
        pid = ppid
    named = os.environ.get("CLAUDE_PID", "").strip()
    if named.isdigit() and int(named) in table and is_claude(table[int(named)][1]):
        return table[int(named)][1]
    return None


def flag(args: list[str] | None, name: str) -> str:
    """The value of `--<name> <v>` or `--<name>=<v>` in `args`, up to a `--` that ends the options; "" without."""
    for i, arg in enumerate(args or []):
        if arg == "--":
            break
        if arg == name and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith(name + "="):
            return arg.split("=", 1)[1]
    return ""


def read_settings(home: Path) -> tuple[dict, str]:
    path = home / ".claude" / "settings.json"
    try:
        settings = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}, str(path)
    return (settings if isinstance(settings, dict) else {}), str(path)


def model_id(model: str) -> str:
    """The model's id as settings.json's `modelSettings` keys it: `[1m]` and " (1M context)" off, a display name
    ("Opus 5.5") as `claude-opus-5-5`; an alias stays as it is."""
    model = re.sub(r"\[1m\]$", "", model.strip().lower())
    model = re.sub(r"\s*\(.*$", "", model).strip()
    name = DISPLAY_NAME.match(model)
    if name:
        return "-".join(["claude", name.group(1), name.group(2)] + ([name.group(3)] if name.group(3) else []))
    return model


def family(model: str) -> str:
    """`opus`, `sonnet`, `haiku` or `fable` for any form of the model's name, else its id."""
    found = re.search(r"\b(?:claude-)?(" + "|".join(FAMILIES) + r")\b", model.lower())
    return found.group(1) if found else model_id(model)


def settings_effort(settings: dict, model: str) -> str:
    per_model = settings.get("modelSettings")
    if isinstance(per_model, dict):
        key = model_id(model)
        keys = [key] if key in per_model else sorted(
            (k for k in per_model if key in FAMILIES and k.startswith(f"claude-{key}-")), reverse=True)
        for k in keys:
            level = per_model[k].get("effortLevel") if isinstance(per_model[k], dict) else None
            if level:
                return str(level)
    return str(settings.get("effortLevel") or "")


def window_of(model: str, used: int | None = None) -> tuple[int, str]:
    """The context window in tokens for `model` and why."""
    env = os.environ.get("CLAUDE_CONTEXT_WINDOW", "").strip()
    if env.isdigit():
        window, source = int(env), "$CLAUDE_CONTEXT_WINDOW"
    elif os.environ.get("CLAUDE_CODE_DISABLE_1M_CONTEXT", "").strip().lower() in ("1", "true", "yes"):
        window, source = DEFAULT_WINDOW, "$CLAUDE_CODE_DISABLE_1M_CONTEXT"
    else:
        name = model.strip().lower()
        if name.endswith("[1m]") or "1m context" in name:
            window, source = LARGE_WINDOW, "1M in the model's name"
        elif FIVE_X.match(re.sub(r"\[1m\]$", "", name)):
            window, source = LARGE_WINDOW, "a 5.x model (1M by default)"
        else:
            window, source = DEFAULT_WINDOW, DEFAULT
    if used is not None and used > window:
        window, source = max(window, LARGE_WINDOW), "more tokens in use than the window"
    return window, source


def label(tokens: int) -> str:
    """`1m`, `200k`; a window that is neither a whole million nor a whole thousand stays in tokens."""
    if tokens % 1_000_000 == 0:
        return f"{tokens // 1_000_000}m"
    if tokens % 1000 == 0:
        return f"{tokens // 1000}k"
    return str(tokens)


def values(found: dict | None, home: Path) -> dict:
    """The session's model, effort and window from a `scan` (None without a transcript), with their sources."""
    found = found or {}
    settings, settings_path = read_settings(home)
    process = functools.cache(lambda: claude_args())  # one `ps` at most, only when the transcript falls short
    sources = {}
    chosen = later(found.get("requested_model"), found.get("model_switch"))
    if chosen:
        model = chosen[0]
        sources["model"] = ("/model in the transcript" if chosen is found.get("model_switch")
                            else "requestedModel in the transcript")
    elif flag(process(), "--model"):
        model, sources["model"] = flag(process(), "--model"), "the session process's --model"
    elif os.environ.get("ANTHROPIC_MODEL", "").strip():
        model, sources["model"] = os.environ["ANTHROPIC_MODEL"].strip(), "$ANTHROPIC_MODEL"
    elif settings.get("model"):
        model, sources["model"] = str(settings["model"]), settings_path
    else:
        model, sources["model"] = "", DEFAULT

    chosen = later(found.get("effort"), found.get("effort_switch"))
    if chosen:
        effort = chosen[0]
        sources["effort"] = ("/effort in the transcript" if chosen is found.get("effort_switch")
                             else "effort in the transcript")
    elif os.environ.get("CLAUDE_EFFORT", "").strip():
        effort, sources["effort"] = os.environ["CLAUDE_EFFORT"].strip(), "$CLAUDE_EFFORT"
    elif flag(process(), "--effort"):
        effort, sources["effort"] = flag(process(), "--effort"), "the session process's --effort"
    elif settings_effort(settings, model):
        effort, sources["effort"] = settings_effort(settings, model), settings_path
    else:
        effort, sources["effort"] = "", DEFAULT

    window, sources["window"] = window_of(model, found.get("used"))
    return {"model": model, "effort": effort, "window": label(window), "window_tokens": window,
            "used": found.get("used"), "sources": sources}


def session_transcript(args: argparse.Namespace, home: Path) -> Path | None:
    if args.transcript:
        return Path(args.transcript)
    session = args.session or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    return find_transcript(session, home / ".claude" / "projects") if session else None


def live(transcript: str = "", session: str = "") -> dict:
    """The running session's values (`values`) with `transcript`: what this script prints; plan.py's `run`."""
    home = Path(os.environ.get("HOME", str(Path.home())))
    path = session_transcript(argparse.Namespace(transcript=transcript, session=session), home)
    try:
        found = scan(path) if path else None
    except OSError:
        found = None
    result = values(found, home)
    result["transcript"] = str(path) if found is not None else None
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--transcript", help="transcript file to read instead of finding it")
    parser.add_argument("--session", help="Claude Code session id (default: $CLAUDE_CODE_SESSION_ID)")
    args = parser.parse_args(argv)
    print(json.dumps(live(args.transcript or "", args.session or "")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
