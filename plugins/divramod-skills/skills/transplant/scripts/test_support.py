"""Shared fixtures of the transplant skill's tests: fake hal2 CLIs on PATH, a fake login shell, a scratch repository."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "transplant.py"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
HELP = "usage: hal2-cli-git ...\n  worktree transplant <from> <to>\n"
OK = {"status": "ok", "transplant": None, "refused": None, "checks": [], "would": {"creates": False, "servants": []}}

# One script is both fake CLIs. State lives in files of $FAKE_DIR: cfg.json (help, the answer per transplant mode,
# the history), sessions.json (running agents; `stop` removes one), refuse-stop (its presence makes `stop` refuse).
FAKE = r'''#!/usr/bin/env python3
import json, os, sys
d, name, args = os.environ["FAKE_DIR"], os.path.basename(sys.argv[0]), sys.argv[1:]
with open(d + "/log", "a") as f:
    f.write(json.dumps([name] + args + ["TMUX=" + os.environ.get("TMUX", "")]) + "\n")
def load(n, default):
    try:
        return json.load(open(d + "/" + n))
    except OSError:
        return default
def out(obj, rc=0):
    print(json.dumps(obj))
    sys.exit(rc)
cfg = load("cfg.json", {})
if name == "hal2-cli-agents":
    if args[:1] == ["list"]:
        out(load("sessions.json", []))
    if args[:1] == ["stop"]:
        if os.path.exists(d + "/refuse-stop"):
            out({"refused": "the agent holds a draft in its box"}, 3)
        left = [s for s in load("sessions.json", []) if s["pane_id"] != args[1]]
        json.dump(left, open(d + "/sessions.json", "w"))
        out({"how": "terminal-kill"})
else:
    if args[:1] == ["--help"]:
        print(cfg.get("help", ""))
        sys.exit(0)
    if args[:2] == ["worktree", "queue"]:
        out({"queue": []})
    if args[:2] == ["worktree", "run"]:
        print("setup ...")
        out({"mode": "terminal", "pane": "t:new", "slot": args[2], "worktree": "/wt/" + args[2]})
    if args[:2] == ["worktree", "transplants"]:
        out({"transplants": cfg.get("transplants", [])})
    if args[:2] == ["worktree", "transplant"]:
        mode = next((m for m in ("dry-run", "prepare", "cancel") if "--" + m in args), "drive")
        rc, obj = cfg["transplant"][mode]
        out(obj, rc)
sys.exit(2)
'''
SHELL = '#!/bin/sh\n# a login shell without the login: runs the command it gets with -lc\nexec /bin/sh -c "$2"\n'


def sh(path, *args, check=True) -> str:
    r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, env={**os.environ, **GIT_ENV})
    if check and r.returncode:
        raise AssertionError(f"git {args}: {r.stderr}")
    return r.stdout.strip()


def commit(path: Path, name: str) -> str:
    (path / name).write_text(name)
    sh(path, "add", name)
    sh(path, "commit", "-q", "-m", name)
    return sh(path, "rev-parse", "HEAD")


class Scratch(unittest.TestCase):
    """A repository `app` with a bare origin and the fields 34 and 09 (09 only with with_target)."""
    with_target = True

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name).resolve()
        self.origin, self.app = self.t / "origin.git", self.t / "app"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.app)], check=True)
        sh(self.app, "remote", "add", "origin", str(self.origin))
        self.base = commit(self.app, "base")
        sh(self.app, "push", "-q", "-u", "origin", "main")
        sh(self.app, "remote", "set-head", "origin", "main")
        self.wt = self.t / "wt"
        self.wt.mkdir()
        self.f34 = self.field("34")
        self.f09 = self.field("09") if self.with_target else self.wt / "09"
        self.fake = self.t / "fake"
        self.fake.mkdir()
        self.bin = self.t / "bin"
        self.bin.mkdir()
        for name in ("hal2-cli-agents", "hal2-cli-git"):
            (self.bin / name).write_text(FAKE)
            (self.bin / name).chmod(0o755)
        (self.bin / "fakeshell").write_text(SHELL)
        (self.bin / "fakeshell").chmod(0o755)
        (self.bin / "git").symlink_to(shutil.which("git"))
        self.config(transplant={"dry-run": [0, OK]})

    def tearDown(self):
        self.tmp.cleanup()

    def field(self, name: str) -> Path:
        sh(self.app, "worktree", "add", "-q", "-b", name, str(self.wt / name), "main")
        return self.wt / name

    def config(self, **cfg):
        (self.fake / "cfg.json").write_text(json.dumps({"help": HELP, **cfg}))

    def sessions(self, *sessions):
        (self.fake / "sessions.json").write_text(json.dumps([
            {"pane_id": f"t:s{slot}", "slot": slot, "state": "idle", "project": str(self.app), **extra}
            for slot, extra in sessions]))

    def calls(self) -> list[list[str]]:
        log = self.fake / "log"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def run_script(self, *args, repo=None, path_dirs=None):
        env = {k: v for k, v in os.environ.items() if k not in ("TMUX_PANE", "HAL2_TERMINAL")}
        env.update(PATH=os.pathsep.join(path_dirs or [str(self.bin), os.environ["PATH"]]), FAKE_DIR=str(self.fake),
                   SHELL=str(self.bin / "fakeshell"), TMUX="/private/tmux", HOME=str(self.t), **GIT_ENV)
        r = subprocess.run([sys.executable, "-B", str(SCRIPT), *args, "--repo", str(repo or self.app)]
                           if args[0] != "advice" else [sys.executable, "-B", str(SCRIPT), *args],
                           capture_output=True, text=True, env=env)
        return r.returncode, (json.loads(r.stdout) if r.stdout.lstrip().startswith("{") else r.stdout), r.stderr
