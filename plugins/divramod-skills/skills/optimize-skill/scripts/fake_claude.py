"""A fake `claude` for the tests: canned stream-json, 0 tokens. Never the real `claude`.

`install(folder, rules=None, default=None)` writes an executable `claude` into `folder`. Each call appends
{argv, prompt, env (only the names ANTHROPIC*, CLAUDE*, OPTIMIZE_*), cwd, skills: {name: SKILL.md text in the
cwd's `.claude/skills/`}} to `calls.jsonl` beside it, then prints the stream of the first rule that matches:

    {"prompt": "<substring of the -p prompt>", "skill": "<substring of any SKILL.md in the workspace>",
     "stream": [<events>] or "<raw text>", "exit": 0, "sleep": 0}

(a rule without `prompt` and `skill` always matches), else `default` (a success stream). With
`FAKE_CLAUDE_PROJECTS` and `CLAUDE_CONFIG_DIR` set it also makes `<config>/projects/<cwd slug>/memory/`, as claude
does. `stream_for(...)` builds a
canned stream: init, one assistant event per tool call and text, the tool results, the result event.
"""

import json
import stat
import sys
from pathlib import Path

USAGE = {"input_tokens": 8, "cache_creation_input_tokens": 10714, "cache_read_input_tokens": 73162,
         "output_tokens": 1082}

CLAUDE = '''\
import json, os, sys, time
from pathlib import Path
here = Path(__file__).resolve().parent
argv = sys.argv[1:]
prompt = argv[argv.index("-p") + 1] if "-p" in argv else ""
skills = {p.parent.name: p.read_text(encoding="utf-8") for p in Path.cwd().glob(".claude/skills/*/SKILL.md")}
env = {k: v for k, v in os.environ.items() if k.startswith(("ANTHROPIC", "CLAUDE", "OPTIMIZE_"))}
with open(here / "calls.jsonl", "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"argv": argv, "prompt": prompt, "env": env, "cwd": os.getcwd(), "skills": skills}) + "\\n")
if os.environ.get("FAKE_CLAUDE_PROJECTS") and os.environ.get("CLAUDE_CONFIG_DIR"):  # as claude: a per-cwd folder
    slug = "".join(c if c.isascii() and c.isalnum() else "-" for c in os.path.realpath(os.getcwd()))
    (Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / slug / "memory").mkdir(parents=True, exist_ok=True)
config = json.loads((here / "rules.json").read_text(encoding="utf-8"))
def matches(rule):
    if "prompt" in rule and rule["prompt"] not in prompt:
        return False
    return "skill" not in rule or any(rule["skill"] in text for text in skills.values())
rule = next((r for r in config["rules"] if matches(r)), config["default"])
time.sleep(float(rule.get("sleep") or 0))
out = rule["stream"]
sys.stdout.write(out if isinstance(out, str) else "".join(json.dumps(e) + "\\n" for e in out))
sys.stdout.flush()
sys.exit(int(rule.get("exit") or 0))
'''


def stream_for(text="done", tool_calls=(), usage=None, subtype="success", cost=0.0034, model="claude-haiku-5-5"):
    """A canned stream: `tool_calls` are (name, input) pairs, answered by an ok tool_result each."""
    usage = dict(USAGE if usage is None else usage)
    share = {key: value // (len(tool_calls) + 1) for key, value in usage.items()}  # per call, summing to <= usage
    share["output_tokens"] = 1  # the stream's first output count, as the real one shows
    events = [{"type": "system", "subtype": "init", "model": model, "skills": [], "tools": []}]
    for n, (name, tool_input) in enumerate(tool_calls):
        events.append({"type": "assistant", "message": {"id": f"msg_{n}", "content": [
            {"type": "tool_use", "id": f"toolu_{n}", "name": name, "input": tool_input}],
            "usage": share}})
        events.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"toolu_{n}", "content": f"ok {n}"}]}})
    events.append({"type": "assistant", "message": {"id": "msg_last", "content": [{"type": "text", "text": text}],
                                                    "usage": share}})
    error = subtype != "success"
    events.append({"type": "result", "subtype": subtype, "is_error": error, "result": "" if error else text,
                   "num_turns": len(tool_calls) + 1, "total_cost_usd": cost, "usage": usage,
                   "errors": [f"stopped: {subtype}"] if error else [],
                   "modelUsage": {model: {"inputTokens": usage["input_tokens"],
                                          "outputTokens": usage["output_tokens"],
                                          "cacheReadInputTokens": usage["cache_read_input_tokens"],
                                          "cacheCreationInputTokens": usage["cache_creation_input_tokens"],
                                          "costUSD": cost}}})
    return events


def _executable(path, body):
    path.write_text(f"#!{sys.executable}\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def set_rules(folder, rules=None, default=None):
    default = default or {"stream": stream_for(tool_calls=[("Skill", {"skill": "demo"})])}
    (Path(folder) / "rules.json").write_text(json.dumps({"rules": list(rules or []), "default": default}),
                                             encoding="utf-8")


def install(folder, rules=None, default=None):
    """Write the fake into `folder`; returns the path of its `claude`."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    set_rules(folder, rules, default)
    return str(_executable(folder / "claude", CLAUDE))


def calls(folder):
    path = Path(folder) / "calls.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
