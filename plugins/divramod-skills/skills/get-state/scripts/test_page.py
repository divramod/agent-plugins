import base64
import gzip
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import grid
import page
import steward_sources
import views

TABLE = {"heading": "Fields", "columns": ["Field", "Plan"], "rows": [["10", "<script>alert(1)</script>"], ["11", "a & b"]],
         "marked": [0]}


class Render(unittest.TestCase):
    def test_every_value_is_escaped(self):
        out = page.render("t <b>", [TABLE, {"heading": "<h>", "items": ["<i>"]}, {"heading": "p", "text": '"q"'}], "m <x>")
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", out)
        self.assertIn("a &amp; b", out)
        for raw in ("t <b>", "<h>", "<i>", "m <x>"):
            self.assertNotIn(raw, out)
        self.assertIn("&quot;q&quot;", out)

    def test_self_contained_no_script_no_network(self):
        out = page.render("t", [TABLE])
        self.assertTrue(out.startswith("<!DOCTYPE html>"))
        self.assertIn("<style>", out)
        self.assertNotRegex(out, r"(?i)<script|<link|src=|href=|https?://|@import|url\(")

    def test_light_and_dark(self):
        self.assertIn("prefers-color-scheme: dark", page.render("t", []))

    def test_a_table_its_head_its_rows_and_the_marked_row(self):
        out = page.render("t", [TABLE])
        self.assertIn("<th>Field</th><th>Plan</th>", out)
        self.assertEqual(len(re.findall(r"<tr class=\"marked\"><td>10</td>", out)), 1)
        self.assertIn("<tr><td>11</td>", out)

    def test_title_meta_and_sections_in_order(self):
        out = page.render("Title", [{"heading": "A", "text": "x"}, {"heading": "B", "items": ["y"]}], "the line")
        self.assertIn("<title>Title</title>", out)
        self.assertIn('<p class="meta">the line</p>', out)
        self.assertLess(out.index("<h2>A</h2>"), out.index("<h2>B</h2>"))
        self.assertIn("<ul><li>y</li></ul>", out)
        self.assertNotIn('class="meta"', page.render("Title", []))

    def test_empty_states(self):
        out = page.render("t", [{"heading": "a", "columns": ["x"], "rows": [], "empty": "No fields."},
                                {"heading": "b", "items": []}, {"heading": "c", "empty": "Nothing <yet>."}])
        self.assertIn('<p class="empty">No fields.</p>', out)
        self.assertIn(f'<p class="empty">{page.EMPTY}</p>', out)
        self.assertIn('<p class="empty">Nothing &lt;yet&gt;.</p>', out)
        self.assertNotIn("<table>", out)


GRID = {"kind": "grid", "id": "fields", "heading": "Plan fields", "note": "mode: smuggle <since>",
        "columns": [{"key": "field", "label": "Field"}, {"key": "done", "label": "Done %", "type": "num", "hidden": True},
                    {"key": "plan", "label": "Plan"}],
        "rows": [{"field": "07", "done": 40, "plan": "a </script><b>"}, {"field": "10", "done": 100, "plan": "b", "_marked": True},
                 {"field": "03", "done": "", "plan": "c"}, {"field": "12", "done": 75, "plan": "d"}],
        "filters": [{"key": "done", "label": "Done", "match": {"done": [100]}}, {"key": "all", "label": "All", "match": None}],
        "sort": {"key": "done", "dir": "desc"}, "empty": "No fields."}


