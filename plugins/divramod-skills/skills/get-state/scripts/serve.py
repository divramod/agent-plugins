#!/usr/bin/env python3
"""The state page's loopback server (hal2 plan 0369, D1, D4, D9), stdlib only, 127.0.0.1 only.

    serve.py [--port <n>] [--idle <seconds>]

  GET /health                   {"app": "hal2-get-state", "pid", "port", "version"}
  GET /?repo=<path>[&role=<r>]  the role's page, rendered fresh (state.collect, the view, page.render)
  GET /table/<id>?repo=&role=   one grid section's JSON (the farmer's view.table; 404 for another role or id)
  GET /settings                 {<table id>: settings} from `<state dir>/settings.json`
  PUT /settings                 {<table id>: settings | null} merged (null drops the entry); answers the whole map
One server per user for every repository and role, port 47369 (`HAL2_STATE_PORT` overrides); it exits after 30
idle minutes. Refused: a Host or Origin that is not the server's own (DNS rebinding, another site, `file://`), a
cross-site fetch (`Sec-Fetch-Site`), a body that is not a JSON object under 64 KiB. The launcher state.py
calls (reuse, else start detached) is serve_launch.py.
"""

import argparse
import json
import os
import re
import signal
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import page
from serve_launch import APP, VERSION, drop_pid, port_of, write_pid

IDLE = 30 * 60
MAX_BODY = 64 * 1024
LOOPBACK = "127.0.0.1"
HOSTS = ("127.0.0.1", "localhost")
FETCH_SITES = {None, "none", "same-origin"}
TABLE_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
LOCK = threading.Lock()


