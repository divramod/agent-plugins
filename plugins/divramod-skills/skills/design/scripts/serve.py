"""`design.py serve` (hal2 plan 0364, D7): the review server of a plan's `design.html`, stdlib only, loopback only.

  GET  /  /design.html     the page, rendered fresh from design/ (so new versions and state show on reload)
  GET  /state              {"schema": 1, "designs": {...}}
  POST /accept             {"id": "<feat>/<kind>/v<n>", "accepted": true|false}
  POST /comment            {"id", "text", "anchor"?}
  POST /comment/delete     {"id", "index", "at"?}
A POST answers {"designs": {...}} (the new state of every design). Refused: another bind host, a Host or Origin that
is not the server's own (DNS rebinding, a page from another site, `file://`), a body that is not a JSON object under
16 KiB. Every write re-renders `design.html` too, so the `file://` view shows the saved state.
"""

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import render
import review
import store

MAX_BODY = 16 * 1024
LOOPBACK = "127.0.0.1"
HOSTS = {"127.0.0.1": LOOPBACK, "localhost": LOOPBACK}


class Refused(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


class Handler(BaseHTTPRequestHandler):
    server_version = "design-serve"

    def log_message(self, fmt, *args):  # quiet: the terminal shows only the URL
        pass

    def _send(self, code: int, body: bytes, kind: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, data: dict) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _guard(self) -> None:
        port = self.server.server_address[1]
        own = {f"{host}:{port}" for host in HOSTS}
        if self.headers.get("Host", "") not in own:
            raise Refused(403, "foreign host")
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {f"http://{h}" for h in own}:
            raise Refused(403, "foreign origin")

    def _body(self) -> dict:
        if not (self.headers.get("Content-Type") or "").lower().startswith("application/json"):
            raise Refused(415, "send application/json")
        length = self.headers.get("Content-Length")
        if length is None or not re.fullmatch(r"[0-9]+", length):
            raise Refused(411, "Content-Length required")
        if int(length) > MAX_BODY:
            raise Refused(413, f"body over {MAX_BODY} bytes")
        try:
            body = json.loads(self.rfile.read(int(length)) or b"null")
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise Refused(400, "body is not JSON") from None
        if not isinstance(body, dict):
            raise Refused(400, "body must be a JSON object")
        return body

    def _handle(self, run) -> None:
        try:
            self._guard()
            run()
        except Refused as err:
            self._json(err.code, {"error": str(err)})
        except review.ReviewError as err:
            self._json(err.code, {"error": str(err)})
        except json.JSONDecodeError as err:
            self._json(400, {"error": f"not valid JSON: {err}"})
        except ValueError as err:
            self._json(400, {"error": str(err)})
        except (store.StoreError, OSError) as err:
            self._json(500, {"error": str(err)})

    def do_GET(self):
        def run():
            folder = self.server.folder
            if self.path in ("/", "/design.html"):
                self._send(200, render.page(render.model(folder)).encode(), "text/html; charset=utf-8")
            elif self.path == "/state":
                self._json(200, review.load(folder))
            else:
                raise Refused(404, "not found")
        self._handle(run)

    def do_POST(self):
        def run():
            folder = self.server.folder
            body = self._body()
            actions = {
                "/accept": lambda: review.set_accepted(folder, body.get("id"), body.get("accepted")),
                "/comment": lambda: review.add_comment(folder, body.get("id"), body.get("text"),
                                                       body.get("anchor", ""), body.get("by", "user")),
                "/comment/delete": lambda: review.delete_comment(folder, body.get("id"), body.get("index"),
                                                                 body.get("at")),
            }
            if self.path not in actions:
                raise Refused(404, "not found")
            designs = actions[self.path]()
            try:
                render.render(folder)
            except (OSError, store.StoreError, ValueError):
                pass  # the state is saved; the file:// copy catches up on the next render
            self._json(200, {"designs": designs})
        self._handle(run)


def make_server(folder: Path, host: str = LOOPBACK, port: int = 0) -> ThreadingHTTPServer:
    """A server bound to loopback only (`localhost` means 127.0.0.1); any other host is refused."""
    if host not in HOSTS:
        raise store.StoreError(f"refusing host '{host}': the review server binds 127.0.0.1 only")
    server = ThreadingHTTPServer((HOSTS[host], port), Handler)
    server.daemon_threads = True
    server.folder = folder
    return server


def url_of(server: ThreadingHTTPServer) -> str:
    return f"http://{LOOPBACK}:{server.server_address[1]}/"
