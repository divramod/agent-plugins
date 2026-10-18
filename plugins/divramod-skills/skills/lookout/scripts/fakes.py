"""Test fakes for lookout's scripts: check scripts and a `claude` binary. Never the real `claude`.

`fake_claude(folder, result)` writes an executable `claude` that appends {argv, stdin, env, cwd} to `calls.jsonl`
beside it (of the env only the names ANTHROPIC*, CLAUDE*, KEEP_*, LOOKOUT_*) and prints `result` (a dict, as JSON; a str as it is). `fake_check(folder, body)` writes a Python check.
"""

import json
import os
import stat
import sys
import textwrap
from pathlib import Path

SUCCESS = {"type": "result", "subtype": "success", "is_error": False, "duration_ms": 2100, "num_turns": 2,
           "total_cost_usd": 0.0102, "result": "",
           "usage": {"input_tokens": 407, "cache_creation_input_tokens": 2094, "cache_read_input_tokens": 0,
                     "output_tokens": 96},
           "structured_output": {"verdict": "act", "title": "Acme: invitation", "notify": "Acme: invitation",
                                 "data": {"kind": "invitation"}}}

CLAUDE = '''\
import json, os, sys, time
from pathlib import Path
here = Path(__file__).resolve().parent
stdin = sys.stdin.read()
with open(here / "calls.jsonl", "a", encoding="utf-8") as fh:
    env = {k: v for k, v in os.environ.items() if k.startswith(("ANTHROPIC", "CLAUDE", "KEEP_", "LOOKOUT_"))}
    fh.write(json.dumps({"argv": sys.argv[1:], "stdin": stdin, "env": env, "cwd": os.getcwd()}) + "\\n")
if (here / "sleep").exists():
    time.sleep(float((here / "sleep").read_text()))
sys.stdout.write((here / "result.txt").read_text())
'''


def _executable(path, body):
    path.write_text(f"#!{sys.executable}\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def fake_claude(folder, result=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    set_result(folder, SUCCESS if result is None else result)
    return str(_executable(folder / "claude", CLAUDE))


def set_result(folder, result):
    text = result if isinstance(result, str) else json.dumps(result)
    (Path(folder) / "result.txt").write_text(text, encoding="utf-8")


def calls(folder):
    path = Path(folder) / "calls.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def fake_check(folder, name, body):
    """A Python check script; returns its `check` line (`{python} <path>`)."""
    path = Path(folder) / f"{name}.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return f"{{python}} {path}"


def base_env():
    """A small env for a child: PATH and HOME only (never the whole environment)."""
    return {k: os.environ[k] for k in ("PATH", "HOME", "SYSTEMROOT") if k in os.environ}
