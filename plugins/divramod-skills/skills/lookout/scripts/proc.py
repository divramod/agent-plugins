"""One bounded child process: stdin, cwd, env, a timeout that kills the whole process group.

Used by the check runner and the judge. Never a shell. POSIX: the child leads a new session, a timeout sends SIGKILL
to its group; Windows: a new process group, a timeout runs `taskkill /F /T` on its tree. Stdlib only.
"""

import os
import signal
import subprocess
import time


def _spawn_options():
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def _kill_tree(proc):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def run(argv, *, cwd, env, stdin=b"", timeout=60):
    """Run argv to its end or the timeout.

    Returns {"code": int or None, "timed_out": bool, "out": bytes, "err": bytes, "ms": int, "error": str or None};
    `error` names a start failure (missing program, bad cwd), with `code` None.
    """
    start = time.monotonic()
    result = {"code": None, "timed_out": False, "out": b"", "err": b"", "ms": 0, "error": None}
    try:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, **_spawn_options())
    except (OSError, ValueError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    try:
        out, err = proc.communicate(stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:  # a grandchild that left the group may still hold the pipes: do not wait for it
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            out, err = b"", b""
        result["timed_out"] = True
    result.update(code=None if result["timed_out"] else proc.returncode, out=out or b"", err=err or b"",
                  ms=int((time.monotonic() - start) * 1000))
    return result


def tail(data, limit=2048):
    """The last `limit` bytes of a child's output, as text."""
    return data[-limit:].decode("utf-8", errors="replace")