class Grid(unittest.TestCase):
    def test_a_grid_page_inlines_the_component_and_loads_nothing(self):
        out = page.render("t", [GRID])
        self.assertIn(".grid-menu", out)
        self.assertIn("function sortRows", out)
        self.assertIn('<script type="application/json" class="grid-data">', out)
        self.assertNotRegex(out, r"(?i)<link|src=|href=|https?://|@import|url\(")
        self.assertNotIn("<script>", page.render("t", [TABLE]))

    def test_the_island_cannot_close_its_script(self):
        out = page.render("t", [GRID])
        island = out.split('class="grid-data">', 1)[1].split("</script>", 1)[0]
        self.assertNotIn("<", island)
        self.assertEqual(json.loads(island), GRID)

    def test_static_rows_default_filter_sort_and_hidden_columns(self):
        body = grid.table_html(GRID)
        self.assertIn('<th data-key="field" draggable="true" aria-sort="none">Field', body)
        self.assertNotIn('data-key="done"', body)  # hidden by default, yet the default sort key
        self.assertEqual(re.findall(r"<tr[^>]*><td>(\d+)</td>", body), ["10", "12", "07", "03"])
        self.assertIn('<tr class="marked"><td>10</td>', body)
        self.assertIn("a &lt;/script&gt;&lt;b&gt;", body)

    def test_the_default_filter(self):
        self.assertEqual(grid.default_filter(GRID), "all")
        done = {**GRID, "filter": "done"}
        self.assertEqual(re.findall(r"<tr[^>]*><td>(\d+)</td>", grid.table_html(done)), ["10"])
        self.assertIn('<p class="empty">No fields.</p>', grid.table_html({**GRID, "rows": []}))

    def test_sorting_numbers_text_and_empties(self):
        cols = [{"key": "n", "type": "num"}, {"key": "t"}]
        rows = [{"n": 9, "t": "wt 10"}, {"n": "", "t": None}, {"n": 10, "t": "wt 9"}, {"n": "x", "t": "WT 2"}]
        asc = [r["n"] for r in grid.sort_rows(rows, {"key": "n", "dir": "asc"}, cols)]
        self.assertEqual(asc, [9, 10, "x", ""])
        self.assertEqual([r["t"] for r in grid.sort_rows(rows, {"key": "t", "dir": "desc"}, cols)], ["wt 10", "wt 9", "WT 2", None])
        self.assertEqual(grid.sort_rows(rows, None, cols), rows)

    def test_sorting_text_with_non_decimal_digits_does_not_raise(self):
        rows = [{"t": "2 m²"}, {"t": "10 m²"}, {"t": "①"}]  # str.isdigit is True for ² and ①, int() refuses them
        self.assertEqual([r["t"] for r in grid.sort_rows(rows, {"key": "t", "dir": "asc"}, [{"key": "t"}])],
                         ["2 m²", "10 m²", "①"])

    def test_the_note_heading_and_tools(self):
        out = grid.grid_html(GRID)
        self.assertIn('<section class="grid" data-grid="fields">', out)
        self.assertIn('<p class="grid-note">mode: smuggle &lt;since&gt;</p>', out)
        self.assertIn('<div class="grid-tools"></div>', out)
        self.assertNotIn("grid-note", grid.grid_html({**GRID, "note": ""}))

    def test_a_big_island_is_packed_and_unpacks_to_the_section(self):
        big = {**GRID, "rows": [{"field": str(i), "plan": f"plan </script> {i} " + "x" * 400} for i in range(120)]}
        out = grid.grid_html(big)
        self.assertNotIn('type="application/json"', out)
        packed = out.split('<script type="application/gzip+base64" class="grid-data">', 1)[1].split("</script>", 1)[0]
        self.assertRegex(packed, r"^[A-Za-z0-9+/=]+$")
        self.assertEqual(json.loads(gzip.decompress(base64.b64decode(packed))), big)
        self.assertEqual(out, grid.grid_html(big))  # the same data gives the same page
        self.assertIn('type="application/json"', grid.grid_html(GRID))  # a small one stays plain

    def test_static_false_leaves_the_rows_to_the_script(self):
        out = grid.grid_html({**GRID, "static": False})
        self.assertIn(f'<div class="grid-body"><p class="empty">{grid.esc(grid.NEEDS_SCRIPT)}</p></div>', out)
        self.assertNotIn("<tbody>", out)
        self.assertIn('class="grid-data"', out)


