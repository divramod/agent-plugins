"""`design.py serve` (hal2 plan 0364, D7): the server on a free loopback port in a thread, its API and guards."""
import http.client
import json
import socket
import sys
import tempfile
import threading
import unittest
from unittest import mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import review  # noqa: E402
import serve  # noqa: E402
import store  # noqa: E402
from test_review import make_folder  # noqa: E402


class ServeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = make_folder(Path(self.tmp.name))
        self.server = serve.make_server(self.folder, "127.0.0.1", 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        self.tmp.cleanup()

    def call(self, method, path, body=None, headers=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        head = {"Content-Type": "application/json"} if method == "POST" else {}
        head.update(headers or {})
        payload = raw if raw is not None else (json.dumps(body) if body is not None else None)
        conn.request(method, path, body=payload, headers=head)
        res = conn.getresponse()
        data = res.read()
        conn.close()
        return res.status, data

    def post(self, path, body, **kw):
        status, data = self.call("POST", path, body, **kw)
        return status, json.loads(data)

    def test_binds_loopback_only_and_refuses_other_hosts(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertEqual(serve.url_of(self.server), f"http://127.0.0.1:{self.port}/")
        for host in ("0.0.0.0", "192.168.1.5", "example.com", ""):
            with self.assertRaises(store.StoreError, msg=host):
                serve.make_server(self.folder, host, 0)
        other = serve.make_server(self.folder, "localhost", 0)
        self.assertEqual(other.server_address[0], "127.0.0.1")
        other.server_close()

    def test_page_is_rendered_fresh_with_the_saved_state(self):
        status, page = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"plan 0070 login - design", page)
        review.set_accepted(self.folder, "login/gui/v1", True)
        _, again = self.call("GET", "/design.html")
        self.assertIn(b'"accepted": true', again)

    def test_state_accept_comment_delete_roundtrip(self):
        status, state = self.call("GET", "/state")
        self.assertEqual((status, json.loads(state)), (200, {"schema": 1, "designs": {}}))
        status, out = self.post("/accept", {"id": "login/gui/v1", "accepted": True})
        self.assertEqual(status, 200)
        self.assertTrue(out["designs"]["login/gui/v1"]["accepted"])
        status, out = self.post("/accept", {"id": "login/gui/v2", "accepted": True})
        self.assertFalse(out["designs"]["login/gui/v1"]["accepted"])
        status, out = self.post("/comment", {"id": "login/gui/v2", "text": "move the button", "anchor": "screen.html"})
        comment = out["designs"]["login/gui/v2"]["comments"][0]
        self.assertEqual((comment["text"], comment["by"], comment["anchor"]), ("move the button", "user", "screen.html"))
        saved = json.loads(review.state_path(self.folder).read_text())
        self.assertEqual(saved["designs"]["login/gui/v2"]["comments"][0]["text"], "move the button")
        status, out = self.post("/comment/delete", {"id": "login/gui/v2", "index": 0, "at": comment["at"]})
        self.assertEqual((status, out["designs"]["login/gui/v2"]["comments"]), (200, []))
        self.assertEqual(json.loads(self.call("GET", "/state")[1])["designs"]["login/gui/v2"]["accepted"], True)

    def test_a_write_also_refreshes_design_html_for_file_urls(self):
        self.post("/accept", {"id": "login/gui/v1", "accepted": True})
        self.assertIn('"accepted": true', (self.folder / "design.html").read_text())

    def test_bad_requests_are_answered_not_saved(self):
        cases = [("/accept", {"id": "login/gui/v9", "accepted": True}, 404),
                 ("/accept", {"id": "../../etc/passwd", "accepted": True}, 400),
                 ("/accept", {"id": "login/gui/v1", "accepted": "yes"}, 400),
                 ("/comment", {"id": "login/gui/v1", "text": "  "}, 400),
                 ("/comment/delete", {"id": "login/gui/v1", "index": 3}, 404),
                 ("/nope", {}, 404)]
        for path, body, code in cases:
            status, out = self.post(path, body)
            self.assertEqual(status, code, (path, body))
            self.assertIn("error", out)
        self.assertFalse(review.state_path(self.folder).exists())
        self.assertEqual(self.call("GET", "/nope")[0], 404)

    def test_body_guards(self):
        self.assertEqual(self.call("POST", "/accept", raw="{not json")[0], 400)
        self.assertEqual(self.call("POST", "/accept", raw="[1]")[0], 400)
        self.assertEqual(self.call("POST", "/accept", body={}, headers={"Content-Type": "text/plain"})[0], 415)
        big = json.dumps({"id": "login/gui/v1", "text": "x" * (serve.MAX_BODY + 1)})
        self.assertEqual(self.call("POST", "/comment", raw=big)[0], 413)
        self.assertFalse(review.state_path(self.folder).exists())

    def test_a_non_ascii_digit_length_is_refused_not_a_crash(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            sock.sendall(b"POST /accept HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nContent-Type: application/json\r\n"
                         b"Content-Length: \xb2\r\nConnection: close\r\n\r\n{}" % self.port)
            answer = b""
            while chunk := sock.recv(4096):
                answer += chunk
        self.assertTrue(answer.startswith(b"HTTP/1.0 411") or answer.startswith(b"HTTP/1.1 411"), answer[:40])

    def test_a_value_error_inside_a_handler_answers_400(self):
        for error in (ValueError("bad value"), json.JSONDecodeError("bad", "x", 0)):
            def boom(*_args, _error=error, **_kw):
                raise _error
            with mock.patch.object(review, "set_accepted", boom):
                status, out = self.post("/accept", {"id": "login/gui/v1", "accepted": True})
            self.assertEqual(status, 400, error)
            self.assertIn("error", out)

    def test_foreign_origin_and_host_are_refused(self):
        body = {"id": "login/gui/v1", "accepted": True}
        for origin in ("http://evil.example", "null", f"http://127.0.0.1:{self.port + 1}", "https://127.0.0.1"):
            status, out = self.post("/accept", body, headers={"Origin": origin})
            self.assertEqual((status, out["error"]), (403, "foreign origin"), origin)
        status, out = self.post("/accept", body, headers={"Host": "evil.example"})
        self.assertEqual((status, out["error"]), (403, "foreign host"))
        self.assertEqual(self.call("GET", "/state", headers={"Host": f"evil.example:{self.port}"})[0], 403)
        self.assertFalse(review.state_path(self.folder).exists())
        own = f"http://localhost:{self.port}"
        self.assertEqual(self.post("/accept", body, headers={"Origin": own, "Host": f"localhost:{self.port}"})[0], 200)

    def test_concurrent_comments_are_all_kept(self):
        def add(n):
            self.post("/comment", {"id": "login/gui/v1", "text": f"c{n}"})
        threads = [threading.Thread(target=add, args=(n,)) for n in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        saved = json.loads(review.state_path(self.folder).read_text())
        self.assertEqual(sorted(c["text"] for c in saved["designs"]["login/gui/v1"]["comments"]),
                         sorted(f"c{n}" for n in range(12)))


if __name__ == "__main__":
    unittest.main()
