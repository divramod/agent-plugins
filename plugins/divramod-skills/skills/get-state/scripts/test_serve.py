"""The state page's loopback server (hal2 plan 0369, D1, D4, D9): a round trip over a real socket on a free port, with a
fake collector, page and table function (no git, no browser), the settings file in a temporary state dir."""

import contextlib
import http.client
import io
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote

import page
import serve
import serve_launch
import view_farmer


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch.object(page, "state_dir", return_value=self.tmp / "state")
        p.start()
        self.addCleanup(p.stop)
        self.calls = 0
        self.server = self.start()

    def start(self, **kw) -> serve.ThreadingHTTPServer:
        server = serve.make_server(0, collect=kw.pop("collect", self.collect), page_fn=self.page, table=self.table,
                                   roles=("farmer", "foreman"), **kw)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        server.thread = thread
        self.addCleanup(thread.join, 5)
        self.addCleanup(serve.stop, server)
        return server

    def collect(self, repo: str, role: str | None = None) -> dict:
        self.calls += 1
        return {"repo": repo, "n": self.calls}

    def page(self, data: dict, repo: str, role) -> str:
        return f"<html>page {data['n']} of {repo} as {role}</html>"

    def table(self, data: dict, repo: str, role, table_id: str):
        return {"kind": "grid", "id": table_id, "n": data["n"]} if table_id in ("queue", "fields", "free") else None

    def call(self, method: str, path: str, body=None, headers=None, server=None):
        port = (server or self.server).server_address[1]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        hdrs = {"Host": f"127.0.0.1:{port}", **(headers or {})}
        data = None
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            hdrs.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=data, headers=hdrs)
        r = conn.getresponse()
        text = r.read().decode()
        conn.close()
        return r.status, text

    def q(self, role: str = "farmer") -> str:
        return f"?repo={quote(str(self.tmp))}&role={role}"


class Server(Base):
    def test_health_names_the_app(self):
        status, text = self.call("GET", "/health")
        self.assertEqual(status, 200)
        data = json.loads(text)
        self.assertEqual((data["app"], data["version"], data["port"]), (serve_launch.APP, serve_launch.VERSION, self.server.server_address[1]))

    def test_the_page_is_rendered_fresh_on_every_request(self):
        self.assertEqual(self.call("GET", "/" + self.q()), (200, f"<html>page 1 of {self.tmp} as farmer</html>"))
        self.assertEqual(self.call("GET", "/" + self.q())[1], f"<html>page 2 of {self.tmp} as farmer</html>")
        self.assertEqual(self.call("GET", f"/?repo={quote(str(self.tmp))}")[1], f"<html>page 3 of {self.tmp} as None</html>")

    def test_a_table_refresh_answers_its_section(self):
        status, text = self.call("GET", "/table/fields" + self.q())
        self.assertEqual((status, json.loads(text)), (200, {"kind": "grid", "id": "fields", "n": 1}))
        self.assertEqual(self.call("GET", "/table/nope" + self.q())[0], 404)
        self.assertEqual(self.call("GET", "/table/a%2Fb" + self.q())[0], 404)

    def test_settings_round_trip(self):
        self.assertEqual(self.call("GET", "/settings"), (200, "{}"))
        fields = {"order": ["wt", "plan"], "hidden": ["done_pct"], "sort": {"key": "wt", "dir": "asc"}, "filter": "all",
                  "widths": {"plan": 240}}
        status, text = self.call("PUT", "/settings", {"fields": fields, "queue": {"order": ["place"]}})
        self.assertEqual((status, json.loads(text)), (200, {"fields": fields, "queue": {"order": ["place"]}}))
        self.call("PUT", "/settings", {"queue": None})
        self.assertEqual(json.loads(self.call("GET", "/settings")[1]), {"fields": fields})
        on_disk = json.loads((self.tmp / "state" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk, {"fields": fields})
        self.assertEqual([p.name for p in (self.tmp / "state").iterdir()], ["settings.json"])  # no temp file left

    def test_a_corrupt_settings_file_reads_as_empty(self):
        (self.tmp / "state").mkdir()
        (self.tmp / "state" / "settings.json").write_text("[1, 2", encoding="utf-8")
        self.assertEqual(self.call("GET", "/settings"), (200, "{}"))
        self.assertEqual(json.loads(self.call("PUT", "/settings", {"free": {}})[1]), {"free": {}})

    def test_foreign_requests_are_refused(self):
        port = self.server.server_address[1]
        for headers in ({"Host": "evil.example"}, {"Host": f"rebind.example:{port}"},
                        {"Origin": "http://evil.example"}, {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"}):
            self.assertEqual(self.call("GET", "/settings", headers=headers)[0], 403, headers)
        self.assertEqual(self.call("GET", "/settings", headers={"Origin": f"http://localhost:{port}",
                                                                "Sec-Fetch-Site": "same-origin"})[0], 200)

    def test_bad_bodies_are_refused(self):
        self.assertEqual(self.call("PUT", "/settings", [1, 2])[0], 400)
        self.assertEqual(self.call("PUT", "/settings", b"{nope")[0], 400)
        self.assertEqual(self.call("PUT", "/settings", {"x": 1})[0], 400)
        self.assertEqual(self.call("PUT", "/settings", {"a/b": {}})[0], 400)
        self.assertEqual(self.call("PUT", "/settings", {"x": "y" * serve.MAX_BODY})[0], 413)
        self.assertEqual(self.call("PUT", "/settings", {"x": {}}, {"Content-Type": "text/plain"})[0], 415)
        for constant in (b'{"x": {"w": NaN}}', b'{"x": {"w": Infinity}}', b'{"x": {"w": -Infinity}}'):
            self.assertEqual(self.call("PUT", "/settings", constant)[0], 400, constant)  # the browser could not read it back
        self.assertFalse((self.tmp / "state" / "settings.json").exists())

    def test_bad_queries_and_paths(self):
        self.assertEqual(self.call("GET", "/?repo=relative")[0], 400)
        self.assertEqual(self.call("GET", f"/?repo={quote(str(self.tmp / 'gone'))}")[0], 400)
        self.assertEqual(self.call("GET", "/" + self.q("king"))[0], 400)
        self.assertEqual(self.call("GET", "/nowhere")[0], 404)
        self.assertEqual(self.call("PUT", "/table/fields", {})[0], 404)

    def test_a_failing_collector_answers_500_and_the_server_lives_on(self):
        server = self.start(collect=mock.Mock(side_effect=RuntimeError("git broke")))
        with contextlib.redirect_stderr(io.StringIO()) as err:
            status, text = self.call("GET", "/" + self.q(), server=server)
        self.assertEqual((status, json.loads(text)["error"]), (500, "git broke"))
        self.assertIn("git broke", err.getvalue())
        self.assertEqual(self.call("GET", "/health", server=server)[0], 200)

    def test_it_exits_when_idle(self):
        server = self.start(idle=0.2)
        server.thread.join(3)
        self.assertFalse(server.thread.is_alive())

    def test_the_default_table_is_the_farmers_only(self):
        fake = mock.Mock(return_value={"id": "fields"})
        with mock.patch.object(view_farmer, "table", fake, create=True):
            self.assertEqual(serve.table_default({"repo": "/x"}, "/x", "farmer", "fields"), {"id": "fields"})
            self.assertIsNone(serve.table_default({"repo": "/x"}, "/x", "foreman", "fields"))
        fake.assert_called_once_with({"repo": "/x"}, "fields")


class Launcher(Base):
    def test_a_healthy_server_of_these_scripts_is_reused(self):
        serve_launch.write_pid(self.server.server_address[1])  # what serve.py's main writes
        with mock.patch.object(serve_launch, "spawn") as spawn:
            self.assertEqual(serve_launch.ensure(self.server.server_address[1]), self.server.server_address[1])
        spawn.assert_not_called()

    def test_a_server_the_pid_file_does_not_name_is_neither_reused_nor_signalled(self):
        port = self.server.server_address[1]
        for pid in (os.getpid(), -1, 0, 1, True, 99999999):
            stale = {"app": serve_launch.APP, "pid": pid, "port": port, "version": "old"}
            for h in (stale, {**stale, "version": serve_launch.VERSION}):
                with mock.patch.object(serve_launch, "health", return_value=h), \
                        mock.patch.object(serve_launch.os, "kill") as kill, mock.patch.object(serve_launch, "spawn") as spawn:
                    self.assertIsNone(serve_launch.ensure(port), (pid, h))
                kill.assert_not_called()
                spawn.assert_not_called()

    def test_a_stale_server_of_ours_is_stopped_by_its_recorded_pid(self):
        port = self.server.server_address[1]
        (self.tmp / "state").mkdir(exist_ok=True)
        serve_launch.pid_file(port).write_text("4242", encoding="ascii")
        h = {"app": serve_launch.APP, "pid": 4242, "port": port, "version": "old"}
        with mock.patch.object(serve_launch, "health", side_effect=[h, None]), \
                mock.patch.object(serve_launch.os, "kill") as kill, mock.patch.object(serve_launch, "spawn", return_value=None):
            self.assertIsNone(serve_launch.ensure(port))
        kill.assert_called_once_with(4242, serve_launch.signal.SIGTERM)

    def test_the_pid_file_is_written_atomically_and_dropped_only_by_its_process(self):
        serve_launch.write_pid(5)
        self.assertEqual(serve_launch.recorded_pid(5), os.getpid())
        self.assertEqual([p.name for p in (self.tmp / "state").iterdir()], ["serve-5.pid"])
        serve_launch.pid_file(5).write_text("4242", encoding="ascii")
        serve_launch.drop_pid(5)
        self.assertTrue(serve_launch.pid_file(5).exists())
        serve_launch.write_pid(5)
        serve_launch.drop_pid(5)
        self.assertFalse(serve_launch.pid_file(5).exists())

    def test_no_server_when_the_child_cannot_bind(self):
        port = self.server.server_address[1]
        serve.stop(self.server)
        proc = mock.Mock(**{"poll.return_value": 1})
        start = time.monotonic()
        with mock.patch.object(serve_launch, "spawn", return_value=proc):
            self.assertIsNone(serve_launch.ensure(port))
        self.assertLess(time.monotonic() - start, 2)

    def test_the_page_url(self):
        self.assertEqual(serve_launch.page_url(47369, "/a b/c", "farmer"), "http://127.0.0.1:47369/?repo=%2Fa+b%2Fc&role=farmer")
        self.assertEqual(serve_launch.page_url(5, "/r", None), "http://127.0.0.1:5/?repo=%2Fr")


if __name__ == "__main__":
    unittest.main()
