"""A test's git tree grown once and copied for every later test, across processes (hal2 plan 0480 step 05.01, D6).

The agents-test job runs one process per test file, so a seed per process (the old `roles/farmer/scripts/git_seed.py`)
regrew the same tree in every file. This one keeps the seed on disk, keyed by content, shared by every process of
the run under a lock, and removes it when the last process that joined it exits. No test of the skills here but
`test_git_seed.py`.

  git_seed.grow(self.tmp, key, self.grow)    # the empty folder `tmp` now holds the tree `build()` grows there
  git_seed.guard(self)                       # a 60 s hang guard for this test
  p = git_seed.spawn(self, argv)             # a child in its own process group, killed when the test ends

The seed lives in `<tempdir>/hal2-git-seed-<uid>` (`HAL_GIT_SEED_ROOT` overrides it: the scratch root of a test),
never in a user's state. Locks are `flock`s: a process that dies, `kill -9` too, drops its hold at once; a root left
by a run in which every process died is reused (its seeds are keyed by content) and removed by the next last exit.
"""

import atexit
import fcntl
import hashlib
import inspect
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

TREE, PATHS = "tree", "paths.json"
_DIGESTS = {}  # (key, build's code) -> the seed's name, read once per process
_STATE = {}  # root, use (the shared lock held while this process uses the root)


def grow(tmp, key, build):
    """Make the empty folder `tmp` hold the tree `build()` grows there: grown for real the first time for this
    content of `key` and `build` (in any process of the run), then copied from that first tree, every absolute path
    to its folder (worktree links, the origin's url) rewritten to `tmp`."""
    tmp = Path(tmp)
    root = _join()
    fast_git(root)
    name = _digest(key, build)
    seed = root / name
    if not seed.exists():
        with _locked(root / f"{name}.lock", fcntl.LOCK_EX):
            if not seed.exists():
                build()
                part = root / f"{name}.part-{os.getpid()}"
                shutil.rmtree(part, True)
                shutil.copytree(tmp, part / TREE, symlinks=True)
                (part / PATHS).write_text(json.dumps([os.path.realpath(tmp), str(tmp)]))
                os.rename(part, seed)
                return
    first = json.loads((seed / PATHS).read_text())
    shutil.copytree(seed / TREE, tmp, symlinks=True, dirs_exist_ok=True)
    moves = zip(first, (os.path.realpath(tmp), str(tmp)))  # the real path first: /private/var holds /var
    _relocate(tmp, [(a.encode(), b.encode()) for a, b in moves])


def fast_git(root=None):
    """On macOS `/usr/bin/git` (and its `git-upload-pack`) is a stub that starts Xcode's git through xcrun, about
    three times the CPU of the real one on every call (4.5 ms against 15.6 ms, measured), and a child of the stub
    can sit frozen by a landing's workqueue hold: put a script that runs the real binary first on this process's
    PATH, seen by every child of a test. (A link would not do: git finds its helpers and templates beside the path
    it was started by.) Elsewhere, or with a git of another place first (Homebrew's), nothing changes."""
    real = _real_git()
    if real is None:
        return
    text = f'#!/bin/sh\nexec "{real}" "$@"\n'
    folder = (root or _join()) / f"bin-{hashlib.sha256(text.encode()).hexdigest()[:8]}"  # a changed script, a new folder
    script = folder / "git"
    if not script.exists():
        folder.mkdir(exist_ok=True)
        part = folder / f"git.part-{os.getpid()}"
        part.write_text(text)
        part.chmod(0o755)
        os.rename(part, script)
    paths = os.environ.get("PATH", "").split(os.pathsep)
    if paths[0] != str(folder):
        os.environ["PATH"] = os.pathsep.join([str(folder), *paths])


def _real_git():
    if sys.platform != "darwin" or shutil.which("git") != "/usr/bin/git":
        return None
    candidates = []
    try:
        candidates.append(os.path.join(os.readlink("/var/db/xcode_select_link"), "usr/bin/git"))
    except OSError:
        pass
    candidates.append("/Library/Developer/CommandLineTools/usr/bin/git")
    return next((c for c in candidates if os.access(c, os.X_OK)), None)


def guard(test, seconds=60):
    """A hang guard: the test fails with TimeoutError after `seconds` of wall time (SIGALRM; main thread, POSIX
    only, else nothing). Call it in setUp; the timer and the old handler are put back when the test ends."""
    if not hasattr(signal, "setitimer") or threading.current_thread() is not threading.main_thread():
        return

    def hang(_signo, _frame):
        raise TimeoutError(f"{test.id()} hung for over {seconds} s")

    old = signal.signal(signal.SIGALRM, hang)
    signal.setitimer(signal.ITIMER_REAL, seconds)

    def back():
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)

    test.addCleanup(back)


def spawn(test, argv, **kwargs):
    """`subprocess.Popen` in a process group of its own, which the test's cleanup kills with all its children (only
    this group, by its id, never by a name) and waits for."""
    kwargs.setdefault("start_new_session", True)
    proc = subprocess.Popen(argv, **kwargs)
    test.addCleanup(reap, proc)
    return proc


def reap(proc):
    """Kill the process group of a child `spawn`ed with `start_new_session` and wait for the child."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    for stream in (proc.stdin, proc.stdout, proc.stderr):
        if stream is not None:
            stream.close()


def root_dir():
    """The folder the seeds live in (not created)."""
    explicit = os.environ.get("HAL_GIT_SEED_ROOT")
    if explicit:
        return Path(explicit)
    return Path(tempfile.gettempdir()) / f"hal2-git-seed-{os.getuid()}"


def _digest(key, build):
    """The seed's name: the key, the source files that grow it (the key's classes, `build`'s file, this file) and
    the git binary, so a changed fixture or git never reuses an old tree."""
    sources = {__file__}
    parts = [_norm(key, sources)]
    code = getattr(build, "__code__", None)
    memo = (parts[0], code and code.co_filename, code)
    if memo in _DIGESTS:
        return _DIGESTS[memo]
    if code is not None:
        sources.add(code.co_filename)
    for path in sorted(sources):
        try:
            parts.append(Path(path).read_text())
        except OSError:
            parts.append(path)
    git = shutil.which("git")
    if git:
        info = os.stat(git)
        parts.append(f"{os.path.realpath(git)} {info.st_size} {info.st_mtime_ns}")
    _DIGESTS[memo] = hashlib.sha256("\0".join(parts).encode()).hexdigest()[:24]
    return _DIGESTS[memo]


def _norm(key, sources):
    if inspect.isclass(key):
        try:
            sources.add(inspect.getsourcefile(key) or "")
        except TypeError:
            pass
        return f"{key.__module__}.{key.__qualname__}"
    if isinstance(key, (tuple, list)):
        return "(" + ",".join(_norm(k, sources) for k in key) + ")"
    return repr(key)


def _join():
    """The root, with this process holding a shared lock on it until it exits (the last one out removes it)."""
    if "root" in _STATE:
        return _STATE["root"]
    root = root_dir()
    while True:
        try:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            with _locked(root / "mutex", fcntl.LOCK_EX):
                use = os.open(root / "use", os.O_RDWR | os.O_CREAT, 0o600)
                fcntl.flock(use, fcntl.LOCK_SH)
            break
        except FileNotFoundError:  # the last process out removed the root between our steps: again
            continue
    _STATE.update(root=root, use=use)
    atexit.register(_leave)
    return root


def _leave():
    """Drop this process's hold; remove the root when nobody else holds it. The root is renamed away under the
    mutex before a file of it goes: an rmtree in place let a joining process make its lock files in the half-removed
    folder and copy a seed while it was being deleted (train 37+19+08+06+13's agents-test, hal2 plan 0480)."""
    root, use = _STATE.pop("root", None), _STATE.pop("use", None)
    if root is None:
        return
    os.close(use)
    gone = root.with_name(f"{root.name}.gone-{os.getpid()}")
    try:
        with _locked(root / "mutex", fcntl.LOCK_EX):
            fd = os.open(root / "use", os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return  # another process still uses the root
            finally:
                os.close(fd)
            os.rename(root, gone)  # out of every joiner's reach at once: a joiner now makes a new root
    except OSError:
        return
    for old in root.parent.glob(f"{root.name}.gone-*"):  # this one, and those of a leaver killed while deleting
        shutil.rmtree(old, True)


class _locked:
    """`with _locked(path, mode)`: an flock on `path` (created), checked to still be the file at `path`: the last
    process out removes the root with its lock files."""

    def __init__(self, path, mode):
        self.path, self.mode = path, mode

    def __enter__(self):
        while True:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(fd, self.mode)
            try:
                if os.fstat(fd).st_ino == os.stat(self.path).st_ino:
                    self.fd = fd
                    return self
            except FileNotFoundError:
                pass
            os.close(fd)

    def __exit__(self, *exc):
        os.close(self.fd)  # closing releases the flock


def _relocate(top, moves):
    """Rewrite the old folder's paths in every git file that holds one (`.git` links, `gitdir`, `config`,
    `FETCH_HEAD`): objects and the index hold none."""
    for root, dirs, files in os.walk(top):
        dirs[:] = [d for d in dirs if d not in ("objects", "hooks")]
        for name in files:
            if name == "index":
                continue
            path = os.path.join(root, name)
            if os.path.islink(path) or os.path.getsize(path) > 1 << 20:
                continue
            with open(path, "rb") as f:
                data = f.read()
            new = data
            for old, to in moves:
                new = new.replace(old, to)
            if new != data:
                with open(path, "wb") as f:
                    f.write(new)
