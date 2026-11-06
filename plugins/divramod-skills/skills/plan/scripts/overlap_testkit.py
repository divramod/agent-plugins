"""A fake `hal2-cli-plans` for the overlap tests of every start path (plan 0593 step 6): `overlap --goal ... --json`
prints a canned answer and records its argv in `calls.jsonl` beside it. `HIT` is a schema 1 answer with one plan and
one earlier research, in the shape of the CLI's contract fixture (test_overlap's `Contract`); `EMPTY` nothing over
the threshold. Their `text` holds markers no Python format makes (plan 0684 D8): a reader that prints them printed
the CLI's own text."""
import contextlib
import json
import os
import stat
import tempfile
from pathlib import Path
from unittest import mock

HIT = {"schema": 1, "repo": "hal2", "base": "origin/main",
       "query": {"plan": None, "title": "Milestone hitch again", "goal": "hitch at milestones", "files": ["a.rs"],
                 "units": []},
       "threshold": 3.0, "scanned": {"plans": 4, "research": 2},
       "plans": [{"slug": "0571-milestone-hitch", "number": 571, "title": "Milestone hitch", "repo": "hal2",
                  "origin": "field", "field": "12", "branch": "12", "paused": False, "state": "active", "next": "3",
                  "path": "plans/0571-milestone-hitch/plan.md", "score": 4.0,
                  "why": [{"kind": "title_word", "what": "hitch", "points": 2.0},
                          {"kind": "goal_word", "what": "milestone", "points": 1.5}]}],
       "research": [{"repo": "hal2", "slug": "0131-plan-consistency", "title": "Plan consistency",
                     "question": "How do plans stay consistent?", "answer": "by since", "status": "final",
                     "revisit": "2027-02-01", "superseded_by": [], "tags": [],
                     "path": "research/0131-plan-consistency/research.md", "stale": False, "score": 3.5,
                     "why": [{"kind": "goal_word", "what": "plans", "points": 1.0}]}],
       "text": {"lines": ["CLI-LINE-1", "CLI-LINE-2"], "context": "- CLI-CONTEXT", "report": "CLI-REPORT"}}
EMPTY = {"plans": [], "research": [],
         "text": {"lines": [], "context": "- CLI-CONTEXT-NONE", "report": "CLI-REPORT-NONE"}}
SCRIPT = '''#!/usr/bin/env python3
import json, os, sys
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "calls.jsonl"), "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:2] != ["overlap"]:
    sys.exit(2)
sys.stdout.write(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "answer.json")).read() + "\\n")
sys.exit(int(os.environ.get("FAKE_OVERLAP_EXIT", "0")))
'''


@contextlib.contextmanager
def fake_cli(answer: dict | str | None, code: int = 0):
    """PATH starts with a folder holding the fake (answer None: a CLI that exits 2, as an older one does; a str:
    printed as it is, e.g. garbage; `code`: its exit code) and the scan is on (`HAL2_OVERLAP` unset). Yields the
    folder; its `calls.jsonl` holds the calls."""
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        cli = folder / "hal2-cli-plans"
        if answer is None:
            cli.write_text("#!/bin/sh\nexit 2\n")
        else:
            cli.write_text(SCRIPT)
            (folder / "answer.json").write_text(answer if isinstance(answer, str) else json.dumps(answer))
        cli.chmod(cli.stat().st_mode | stat.S_IEXEC)
        env = {k: v for k, v in os.environ.items() if k != "HAL2_OVERLAP"}
        env["FAKE_OVERLAP_EXIT"] = str(code)
        env["PATH"] = f"{folder}{os.pathsep}{env.get('PATH', '')}"
        with mock.patch.dict(os.environ, env, clear=True):
            yield folder


def calls(folder: Path) -> list[list[str]]:
    path = folder / "calls.jsonl"
    return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []
