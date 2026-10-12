#!/usr/bin/env python3
"""How full the agent's context window is, to decide whether a running plan stops for a handoff.

  context.py [--threshold <percent>] [--window <tokens>] [--session <id>] [--transcript <file>]

Claude Code: the session is $CLAUDE_CODE_SESSION_ID, its transcript ~/.claude/projects/*/<session>.jsonl.
Used tokens are the last main-conversation API call's input (uncached + cache read + cache write) plus its
output, which is what the next call starts from. The window comes from --window, else session.py, which reads the
session's live model, effort and window with their sources: $CLAUDE_CONTEXT_WINDOW, else `[1m]`/"1M context" in the
model or a 5.x model (1,000,000 unless CLAUDE_CODE_DISABLE_1M_CONTEXT=1), else 200,000; the model is the
transcript's last `requestedModel` or `/model` switch, else the `claude` process's `--model` (hal2 starts sessions
with `--model opus[1m]`), else $ANTHROPIC_MODEL, else ~/.claude/settings.json. When more tokens are in use than
the window, the window must be the 1M one.

`percent` is measured against the usable window, i.e. without Claude Code's auto-compact buffer (16.5% of the
window), exactly like the Claude Code statusline shows it; `raw_percent` is against the whole window.

The threshold is --threshold, else hal2's `[autoclear]` settings (`hal2-cli-agents settings --json`, agents.toml):
`step_percent` when it is set (`step_tokens`: the plan runs this check at a step boundary, where a clear is cheapest,
so it stops earlier there than the guard's ceiling does mid-step; hal2 research 0048), else `percent` (the ceiling,
the lower of `percent` and `tokens`), else 35. `autoclear` says whether the session can clear and continue on its own after a hand-off
(`hal2-cli-agents clear-and-continue --detach`): hal2's autoclear is enabled and the agent is Claude Code in a tmux
pane or a hal2 terminal host ($CLAUDE_CODE_SESSION_ID, and $TMUX_PANE or $HAL2_TERMINAL: clear-and-continue takes
the pane `%<n>` or `t:<id>` from them itself); `autoclear_reason` says why not. $HAL2_CLI_AGENTS names the program
(default `hal2-cli-agents` on the PATH).

Prints JSON: {"known", "used", "window", "percent", "raw_percent", "threshold", "stop", "source", "autoclear",
"autoclear_reason", "model_source", "model", "effort", "sources", "plan", "run", "drift"}. `model`, `effort` and
`sources` (where model, effort and window came from) are session.py's; `model_source` is `sources.model`. `plan` is
the current plan (plans/CURRENT_PLAN of the repository around the working directory), `run` its `run: <model>
<effort> <window>` (null without), `drift` the fields where the session differs from `run`, e.g. {"effort":
{"session": "medium", "plan": "max"}} (a model compares by family, `[1m]` aside; `{}` without a plan or `run`). `stop` is true when percent >= threshold. When nothing can be measured (another
agent, no transcript yet) `known` is false and `stop` is null: the agent judges for itself. Always exits 0 unless the arguments are wrong.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import session

DEFAULT_THRESHOLD = 35.0
# Share of the window Claude Code keeps free for auto-compaction; the statusline leaves it out.
AUTO_COMPACT_BUFFER = 0.165


def autoclear_settings() -> tuple[dict | None, str]:
    """hal2's `[autoclear]` settings and the program, or None and why not."""
    program = os.environ.get("HAL2_CLI_AGENTS") or shutil.which("hal2-cli-agents")
    if not program:
        return None, "hal2-cli-agents is not installed"
    try:
        out = subprocess.run([program, "settings", "--json"], capture_output=True, text=True, timeout=10)
        settings = json.loads(out.stdout).get("autoclear") if out.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, AttributeError):
        settings = None
    if not isinstance(settings, dict):
        return None, f"{program} settings --json has no autoclear settings (hal2 too old?)"
    return settings, ""


def autoclear(settings: dict | None, why: str) -> tuple[bool, str]:
    if settings is None:
        return False, why
    if not settings.get("enabled", True):
        return False, "autoclear is disabled in agents.toml"
    if not os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip():
        return False, "not Claude Code ($CLAUDE_CODE_SESSION_ID unset)"
    if not agent_pane():
        return False, "not in a tmux pane or hal2 terminal ($TMUX_PANE and $HAL2_TERMINAL unset)"
    return True, ""


def agent_pane() -> str:
    """The agent's address as hal2 names it: `$TMUX_PANE` (`%<n>`), else `t:$HAL2_TERMINAL`; "" outside both."""
    pane = os.environ.get("TMUX_PANE", "").strip()
    if pane:
        return pane
    terminal = os.environ.get("HAL2_TERMINAL", "").strip()
    return f"t:{terminal}" if terminal else ""


def plan_run(start: Path) -> tuple[str | None, str]:
    """The current plan's slug (plans/CURRENT_PLAN of the repository around `start`) and its `run` value
    (front matter `run`, a legacy plan's `Run:` line); (None, "") without a current plan."""
    import plan  # plan.py's own reading; imported here so context.py starts fast and stands alone in tests
    try:
        path = plan.current_path(plan.find_root(start))
        return plan.slug_of(path), plan.header_value(path.read_text(), "Run")
    except (plan.PlanError, OSError):
        return None, ""


def drift(live: dict, run: str) -> dict:
    """The fields where the session differs from `run: <model> <effort> <window>`: {field: {"session", "plan"}}.
    A model compares by family (`opus`, `claude-opus-5-5[1m]` and "Opus 5.5 (1M context)" are one); a field the
    plan or the session does not name is left out."""
    words = [w.strip("`") for w in run.split()] + ["", "", ""]
    model, effort, window = ("" if w == "-" else w for w in words[:3])
    out = {}
    if model and live["model"] and session.family(model) != session.family(live["model"]):
        out["model"] = {"session": live["model"], "plan": model}
    if effort and live["effort"] and effort.lower() != live["effort"].lower():
        out["effort"] = {"session": live["effort"], "plan": effort}
    if window and window.lower() != live["window"]:
        out["window"] = {"session": live["window"], "plan": window}
    return out


def measure(args: argparse.Namespace, home: Path) -> dict:
    settings, why = autoclear_settings()
    threshold = args.threshold
    if threshold is None:
        numbers = [(settings or {}).get(key) for key in ("step_percent", "percent")]
        numbers = [float(n) for n in numbers if isinstance(n, (int, float)) and not isinstance(n, bool)]
        threshold = numbers[0] if numbers else DEFAULT_THRESHOLD
    can_clear, clear_why = autoclear(settings, why)
    result = {"known": False, "used": None, "window": None, "percent": None, "raw_percent": None,
              "threshold": threshold, "stop": None, "source": None,
              "autoclear": can_clear, "autoclear_reason": clear_why, "model_source": None}
    found = None
    session_id = args.session or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    transcript = Path(args.transcript) if args.transcript else (
        session.find_transcript(session_id, home / ".claude" / "projects") if session_id else None)
    if transcript is None:
        result["source"] = (f"no transcript for session {session_id}" if session_id
                            else "no session id ($CLAUDE_CODE_SESSION_ID unset)")
    else:
        try:
            found = session.scan(transcript)
        except OSError as error:
            result["source"] = f"cannot read {transcript}: {error}"
    live = session.values(found, home)
    slug, run = plan_run(Path.cwd())
    result.update(model=live["model"], effort=live["effort"], model_source=live["sources"]["model"],
                  sources=live["sources"], plan=slug, run=run or None, drift=drift(live, run))
    if found is None:
        return result
    used = found["used"]
    if used is None:
        result["source"] = f"no usage recorded yet in {transcript}"
        return result
    window = args.window or live["window_tokens"]
    if args.window:
        result["sources"]["window"] = "--window"
    if used > window:
        window = max(window, session.LARGE_WINDOW)
    percent = round(min(100.0, 100 * used / (window * (1 - AUTO_COMPACT_BUFFER))), 1)
    result.update(known=True, used=used, window=window, percent=percent,
                  raw_percent=round(100 * used / window, 1),
                  stop=percent >= threshold, source=str(transcript))
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--threshold", type=float,
                        help="stop at this percent used (default: hal2's autoclear percent, else 35)")
    parser.add_argument("--window", type=int, help="context window size in tokens")
    parser.add_argument("--session", help="Claude Code session id (default: $CLAUDE_CODE_SESSION_ID)")
    parser.add_argument("--transcript", help="transcript file to read instead of finding it")
    args = parser.parse_args(argv)
    home = Path(os.environ.get("HOME", str(Path.home())))
    print(json.dumps(measure(args, home)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
