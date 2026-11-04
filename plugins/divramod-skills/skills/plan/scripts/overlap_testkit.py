"""A fake `hal2-cli-plans` for the overlap tests of every start path (plan 0593 step 6): `overlap --goal ... --json`
prints a canned answer and records its argv in `calls.jsonl` beside it. `HIT` is a schema 1 answer with one plan and
one earlier research; `EMPTY` nothing over the threshold."""
import contextlib
import json
import os
import stat
import tempfile
from pathlib import Path
from unittest import mock

HIT = {"plans": [{"slug": "0571-milestone-hitch", "title": "Milestone hitch", "field": "12", "paused": False,
                  "state": "open", "next": "3", "path": "plans/0571-milestone-hitch/plan.md", "score": 0.8,
                  "why": ["same goal words: hitch, milestone"]}],
       "research": [{"slug": "0131-plan-consistency", "question": "How do plans stay consistent?", "answer": "by since",
                     "status": "final", "revisit": "2027-02-01", "superseded_by": None,
                     "path": "research/0131-plan-consistency/research.md", "stale": False, "score": 0.6,
                     "why": ["same topic"]}]}
EMPTY = {"plans": [], "research": []}
SCRIPT = '''#!/usr/bin/env python3
import json, os, sys
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "calls.jsonl"), "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:2] != ["overlap"]:
    sys.exit(2)
print(json.dumps(json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "answer.json")))))
'''


@contextlib.contextmanager
def fake_cli(answer: dict | None):
    """PATH starts with a folder holding the fake (answer None: a CLI that exits 2, as an older one does) and the
    scan is on (`HAL2_OVERLAP` unset). Yields the folder; its `calls.jsonl` holds the calls."""
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        cli = folder / "hal2-cli-plans"
        if answer is None:
            cli.write_text("#!/bin/sh\nexit 2\n")
        else:
            cli.write_text(SCRIPT)
            (folder / "answer.json").write_text(json.dumps(answer))
        cli.chmod(cli.stat().st_mode | stat.S_IEXEC)
        env = {k: v for k, v in os.environ.items() if k != "HAL2_OVERLAP"}
        env["PATH"] = f"{folder}{os.pathsep}{env.get('PATH', '')}"
        with mock.patch.dict(os.environ, env, clear=True):
            yield folder


def calls(folder: Path) -> list[list[str]]:
    path = folder / "calls.jsonl"
    return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []
