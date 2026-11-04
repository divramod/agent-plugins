"""The continue tests' kit (no test here): one farm in a temp folder, its fields, and fake hal2 CLIs.

`Farm(base)`: a main checkout `app` on `main` and fields under `worktree/app/<name>` (git worktrees), built once per
test class. `fakes(dir)`: `hal2-cli-agents`, `hal2-cli-plans`, `hal2-cli-git` as small Python programs answering from
JSON files below `dir` (`role/<folder name>.json`, `since/<plan>.json`, `queue.json`, `paused.json`, `list.json`); a
missing file is an older CLI (exit 2). `env(dir)` points the scripts at them; `HAL2_CLI_*` set to a missing path
pins the fallbacks.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
RECORD_PLAN = """---
type: Plan
schema: 1
id: 1
title: "x"
status: open
landing: auto
---

# Plan 0001: x

## Steps

| # | Step | Done when | Model | Effort | Window | Size | Status |
|---|---|---|---|---|---|---|---|
| 1 | Write the parser | parser tests green | sonnet | medium | 1m | 100k | done |
| 2 | Send the report by mail | a mail goes out | sonnet | medium | 1m | 100k | next |
| 3 | Show the report in the view | the view test green | sonnet | medium | 1m | 100k | |
"""
LEDGER = """---
type: Decisions
schema: 1
plan: 1
title: Decisions of plan 0001
description: Every decision of plan 0001.
status: open
---

# Decisions of plan 0001

## D1 · 2026-11-01 · agent · in-force

**D:** The parser reads JSON.

## D2 · 2026-11-01 · agent · in-force

**D:** The report goes out by mail.
**Why:** the user reads mail.
"""
STEP = "# Step {n}: x\n\n## Task\n\nDo it.\n\n## Approach\n\nThe plain way.\n"

FAKE = r'''#!{python}
import json, sys
from pathlib import Path
d = Path({dir!r})
args = sys.argv[1:]
def answer(name):
    f = d / name
    if not f.is_file():
        print("unrecognized subcommand", file=sys.stderr); sys.exit(2)
    print(f.read_text()); sys.exit(0)
kind = {kind!r}
if kind == "agents" and args[:1] == ["role"]:
    answer("role/" + Path(args[args.index("--path") + 1]).name + ".json")
if kind == "plans" and args[:1] == ["since"]:
    answer("since/" + args[1] + ".json")
if kind == "git" and args[:2] == ["worktree", "queue"]:
    answer("queue.json")
if kind == "git" and args[:2] == ["worktree", "paused"]:
    answer("paused.json")
if kind == "git" and args[:2] == ["worktree", "list"]:
    answer("list.json")
sys.exit(2)
'''


def git(cwd, *args) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV}).stdout.strip()


class Farm:
    def __init__(self, base: Path):
        self.base = base.resolve()
        self.main = self.base / "app"
        self.main.mkdir(parents=True)
        git(self.main, "init", "-q", "-b", "main")
        (self.main / "plans" / "0001-x" / "steps").mkdir(parents=True)
        (self.main / "plans" / "0001-x" / "plan.md").write_text(RECORD_PLAN)
        (self.main / "plans" / "0001-x" / "decisions.md").write_text(LEDGER)
        (self.main / "plans" / "0001-x" / "handoff.md").write_text("# Handoff of plan 0001\n")
        for n in (2, 3):
            (self.main / "plans" / "0001-x" / "steps" / f"{n}.md").write_text(STEP.format(n=n))
        (self.main / ".gitignore").write_text("/HANDOFF.md\n/roles/*/handoff.md\n")
        git(self.main, "add", "-A")
        git(self.main, "commit", "-q", "-m", "init")

    def field(self, name: str, plan: str | None = None, lead: str | None = None) -> Path:
        path = self.base / "worktree" / "app" / name
        git(self.main, "worktree", "add", "-q", "-b", name, str(path))
        if plan:
            (path / "plans" / "CURRENT_PLAN").write_text(plan + "\n")
        if lead:
            (path / "plans" / "LEAD").write_text(lead + "\n")
        return path


def fakes(dir: Path) -> dict:
    """The fake CLIs below `dir`; the environment that points the scripts at them."""
    dir.mkdir(parents=True, exist_ok=True)
    env = {}
    for kind in ("agents", "plans", "git"):
        cli = dir / f"hal2-cli-{kind}"
        cli.write_text(FAKE.format(python=sys.executable, dir=str(dir), kind=kind))
        cli.chmod(0o755)
        env[f"HAL2_CLI_{kind.upper()}"] = str(cli)
    return env


def answer(dir: Path, name: str, doc: dict) -> None:
    path = dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))


def role_doc(path: Path, role: str | None, why: str = "fixture", lead: dict | None = None) -> dict:
    return {"schema": 1, "path": str(path), "checkout": str(path), "repo": "app", "field": path.name, "role": role,
            "why": why, "lead": lead, "plan": None}


def since_doc(plan: str, **found) -> dict:
    keys = ("decisions", "questions", "records", "farmer", "landed", "overlaps")
    doc = {"schema": 1, "repo": "app", "plan": plan, "field": "07", "base": "origin/main",
           "window": {"at": "2026-11-02T00:00:00Z", "day": "2026-11-02", "from": "plan_commit", "commit": "abc"},
           "open_steps": [{"number": "2", "step": "Send the report by mail", "done_when": "a mail goes out",
                           "status": "next"},
                          {"number": "3", "step": "Show the report in the view", "done_when": "the view test green",
                           "status": ""}]}
    doc.update({k: found.get(k, []) for k in keys})
    doc["empty"] = not any(doc[k] for k in keys)
    return doc
