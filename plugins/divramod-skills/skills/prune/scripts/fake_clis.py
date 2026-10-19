"""Fake hal2 CLIs and a scratch farm for prune's executor tests (hal2 plan 0377 step 5). No test here.

`Farm` is the farmer's scratch repository (a main checkout `hal2` with its origin, test_farmer.Repo) with numbered
fields added by `add`, and executables `hal2-cli-git`, `hal2-cli-agents` and `hal2-cli-plans` first on PATH. They read
`data.json` (agents, queue, plans, fields whose removal fails, a slow removal) and log every call to `calls.jsonl`;
`hal2-cli-git worktree remove` removes with real git on the scratch farm only. Prune's state folder, the farmer's and
cleanup's CLI switch point into the scratch folder: no test touches a real worktree of the machine.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import executor
import facts
from test_farmer import Repo, git

FAKE = r'''#!/usr/bin/env python3
import json, os, subprocess, sys, time
from pathlib import Path
state = Path(os.environ["PRUNE_FAKE_STATE"])
name, args = Path(sys.argv[0]).name, sys.argv[1:]
with open(state / "calls.jsonl", "a") as f:
    f.write(json.dumps([name, *args]) + "\n")
data = json.loads((state / "data.json").read_text()) if (state / "data.json").exists() else {}

def git(*a, cwd=None):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)

def worktrees():
    rows, cur = [], {}
    for line in git("worktree", "list", "--porcelain").stdout.splitlines() + [""]:
        if not line:
            if cur.get("path"):
                rows.append(cur)
            cur = {}
        elif line.startswith("worktree "):
            cur = {"path": line[9:]}
        elif line.startswith("branch "):
            cur["branch"] = line[7:].removeprefix("refs/heads/")
    return [{"name": "main" if i == 0 else Path(w["path"]).name, "path": w["path"], "main": i == 0,
             "branch": w.get("branch")} for i, w in enumerate(rows)]

if name == "hal2-cli-agents":
    print(json.dumps(data.get("agents", [])) if args[:1] == ["list"] else "{}")
elif name == "hal2-cli-plans":
    plan = args[1] if len(args) > 1 else ""
    if plan in data.get("plans", {}):
        print(json.dumps(data["plans"][plan]))
    else:
        sys.stderr.write(f"no plan matches {plan}\n")
        sys.exit(1)
elif args[:2] == ["worktree", "list"]:
    print(json.dumps({"worktrees": worktrees()}))
elif args[:2] == ["worktree", "queue"]:
    print(json.dumps(data.get("queue", {"queue": []})))
elif args[:2] == ["worktree", "remove"]:
    slot = args[2]
    path = next(w["path"] for w in worktrees() if w["name"] == slot)  # names-ok: the CLI's field name
    if slot in data.get("fail_remove", []):
        sys.exit("refused: the fake says no")
    if "--force" not in args and git("status", "--porcelain", cwd=path).stdout.strip():
        sys.exit(f"{slot} holds unsaved work")
    for f in sorted(git("ls-files", cwd=path).stdout.split()) if data.get("slow_remove") else []:
        (Path(path) / f).unlink(missing_ok=True)
        with open(state / "deleted", "a") as out:
            out.write(f + "\n")
        time.sleep(data["slow_remove"])
    git("worktree", "remove", "--force", path)
    git("branch", "-D", slot)  # names-ok: the branch is the field name
    if "--remote" in args and git("rev-parse", "--verify", "--quiet", f"origin/{slot}").returncode == 0 \
            and git("rev-list", "--count", f"origin/main..origin/{slot}").stdout.strip() == "0":
        git("push", "--quiet", "origin", "--delete", slot)
    print(f"removed {slot}")
else:
    sys.exit(f"fake {name}: unknown call {args}")
'''


def install(root: Path) -> dict:
    """The fakes in `root/bin`, their state in `root/fake`; the environment that puts them first."""
    bin_dir, state = root / "bin", root / "fake"
    bin_dir.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    for name in ("hal2-cli-git", "hal2-cli-agents", "hal2-cli-plans"):
        (bin_dir / name).write_text(FAKE.replace("#!/usr/bin/env python3", f"#!{sys.executable}", 1))
        (bin_dir / name).chmod(0o755)
    return {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}", "PRUNE_FAKE_STATE": str(state),
            "HAL_PRUNE_DIR": str(root / "prune"), "HAL_CLEANUP_CLI": "", "FARMER_DIR": str(root / "state")}


class Farm(Repo):
    """The scratch farm: ignored build folders on main, fields added by `add`, the fakes first on PATH, the disk
    `self.disk` (facts.disk) and the free bytes `self.free` (a list: each read takes the next, the last stays)."""

    def setUp(self):
        super().setUp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.main / ".gitignore").write_text("target/\ncode/rust/target/\n")
        for n in range(5):
            (self.main / f"file{n}.txt").write_text(f"{n}\n")
        git(self.main, "add", ".")
        git(self.main, "commit", "-qm", "files")
        git(self.main, "push", "-q", "origin", "main")
        self.base = self.tmp / ".hal/git/worktree/hal2"
        self.env = install(self.tmp)
        self.disk = {"free_gb": 400.0, "used_pct": 60.0, "total_gb": 1000.0}
        self.free = [10**12]
        for p in (mock.patch.dict(os.environ, self.env),
                  mock.patch.object(facts, "disk", side_effect=lambda main: dict(self.disk)),
                  mock.patch.object(executor, "free_bytes", side_effect=self.next_free)):
            p.start()
            self.addCleanup(p.stop)

    def next_free(self, main):
        return self.free.pop(0) if len(self.free) > 1 else self.free[0]

    def add(self, slot: str, base: str = "origin/main", push: bool = True) -> Path:
        path = self.base / slot
        git(self.main, "worktree", "add", "-q", "-b", slot, str(path), base)
        if push:
            git(path, "push", "-q", "-u", "origin", slot)
        return path

    def feed(self, **kw) -> None:
        f = Path(self.env["PRUNE_FAKE_STATE"]) / "data.json"
        old = json.loads(f.read_text()) if f.exists() else {}
        f.write_text(json.dumps({**old, **kw}))

    def calls(self, name: str = "hal2-cli-git", verb: str = "remove") -> list[list[str]]:
        f = Path(self.env["PRUNE_FAKE_STATE"]) / "calls.jsonl"
        rows = [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []
        return [r[1:] for r in rows if r[0] == name and verb in r]

    def prune(self, *fields: str, dry: bool = False) -> tuple[int, list[str]]:
        lines: list[str] = []
        code = executor.run(str(self.main), set(fields) or None, dry, executor.Out(lines.append))
        return code, lines

    def agent(self, slot: str, state: str = "idle", minutes_ago: float = 120, pane: str | None = None) -> dict:
        import time
        return {"pane_id": pane or f"%{slot}", "checkout": str(self.base / slot), "state": state,
                "since": time.time() * 1000 - minutes_ago * 60_000}

    def tree(self) -> list[str]:
        """Every path under the farm's fields and main (not .git), to prove a dry run changed nothing."""
        out = subprocess.run(["find", str(self.base), str(self.main), "-not", "-path", "*/.git/*"],
                             capture_output=True, text=True).stdout
        return sorted(out.splitlines())


def jobs(lines: list[str]) -> list[str]:
    return [x.removeprefix("::job::") for x in lines if x.startswith("::job::")]


def parse(lines: list[str]) -> dict:
    """The workflow commands as the engine reads them (D19): {job: [(step, status, [lines])]}; an AssertionError for a
    command line that is none of the three, a step ended twice or a step left open at its job's end."""
    out: dict = {}
    job, step = "setup", None
    for x in lines:
        if x.startswith("::job::"):
            assert step is None, f"step {step} left open before {x}"
            job = x[7:]
            out[job] = []
        elif x.startswith("::step::"):
            assert step is None, f"step {step} left open"
            step = [x[8:], None, []]
        elif x.startswith("::end-step::"):
            assert step is not None, "end-step without a step"
            assert x[12:] in ("success", "failure", "skipped"), x
            step[1] = x[12:]
            out[job].append(tuple(step))
            step = None
        else:
            assert not x.startswith("::"), f"not a workflow command: {x}"
            if step is not None:
                step[2].append(x)
    assert step is None, "a step left open at the end"
    return out