class Files(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_the_state_dir_honours_xdg_state_home(self):
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.tmp)}), mock.patch.object(page.sys, "platform", "darwin"):
            self.assertEqual(page.state_dir(), self.tmp / "hal2" / "get-state")

    def test_the_state_dir_defaults_to_local_state(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.tmp)}), mock.patch.object(page.sys, "platform", "linux"):
            os.environ.pop("XDG_STATE_HOME", None)
            self.assertEqual(page.state_dir(), self.tmp / ".local/state/hal2/get-state")

    def test_the_state_dir_on_windows(self):
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.tmp)}), mock.patch.object(page.sys, "platform", "win32"):
            self.assertEqual(page.state_dir(), self.tmp / "hal2" / "get-state")

    def test_write_creates_the_dir_and_the_file(self):
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.tmp / "deep")}), mock.patch.object(page.sys, "platform", "darwin"):
            path = page.write("x.html", "<p>ü</p>")
        self.assertEqual(path, self.tmp / "deep/hal2/get-state/x.html")
        self.assertEqual(path.read_text(encoding="utf-8"), "<p>ü</p>")

    def test_page_name(self):
        self.assertEqual(page.page_name("hal2", "10", "foreman"), "hal2-10-foreman.html")
        self.assertEqual(page.page_name("my repo", "../x", "steward"), "my-repo-..-x-steward.html")
        self.assertEqual(page.page_name("", "/", "lord"), "x-x-lord.html")
        self.assertNotIn("/", page.page_name("a/b", "..\\c", "pope"))

    def test_open_uses_the_file_uri(self):
        f = self.tmp / "p.html"
        f.write_text("x")
        with mock.patch.object(page.webbrowser, "open", return_value=True) as o:
            self.assertTrue(page.open_page(f))
        o.assert_called_once_with(f.resolve().as_uri())
        self.assertTrue(o.call_args.args[0].startswith("file://"))

    def test_open_never_raises(self):
        with mock.patch.object(page.webbrowser, "open", side_effect=RuntimeError("no browser")):
            self.assertFalse(page.open_page(self.tmp / "p.html"))
        with mock.patch.object(page.webbrowser, "open", return_value=False):
            self.assertFalse(page.open_page(self.tmp / "p.html"))


class Views(unittest.TestCase):
    DATA = {"default": "main", "rows": [
        {"wt": "10", "own": True, "cells": ["**10**", "0366 role state views", "0 of 7", "busy", ""]},
        {"wt": "31", "own": False, "cells": ["↳ 31", "", "", "idle", "Q1"]}]}

    def test_every_role_has_a_view(self):
        for r in (*views.roles.ROLES, "unknown"):
            self.assertIn(r, views.VIEWS)

    def test_the_fallback_is_today_s_table(self):
        title, sections = views.build("unknown", self.DATA, {"repo": "hal2", "checkout": "10"})
        self.assertEqual(title, "hal2 · state 10")
        self.assertEqual(sections[0]["columns"], ["WT", "Plan", "Steps", "State", "Waits for"])
        self.assertEqual(sections[0]["rows"][0][0], "10")
        self.assertEqual(sections[0]["rows"][1][0], "↳ 31")
        self.assertEqual(sections[0]["marked"], [0])

    def test_titles(self):
        for r, checkout, want in (("steward", "main", "hal2 · steward"), ("farmer", "farmer-hal2", "hal2 · farmer"),
                                  ("unknown", "feature", "hal2 · state feature"), ("pope", "main", "hal2 · pope")):
            with mock.patch.object(steward_sources, "chores", return_value=None), \
                    mock.patch.object(steward_sources, "open_uats", return_value=None):  # the steward's readers, no tool
                self.assertEqual(views.build(r, {**self.DATA, "repo": "/x"}, {"repo": "hal2", "checkout": checkout})[0], want)

    def test_an_unregistered_role_gets_the_fallback(self):
        self.assertEqual(views.build("nobody", self.DATA, {"repo": "r", "checkout": "x"})[1][0]["heading"], "Worktrees")


if __name__ == "__main__":
    unittest.main()
