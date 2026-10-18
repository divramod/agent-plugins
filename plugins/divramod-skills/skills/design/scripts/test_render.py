"""The one design.html (hal2 plan 0364, D3-D5): fixed layout, embedded data, renderers, review hook, determinism."""
import datetime as dt
import json
import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import render  # noqa: E402
import review  # noqa: E402
import store  # noqa: E402

NOW = dt.datetime(2026, 10, 18, 12, 0, tzinfo=dt.timezone.utc)
DATA = re.compile(r'<script type="application/json" id="design-data">(.*?)</script>', re.S)


def embedded(html: str) -> dict:
    return json.loads(DATA.search(html).group(1))


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name) / "plans" / "0042-login-page"
        self.folder.mkdir(parents=True)
        (self.folder / "plan.md").write_text("---\ntype: Plan\ntitle: \"login page\"\n---\n")
        gui = store.new_version(self.folder, "login", "gui", title="login screen", now=NOW)
        (gui / "current.html").write_text("<p>old</p>")
        (gui / "new.html").write_text("<p>new</p></script><script>alert(1)</script>")
        erd = store.new_version(self.folder, "login", "erd", now=NOW)
        (erd / "current.dbml").write_text("Table users { id int\n name varchar }")
        (erd / "new.dbml").write_text("Table users { id int\n email varchar }")
        flow = store.new_version(self.folder, "signup", "flow", now=NOW)
        (flow / "flow.mmd").write_text("flowchart LR\n a --> b")
        (flow / "logo.png").write_bytes(b"\x89PNG\r\n")
        store.new_version(self.folder, "signup", "flow", now=NOW)

    def tearDown(self):
        self.tmp.cleanup()

    def test_page_has_the_fixed_layout(self):
        html = render.page(render.model(self.folder))
        self.assertIn("<title>plan 0042 login page - design</title>", html)
        for part in ('id="feat-tabs"', 'id="kind-tabs"', 'id="version-tabs"', 'id="prev"', 'id="next"',
                     'data-view="feats"', 'data-view="designs"', 'id="compare-bar"'):
            self.assertIn(part, html)
        self.assertNotIn("{{", html)
        self.assertNotIn("/*{{", html)

    def test_model_orders_feats_kinds_versions(self):
        data = render.model(self.folder)
        self.assertEqual(data["title"], "plan 0042 login page - design")
        self.assertEqual([f["id"] for f in data["feats"]], ["login", "signup"])
        self.assertEqual([k["id"] for k in data["feats"][0]["kinds"]], ["gui", "erd"])
        self.assertEqual([v["id"] for v in data["feats"][1]["kinds"][0]["versions"]],
                         ["signup/flow/v1", "signup/flow/v2"])

    def test_files_roles_erd_and_images(self):
        data = render.model(self.folder)
        gui, erd = (k["versions"][0]["files"] for k in data["feats"][0]["kinds"])
        self.assertEqual([(f["name"], f["role"]) for f in gui], [("current.html", "current"), ("new.html", "new")])
        current, new = erd
        self.assertNotIn("erd-legend", current["html"])
        self.assertIn("erd-legend", new["html"])
        self.assertIn('st-added', new["html"])
        files = {f["name"]: f for f in data["feats"][1]["kinds"][0]["versions"][1]["files"]}
        self.assertEqual(list(files), ["flow.mmd", "logo.png"])
        png = files["logo.png"]
        self.assertTrue(png["data"].startswith("data:image/png;base64,"))

    def test_embedded_data_cannot_close_the_script(self):
        html = render.page(render.model(self.folder))
        self.assertEqual(html.count("</script>"), 2)
        data = embedded(html)
        new = data["feats"][0]["kinds"][0]["versions"][0]["files"][1]
        self.assertIn("</script><script>alert(1)</script>", new["text"])

    def test_review_state_is_read_into_the_page(self):
        (self.folder / "design" / "state.json").write_text(json.dumps({"schema": 1, "designs": {
            "login/gui/v1": {"accepted": True, "comments": [{"at": "2026-10-18", "by": "user", "text": "ok"}]}}}))
        data = render.model(self.folder)
        review = data["feats"][0]["kinds"][0]["versions"][0]["review"]
        self.assertEqual(review, {"accepted": True, "comments": [{"at": "2026-10-18", "by": "user", "text": "ok"}]})
        other = data["feats"][0]["kinds"][1]["versions"][0]["review"]
        self.assertEqual(other, {"accepted": False, "comments": []})
        self.assertEqual(data["serve"], "design.py serve --plan 0042-login-page")

    def test_renderers_and_pinned_libraries(self):
        html = render.page(render.model(self.folder))
        for ext in ('".html"', '".mmd"', '".md"', '".excalidraw"', '".dbml"'):
            self.assertIn(ext, html)
        self.assertIn("mermaid@11.17.2", html)
        self.assertIn("marked@15.0.12", html)
        self.assertIn("@excalidraw/excalidraw@0.18.1", html)
        self.assertIn('sandbox: "allow-scripts"', html)
        self.assertIn('"data-design-id"', html)

    def test_render_writes_design_html_deterministically(self):
        target = render.render(self.folder)
        self.assertEqual(target, self.folder / "design.html")
        first = target.read_text()
        render.render(self.folder)
        self.assertEqual(target.read_text(), first)

    def test_render_is_atomic_and_waits_for_the_review_lock(self):
        target = self.folder / "design.html"
        target.write_text("old page")
        done = threading.Event()
        with review.LOCK:  # a state write is going on: the render waits
            worker = threading.Thread(target=lambda: (render.render(self.folder), done.set()), daemon=True)
            worker.start()
            self.assertFalse(done.wait(0.3))
            self.assertEqual(target.read_text(), "old page")
        self.assertTrue(done.wait(10))
        worker.join(5)
        self.assertIn("design-data", target.read_text())
        self.assertEqual(oct(target.stat().st_mode & 0o777), "0o644")
        self.assertEqual([p.name for p in self.folder.glob(".design-*")], [])

    def test_a_failed_render_keeps_the_old_page_and_leaves_no_temp_file(self):
        target = self.folder / "design.html"
        target.write_text("old page")
        with mock.patch.object(render.os, "replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                render.render(self.folder)
        self.assertEqual(target.read_text(), "old page")
        self.assertEqual([p.name for p in self.folder.glob(".design-*")], [])

    def test_markdown_is_drawn_in_a_script_free_sandbox_and_a_bad_hash_is_caught(self):
        js = (HERE / "page.js").read_text()
        body = js[js.index("async function drawMarkdown"):js.index("async function drawExcalidraw")]
        self.assertNotIn("innerHTML", body)
        self.assertIn('sandbox: ""', body)
        self.assertIn("srcdoc", body)
        self.assertIn("default-src 'none'", js)
        self.assertNotIn("allow-same-origin", js)
        read = js[js.index("function readHash"):js.index("function writeHash")]
        self.assertRegex(read, r"try \{[^}]*decodeURIComponent[^}]*\} catch")

    def test_empty_store_renders(self):
        empty = Path(self.tmp.name) / "plans" / "0043-empty"
        empty.mkdir()
        data = render.model(empty)
        self.assertEqual(data["feats"], [])
        self.assertIn("no designs yet", render.page(data))


if __name__ == "__main__":
    unittest.main()
