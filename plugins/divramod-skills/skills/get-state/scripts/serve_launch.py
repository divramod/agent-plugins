"""The launcher of the state page's server (hal2 plan 0369, D1), called by state.py: `ensure()` reuses a healthy
server of these scripts on the port (47369, `HAL2_STATE_PORT` overrides), stops a stale one of ours (other scripts, an
update) by the pid its `/health` names when the pid file `serve-<port>.pid` in the state dir names it too (never a
foreign server's or a spoofed pid, which is neither reused nor signalled), else starts `serve.py` detached (its own session on POSIX, a detached process
group on Windows; output to `serve.log` in the state dir) and waits up to 3 s for its `/health`. None when no server
can be had (the port is someone else's): state.py then opens the file.
"""

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
import webbrowser
from pathlib import Path
from urllib.parse import urlencode

import page

APP = "hal2-get-state"
HERE = Path(__file__).resolve().parent
PORT = 47369
LOOPBACK = "127.0.0.1"


def version() -> str:
    """A digest of the scripts' contents: a server of other scripts (an update) is not reused."""
    h = hashlib.sha256()
    for p in sorted(HERE.glob("*")):
        if p.suffix in (".py", ".js", ".css") and not p.name.startswith("test_"):
            h.update(p.name.encode() + b"\0" + p.read_bytes())
    return h.hexdigest()[:16]


VERSION = version()


def port_of() -> int:
    value = os.environ.get("HAL2_STATE_PORT", "")
    return int(value) if value.isdigit() and 0 < int(value) < 65536 else PORT


def health(port: int, timeout: float = 0.5) -> dict | None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never through a proxy
    try:
        with opener.open(f"http://{LOOPBACK}:{port}/health", timeout=timeout) as r:
            data = json.loads(r.read())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("app") == APP else None


def pid_file(port: int) -> Path:
    """The running server's pid, written by serve.py (only its user can write the state dir): a /health answer
    naming another pid is not ours (another user's server, a spoof) and is never reused nor signalled."""
    return page.state_dir() / f"serve-{port}.pid"


def write_pid(port: int) -> None:
    """Records this process as the server on `port`, atomically, readable only by its user."""
    path = pid_file(port)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".serve-", suffix=".pid", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(str(os.getpid()))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def drop_pid(port: int) -> None:
    """Removes the pid file when it still names this process."""
    if recorded_pid(port) == os.getpid():
        pid_file(port).unlink(missing_ok=True)


def recorded_pid(port: int) -> int | None:
    try:
        text = pid_file(port).read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return int(text) if text.isdecimal() else None


def ours(h: dict | None, port: int) -> bool:
    """A /health answer of our own server: a real pid (never 0, 1 or a process group) that the pid file names."""
    pid = h.get("pid") if h else None
    return isinstance(pid, int) and not isinstance(pid, bool) and pid > 1 and recorded_pid(port) == pid


def spawn(port: int) -> subprocess.Popen | None:
    d = page.state_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        log = open(d / "serve.log", "ab")  # noqa: SIM115  (handed to the child)
    except OSError:
        return None
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        kw = {"creationflags": flags}
    else:
        kw = {"start_new_session": True}
    try:
        return subprocess.Popen([sys.executable, str(HERE / "serve.py"), "--port", str(port)], cwd=HERE,
                                stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True, **kw)
    except OSError:
        return None
    finally:
        log.close()


def ensure(port: int | None = None, wait: float = 3.0) -> int | None:
    """The port of a healthy server of these scripts: reused, else started (a stale one of ours stopped first)."""
    port = port or port_of()
    h = health(port)
    if h and not ours(h, port):
        return None  # another user's server or a spoof on the port: neither reused nor signalled
    if h and h.get("version") == VERSION:
        return port
    if h:
        if h["pid"] == os.getpid():
            return None
        try:
            os.kill(h["pid"], signal.SIGTERM)
        except OSError:
            return None
        end = time.monotonic() + 1.0
        while health(port, 0.2) and time.monotonic() < end:
            time.sleep(0.05)
    proc = spawn(port)
    end = time.monotonic() + wait
    while proc and time.monotonic() < end:
        h = health(port, 0.2)
        if h and h.get("version") == VERSION and ours(h, port):
            return port
        if proc.poll() is not None:  # it could not bind: the port is someone else's
            return None
        time.sleep(0.05)
    return None


def page_url(port: int, repo: str, role: str | None) -> str:
    query = {"repo": os.path.abspath(repo), **({"role": role} if role else {})}
    return f"http://{LOOPBACK}:{port}/?{urlencode(query)}"


def open_url(url: str) -> bool:
    try:
        return bool(webbrowser.open(url))
    except Exception:  # noqa: BLE001  (no browser: the printed URL is enough)
        return False
