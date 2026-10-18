"""table.js's pure functions under plain node (hal2 plan 0369 step 2): no npm package, skipped without node."""

import base64
import glob
import gzip
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TABLE_JS = HERE / "table.js"


def find_node() -> str | None:
    """`node` on PATH, else the newest nvm, Homebrew or /usr/local install; None when there is none."""
    found = shutil.which("node")
    if found:
        return found
    nvm = os.environ.get("NVM_DIR") or os.path.expanduser("~/.nvm")
    def version(p: str) -> tuple:
        v = Path(p).parent.parent.name.lstrip("v").split(".")
        return tuple(int(x) for x in v if x.isdigit())
    candidates = sorted(glob.glob(os.path.join(nvm, "versions/node/*/bin/node")), key=version, reverse=True)
    candidates += ["/opt/homebrew/bin/node", "/usr/local/bin/node", "/usr/bin/node"]
    return next((c for c in candidates if os.access(c, os.X_OK)), None)


NODE = find_node()

SECTION = {
    "id": "fields",
    "columns": [{"key": "field", "label": "Field"}, {"key": "done", "label": "Done %", "type": "num", "hidden": True},
                {"key": "plan", "label": "Plan"}],
    "rows": [{"field": "07", "done": 40, "plan": "a <b>"}, {"field": "10", "done": 100, "plan": "b", "_marked": True},
             {"field": "03", "done": None, "plan": "c"}, {"field": "12", "done": 75, "plan": "d"}],
    "filters": [{"key": "done", "label": "Done", "match": {"done": [100]}},
                {"key": "rest", "label": "The rest", "match": {"done": [40, 75]}}, {"key": "all", "label": "All", "match": None}],
    "sort": {"key": "done", "dir": "desc"},
}


