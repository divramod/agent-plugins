"""The handoff tests' kit (no test here): what makes them fast without testing less.

`seed(dest, files)`: a git repository on `main` with `files` in one commit "init", built once per process for each set
of files and copied into `dest` (git's spawns were a third of the suite's time). A plain repository has no absolute
path in it, so the copy is a repository of its own; commit-handoff.sh commits from an index of its own.

`run(args, cwd, env)`: `subprocess.run(args, ...)` with text and captured output, except that a Python script of these
skills (`[python, <x>.py, ...]`) runs in the test's own process, with its argv, folder and environment and an empty
stdin (a spawned Python with its imports costs about 0.3 s). The first call of each script in a run still spawns it,
so every script is also run as a real program; the bash scripts (commit-handoff.sh, since.sh) always run for real,
and they call where.py as a real process.
"""

import atexit
import contextlib
import io
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from unittest import mock

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
_SEEDS: dict = {}
_SPAWNED: set = set()  # the scripts this run has started as a real process once


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV}, check=True, capture_output=True)


def _template(files: tuple) -> Path:
    if files not in _SEEDS:
        root = Path(tempfile.mkdtemp())
        atexit.register(shutil.rmtree, root, True)
        _git(root, "init", "-q", "-b", "main")
        for name, text in files:
            (root / name).write_text(text)
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "--allow-empty", "-m", "init")
        _SEEDS[files] = root
    return _SEEDS[files]


def seed(dest: Path, files: dict) -> None:
    """`dest` (made when missing) becomes a copy of the repository with `files` committed as "init" on `main`."""
    shutil.copytree(_template(tuple(sorted(files.items()))), dest, symlinks=True, dirs_exist_ok=True)


def _python_script(args: list) -> bool:
    return (len(args) >= 2 and Path(args[0]).name.startswith("python") and args[1].endswith(".py")
            and Path(args[1]).is_file())


def run(args, cwd, env=None, check: bool = False) -> subprocess.CompletedProcess:
    args = [str(a) for a in args]
    if not _python_script(args) or args[1] not in _SPAWNED:
        if _python_script(args):
            _SPAWNED.add(args[1])
        return subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, check=check)
    done = _in_process(args, cwd, dict(env if env is not None else os.environ))
    if check and done.returncode:
        raise subprocess.CalledProcessError(done.returncode, args, done.stdout, done.stderr)
    return done


def _in_process(args: list, cwd, env: dict) -> subprocess.CompletedProcess:
    script, out, err, code = args[1], io.StringIO(), io.StringIO(), 0
    saved = os.getcwd(), sys.argv, list(sys.path), sys.stdin
    with mock.patch.dict(os.environ, env, clear=True):
        os.chdir(cwd)
        sys.argv, sys.stdin = [script, *args[2:]], io.StringIO("")
        sys.path.insert(0, str(Path(script).parent))
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    runpy.run_path(script, run_name="__main__")
                except SystemExit as stop:
                    if stop.code is None or isinstance(stop.code, int):
                        code = stop.code or 0
                    else:
                        print(stop.code, file=sys.stderr)
                        code = 1
                except Exception:  # what a real process prints before it exits 1
                    traceback.print_exc()
                    code = 1
        finally:
            os.chdir(saved[0])
            sys.argv, sys.path[:], sys.stdin = saved[1], saved[2], saved[3]
    return subprocess.CompletedProcess(args, code, out.getvalue(), err.getvalue())