class Refused(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


# The table settings (D4): one JSON file in the state dir, merged under a lock, written atomically.

def settings_path() -> Path:
    return page.state_dir() / "settings.json"


def load_settings() -> dict:
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def merge_settings(update: dict) -> dict:
    """Merges `{id: settings | null}` into the file (null drops the id) and returns the whole map."""
    for key, value in update.items():
        if not TABLE_ID.fullmatch(key):
            raise Refused(400, f"bad table id '{key[:70]}'")
        if value is not None and not isinstance(value, dict):
            raise Refused(400, f"settings of '{key}' must be an object or null")
    with LOCK:
        data = load_settings()
        for key, value in update.items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
        path = settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".settings-", suffix=".json", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    return data


# The default page and table functions: the real collector and views (imported late, so a test needs none).

def collect_default(repo: str, role: str | None = None) -> dict:
    import state
    return state.collect(repo, here=repo, **state.page_facts(repo, role))


def page_default(data: dict, repo: str, role: str | None) -> str:
    import state
    return state.page_html(data, repo, role)[1]


def table_default(data: dict, repo: str, role: str | None, table_id: str) -> dict | None:
    import state
    import view_farmer
    fn = getattr(view_farmer, "table", None)
    if fn is None or state.role_of(data, repo, role) != "farmer":
        return None
    return fn(data, table_id)


def _no_constant(name: str):
    """NaN and Infinity are no JSON: stored, they would make every later GET /settings unreadable to the browser."""
    raise ValueError(f"{name} is not JSON")


class Handler(BaseHTTPRequestHandler):
    server_version = "hal2-get-state"

    def log_message(self, fmt, *args):  # quiet: the log keeps only start and errors
        pass

    def _send(self, code: int, body: bytes, kind: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, data) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _guard(self) -> None:
        port = self.server.server_address[1]
        own = {f"{host}:{port}" for host in HOSTS}
        if self.headers.get("Host", "") not in own:
            raise Refused(403, "foreign host")
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {f"http://{h}" for h in own}:
            raise Refused(403, "foreign origin")
        if self.headers.get("Sec-Fetch-Site") not in FETCH_SITES:
            raise Refused(403, "cross-site request")

    def _body(self) -> dict:
        if not (self.headers.get("Content-Type") or "").lower().startswith("application/json"):
            raise Refused(415, "send application/json")
        length = self.headers.get("Content-Length")
        if length is None or not re.fullmatch(r"[0-9]+", length):
            raise Refused(411, "Content-Length required")
        if int(length) > MAX_BODY:
            raise Refused(413, f"body over {MAX_BODY} bytes")
        try:
            body = json.loads(self.rfile.read(int(length)) or b"null", parse_constant=_no_constant)
        except ValueError:  # JSONDecodeError, UnicodeDecodeError, NaN or Infinity
            raise Refused(400, "body is not JSON") from None
        if not isinstance(body, dict):
            raise Refused(400, "body must be a JSON object")
        return body

    def _query(self) -> tuple[str, str | None]:
        q = parse_qs(urlsplit(self.path).query)
        repo = (q.get("repo") or [""])[0]
        role = (q.get("role") or [None])[0] or None
        if not repo or not os.path.isabs(repo) or not os.path.isdir(repo):
            raise Refused(400, "repo must name an existing folder by its absolute path")
        if role is not None and role not in self.server.roles:
            raise Refused(400, f"unknown role '{role[:40]}'")
        return repo, role

    def _handle(self, run) -> None:
        self.server.last = time.monotonic()
        try:
            self._guard()
            run(urlsplit(self.path).path)
        except Refused as err:
            self._json(err.code, {"error": str(err)})
        except Exception as err:  # noqa: BLE001  (a failing collector answers 500, the server keeps running)
            print(f"error {self.command} {self.path}: {err!r}", file=sys.stderr, flush=True)
            self._json(500, {"error": str(err)})

    def do_GET(self):
        def run(path: str) -> None:
            s = self.server
            if path == "/health":
                self._json(200, {"app": APP, "pid": os.getpid(), "port": s.server_address[1], "version": VERSION})
            elif path == "/settings":
                self._json(200, load_settings())
            elif path == "/":
                repo, role = self._query()
                self._send(200, s.page(s.collect(repo, role), repo, role).encode(), "text/html; charset=utf-8")
            elif path.startswith("/table/") and TABLE_ID.fullmatch(unquote(path[7:])):
                repo, role = self._query()
                section = s.table(s.collect(repo, role), repo, role, unquote(path[7:]))
                if section is None:
                    raise Refused(404, "no such table")
                self._json(200, section)
            else:
                raise Refused(404, "not found")
        self._handle(run)

    def do_PUT(self):
        def run(path: str) -> None:
            if path != "/settings":
                raise Refused(404, "not found")
            self._json(200, merge_settings(self._body()))
        self._handle(run)


def watch(server: ThreadingHTTPServer, idle: float) -> None:
    """Shuts the server down after `idle` seconds without a request."""
    while not server.stopped.wait(max(0.05, min(idle / 4, 30))):
        if time.monotonic() - server.last > idle:
            server.shutdown()
            return


def make_server(port: int = 0, collect=None, page_fn=None, table=None, idle: float = IDLE,
                roles: tuple = ()) -> ThreadingHTTPServer:
    """A server on 127.0.0.1:`port` (0: any free port) with its idle watcher; the callables default to the real ones."""
    server = ThreadingHTTPServer((LOOPBACK, port), Handler)
    server.daemon_threads = True
    server.collect, server.page, server.table = collect or collect_default, page_fn or page_default, table or table_default
    if not roles:
        import role as role_mod
        roles = role_mod.ROLES
    server.roles, server.last, server.stopped = set(roles), time.monotonic(), threading.Event()
    threading.Thread(target=watch, args=(server, idle), daemon=True).start()
    return server


def stop(server: ThreadingHTTPServer) -> None:
    server.stopped.set()
    server.shutdown()
    server.server_close()


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=port_of(), help="the port (default 47369, HAL2_STATE_PORT)")
    p.add_argument("--idle", type=float, default=IDLE, help="exit after this many idle seconds (default 1800)")
    args = p.parse_args(argv)
    try:
        server = make_server(args.port, idle=args.idle)
    except OSError as err:
        print(f"cannot bind {LOOPBACK}:{args.port}: {err}", file=sys.stderr)
        return 1
    try:
        write_pid(args.port)
    except OSError as err:
        print(f"cannot write the pid file: {err}", file=sys.stderr)
        server.server_close()
        return 1
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _terminate)
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} serving http://{LOOPBACK}:{args.port}/ pid {os.getpid()}", flush=True)
    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        drop_pid(args.port)
    server.stopped.set()
    server.server_close()
    return 0


def _terminate(signum, frame):  # SIGTERM (the launcher stopping a stale server): leave through main's cleanup
    raise SystemExit(0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