@unittest.skipUnless(NODE, "node is not installed")
class TableJs(unittest.TestCase):
    def js(self, expr: str):
        """Evaluates `expr` with `T` = table.js's exports and `S` = SECTION; returns its JSON value."""
        script = (f"const T = require({json.dumps(str(TABLE_JS))});\nconst S = {json.dumps(SECTION)};\n"
                  f"process.stdout.write(JSON.stringify(({expr})));\n")
        out = subprocess.run([NODE, "-"], input=script, capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_loads_without_a_document(self):
        self.assertEqual(self.js("typeof T.merge + typeof T.tableHtml"), "functionfunction")

    def test_sort_numbers_empties_last_both_ways(self):
        self.assertEqual(self.js("T.sortRows(S.rows, {key: 'done', dir: 'asc'}, S.columns).map(r => r.field)"),
                         ["07", "12", "10", "03"])
        self.assertEqual(self.js("T.sortRows(S.rows, {key: 'done', dir: 'desc'}, S.columns).map(r => r.field)"),
                         ["10", "12", "07", "03"])
        self.assertEqual(self.js("T.sortRows(S.rows, null, S.columns).map(r => r.field)"), ["07", "10", "03", "12"])

    def test_sort_text_natural_and_case_folded(self):
        rows = "[{t: 'wt 10'}, {t: ''}, {t: 'wt 9'}, {t: 'WT 2'}]"
        self.assertEqual(self.js(f"T.sortRows({rows}, {{key: 't', dir: 'asc'}}, []).map(r => r.t)"),
                         ["WT 2", "wt 9", "wt 10", ""])

    def test_sort_cycles_asc_desc_none(self):
        self.assertEqual(self.js("[T.cycleSort(null, 'a'), T.cycleSort({key: 'a', dir: 'asc'}, 'a'),"
                                 " T.cycleSort({key: 'a', dir: 'desc'}, 'a'), T.cycleSort({key: 'b', dir: 'desc'}, 'a')]"),
                         [{"key": "a", "dir": "asc"}, {"key": "a", "dir": "desc"}, None, {"key": "a", "dir": "asc"}])

    def test_filters_match_and_count(self):
        self.assertEqual(self.js("T.filterRows(S.rows, S.filters, 'rest').map(r => r.field)"), ["07", "12"])
        self.assertEqual(self.js("T.filterRows(S.rows, S.filters, 'all').length"), 4)
        self.assertEqual(self.js("T.counts(S.rows, S.filters)"), {"done": 1, "rest": 2, "all": 4})
        self.assertEqual(self.js("T.defaultFilter(S)"), "all")
        self.assertEqual(self.js("T.defaultFilter({...S, filter: 'done'})"), "done")

    def test_defaults_come_from_the_section(self):
        self.assertEqual(self.js("T.defaults(S)"), {"order": ["field", "done", "plan"], "hidden": ["done"],
                                                    "sort": {"key": "done", "dir": "desc"}, "filter": "all", "widths": {}})

    def test_merge_keeps_saved_and_handles_columns_that_came_or_went(self):
        saved = ("{order: ['plan', 'gone', 'field'], hidden: ['plan'], sort: {key: 'gone', dir: 'asc'},"
                 " filter: 'nope', widths: {field: 120.4, gone: 50, plan: -1}}")
        self.assertEqual(self.js(f"T.merge(S, {saved})"), {
            "order": ["plan", "field", "done"], "hidden": ["done", "plan"],  # done is new: its default place and hidden
            "sort": {"key": "done", "dir": "desc"}, "filter": "all", "widths": {"field": 120}})
        self.assertEqual(self.js("T.merge(S, {order: ['done', 'field', 'plan'], hidden: [], sort: null, filter: 'rest'})"),
                         {"order": ["done", "field", "plan"], "hidden": [], "sort": None, "filter": "rest", "widths": {}})
        self.assertEqual(self.js("T.merge(S, null)"), self.js("T.defaults(S)"))

    def test_move_and_drop_reorder(self):
        self.assertEqual(self.js("T.moveKey(['a', 'b', 'c'], 'b', -1)"), ["b", "a", "c"])
        self.assertEqual(self.js("T.moveKey(['a', 'b', 'c'], 'c', 1)"), ["a", "b", "c"])
        self.assertEqual(self.js("T.dropKey(['a', 'b', 'c'], 'a', 'c')"), ["b", "c", "a"])
        self.assertEqual(self.js("T.dropKey(['a', 'b', 'c'], 'c', 'a')"), ["c", "a", "b"])
        self.assertEqual(self.js("T.dropKey(['a', 'b'], 'x', 'a')"), ["a", "b"])

    def test_menu_actions(self):
        state = "T.defaults(S)"
        self.assertEqual(self.js(f"T.act({state}, 'toggle', 'done').hidden"), [])
        self.assertEqual(self.js(f"T.act({state}, 'toggle', 'plan').hidden"), ["done", "plan"])
        self.assertEqual(self.js(f"T.act({state}, 'down', 'field').order"), ["done", "field", "plan"])
        self.assertIsNone(self.js(f"T.act({state}, 'sort', '').sort"))
        self.assertEqual(self.js(f"T.act({state}, 'sort', 'plan').sort"), {"key": "plan", "dir": "asc"})
        self.assertEqual(self.js(f"T.act({state}, 'asc', '').sort"), {"key": "done", "dir": "asc"})
        self.assertEqual(self.js(f"T.act({{...{state}, widths: {{field: 90}}}}, 'fit', '').widths"), {})

    def test_table_html_escapes_wraps_marks_and_matches_the_static_table(self):
        import grid
        html = self.js("T.tableHtml(S, T.defaults(S))")
        self.assertEqual(html, grid.table_html(SECTION))
        self.assertIn("a &lt;b&gt;", html)
        self.assertIn('<tr class="marked"><td>10</td>', html)
        self.assertNotIn('data-key="done"', html)
        self.assertIn('style="width:90px"', self.js("T.tableHtml(S, {...T.defaults(S), widths: {field: 90}})"))
        self.assertEqual(self.js("T.tableHtml({...S, rows: [], empty: 'None <yet>'}, T.defaults(S))"),
                         '<p class="empty">None &lt;yet&gt;</p>')

    def test_menu_and_filters_html(self):
        menu = self.js("T.menuHtml(S, T.defaults(S))")
        for label in ("Columns", "Sort", "Unsorted", "Ascending", "Fit widths", "Reset", "Done %"):
            self.assertIn(label, menu)
        self.assertIn('data-act="up" data-key="field" disabled', menu)
        self.assertIn('data-act="down" data-key="plan" disabled', menu)
        filters = self.js("T.filtersHtml(S, T.defaults(S))")
        self.assertIn('class="grid-filter on" data-filter="all">All <span class="count">4</span>', filters)
        self.assertEqual(self.js("T.filtersHtml({...S, filters: []}, T.defaults(S))"), "")

    def test_read_island_plain_and_packed(self):
        packed = base64.b64encode(gzip.compress(json.dumps(SECTION).encode(), mtime=0)).decode()
        script = (f"const T = require({json.dumps(str(TABLE_JS))});\n"
                  f"Promise.all([T.readIsland({{type: 'application/json', textContent: {json.dumps(json.dumps(SECTION))}}}),"
                  f" T.readIsland({{type: 'application/gzip+base64', textContent: {json.dumps(packed + chr(10))}}})])"
                  ".then((v) => process.stdout.write(JSON.stringify(v)));\n")
        out = subprocess.run([NODE, "-"], input=script, capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), [SECTION, SECTION])


class Source(unittest.TestCase):
    def test_inlinable_and_small(self):
        src = TABLE_JS.read_text(encoding="utf-8")
        self.assertNotIn("</script", src.lower())
        self.assertNotIn("<!--", src)
        self.assertNotRegex(src, r"https?://|import\(")
        for name in ("table.js", "table.css", "grid.py"):
            lines = (HERE / name).read_text(encoding="utf-8").splitlines()
            code = [l for l in lines if l.strip() and not l.strip().startswith(("//", "#", "/*"))]
            self.assertLess(len(code), 300, name)


if __name__ == "__main__":
    unittest.main()
