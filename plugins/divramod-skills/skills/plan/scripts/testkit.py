"""Shared fixtures of the plan skill's tests, so the suite stays fast: a script of this folder run in the test's own
process, and a git repository copied from one made once.

`run` replaces `subprocess.run([sys.executable, script, *args], capture_output=True, text=True, env=..., cwd=...)`:
it calls the script's `main(argv)` with that environment, working directory and argv, captures stdout and stderr and
returns the same CompletedProcess. No interpreter start and no import per call; everything the script reads at call
time (os.environ, the current directory, PATH for the CLIs it spawns) is what the child process would have seen.
test_trailers, test_qcheck, test_plan_number and test_session still start the scripts as real processes.

`init_repo` replaces `git init -q [-b <branch>] <path>`: it copies a `.git` made once per branch name into `path`
(without the sample hooks, which nothing runs). `fill_once` does the same for a fixture the scripts make: the first
test builds it, every later one gets a copy. Every template lives in this process's own temp directory."""
import atexit
import contextlib
import importlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
_TEMPLATES: dict[str | None, Path] = {}
_FILLED: dict[str, Path] = {}


def run(script: Path, args, env: dict | None = None, cwd: Path | str | None = None,
        check: bool = False) -> subprocess.CompletedProcess:
    script = Path(script).resolve()
    argv = [str(a) for a in args]
    command = [sys.executable, str(script), *argv]
    module = _load(script)
    if module is None:  # not a module of this folder: a real process
        return subprocess.run(command, capture_output=True, text=True, env=env, cwd=cwd, check=check)
    saved_env, saved_cwd, saved_argv, saved_vars = dict(os.environ), os.getcwd(), sys.argv, dict(vars(module))
    out, err = io.StringIO(), io.StringIO()
    try:
        if env is not None:
            os.environ.clear()
            os.environ.update(env)
        if cwd is not None:
            os.chdir(cwd)
        sys.argv = [str(script), *argv]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = _call(module, argv)
    finally:
        sys.argv = saved_argv
        os.chdir(saved_cwd)
        os.environ.clear()
        os.environ.update(saved_env)
        for name in [n for n in vars(module) if n not in saved_vars]:
            delattr(module, name)
        for name, value in saved_vars.items():  # a `global` the call rebound (plan.py's PLANS, GLOBAL)
            setattr(module, name, value)
    result = subprocess.CompletedProcess(command, code, out.getvalue(), err.getvalue())
    if check:
        result.check_returncode()
    return result


def _load(script: Path):
    if script.parent != HERE:
        return None
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    module = importlib.import_module(script.stem)
    file = getattr(module, "__file__", None)
    return module if file and Path(file).resolve() == script and hasattr(module, "main") else None


def _call(module, argv: list[str]) -> int:
    """The exit code `sys.exit(main(argv))` gives the process, a traceback on stderr as the interpreter prints it."""
    try:
        code = module.main(argv)
    except SystemExit as stop:
        code = stop.code
    except Exception:  # noqa: BLE001 - an uncaught error is the process's exit 1
        traceback.print_exc()
        return 1
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    print(code, file=sys.stderr)
    return 1


def _scratch() -> Path:
    tmp = tempfile.mkdtemp(prefix="plan-skill-tests-")
    atexit.register(shutil.rmtree, tmp, True)
    return Path(tmp)


def init_repo(path: Path | str, branch: str | None = "main") -> None:
    """`git init -q [-b <branch>] <path>`, copied from a template."""
    if branch not in _TEMPLATES:
        tmp = _scratch()
        subprocess.run(["git", "init", "-q", *(["-b", branch] if branch else []), str(tmp)], check=True)
        _TEMPLATES[branch] = tmp / ".git"
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    shutil.copytree(_TEMPLATES[branch], path / ".git", symlinks=True, ignore=shutil.ignore_patterns("*.sample"))


def fill_once(key: str, root: Path, build) -> None:
    """`build()` fills the repository `root`; it runs once per process and `key`, every later call copies what it
    made into `root`, which must be as the first one was (a fresh `init_repo`). Only what the files hold is copied:
    the scripts must not write `root`'s absolute path into a file a test reads (plan_number's reservations do, into
    an entry nothing reads)."""
    if key in _FILLED:
        shutil.copytree(_FILLED[key], root, symlinks=True, dirs_exist_ok=True)
        return
    build()
    keep = _scratch() / Path(root).name
    shutil.copytree(root, keep, symlinks=True)
    _FILLED[key] = keep
