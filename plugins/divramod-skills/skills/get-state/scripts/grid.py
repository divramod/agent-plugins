"""The page's `grid` section (hal2 plan 0369, D2-D6, D10): one interactive table component for every table that needs
sorting, a column menu, filters and refresh. `page.py` calls `grid_html` for a section with `"kind": "grid"`:

    {"kind": "grid", "id": "<table id>", "heading": "...", "note": "<a line above the table>",
     "columns": [{"key": "...", "label": "...", "type": "text|num", "hidden": bool}, ...],
     "rows": [{"<key>": <value>, ..., "_marked": bool}, ...],
     "filters": [{"key": "...", "label": "...", "match": {"<column key>": [<value>, ...]} | null}, ...],
     "filter": "<default filter key>", "sort": {"key": "...", "dir": "asc|desc"}, "empty": "..."}

A filter whose `match` is null shows every row (All); the default filter is `filter`, else the first All filter. The
static table below is what a page without script shows: the default filter and sort applied, hidden columns left out,
the same markup `table.js` renders; the section's JSON travels beside it as an island `table.js` reads. A big table
keeps the page small (plan 0369 D14): `"static": false` leaves its static rows out (a line says it needs script), and
an island over `PACK_OVER` bytes travels gzipped in base64 (`application/gzip+base64`), which `table.js` unpacks.
"""

import base64
import gzip
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
EMPTY = "Nothing here."
PACK_OVER = 32 * 1024  # an island bigger than this (JSON bytes) is packed
NEEDS_SCRIPT = "This table is shown by the page's script; open the page in a browser with JavaScript on."
_NUM = re.compile(r"^\s*-?\d+(?:\.\d+)?")


def esc(value: object) -> str:
    """HTML-escapes like `table.js`'s `esc` (`&`, `<`, `>`, `"`, `'`), so both render the same markup."""
    s = "" if value is None else str(value)
    for a, b in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&quot;"), ("'", "&#x27;")):
        s = s.replace(a, b)
    return s


def island(section: dict) -> str:
    """The section as JSON safe inside a <script> element: no `<` can close it."""
    return json.dumps(section, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def island_html(section: dict) -> str:
    """The island's <script> element: plain JSON, or over `PACK_OVER` bytes gzip (mtime 0, so the same data gives
    the same page) in base64, whose alphabet cannot close the element."""
    text = island(section)
    if len(text.encode()) <= PACK_OVER:
        return f'<script type="application/json" class="grid-data">{text}</script>'
    packed = base64.b64encode(gzip.compress(text.encode(), 9, mtime=0)).decode()
    return f'<script type="application/gzip+base64" class="grid-data">{packed}</script>'


def default_filter(section: dict):
    """`filter` when it names a filter, else the first filter without a match (All), else None."""
    filters = section.get("filters") or []
    keys = [f.get("key") for f in filters if isinstance(f, dict)]
    if section.get("filter") in keys:
        return section["filter"]
    return next((f.get("key") for f in filters if isinstance(f, dict) and not f.get("match")), None)


def matches(row: dict, flt: dict | None) -> bool:
    """A row matches a filter when every matched column's value is one of the filter's values (compared as text)."""
    match = (flt or {}).get("match") or {}
    return all(_text(row.get(k)) in [_text(v) for v in (vals or [])] for k, vals in match.items())


def _text(v: object) -> str:
    return "" if v is None else str(v)


def _empty(v: object) -> bool:
    return v is None or v == ""


def _key(v: object, kind: str):
    """Numbers numeric (a value without a leading number after every number), text in natural order, case folded."""
    if kind == "num":
        m = _NUM.match(str(v))
        return (0, float(m.group()), "") if m else (1, 0.0, str(v).casefold())
    return [(0, int(p), "") if p.isdecimal() else (1, 0, p) for p in re.split(r"(\d+)", str(v).casefold()) if p]


def sort_rows(rows: list[dict], sort: dict | None, columns: list[dict]) -> list[dict]:
    """Rows sorted by `sort` ({"key", "dir"}), stable, empty values last in both directions; no sort keeps the order."""
    key = (sort or {}).get("key")
    if not key:
        return list(rows)
    kind = next((c.get("type") for c in columns if c.get("key") == key), "text")
    full = [r for r in rows if not _empty(r.get(key))]
    full.sort(key=lambda r: _key(r.get(key), kind), reverse=(sort or {}).get("dir") == "desc")
    return full + [r for r in rows if _empty(r.get(key))]


def view(section: dict) -> tuple[list[dict], list[dict]]:
    """The static table's visible columns and rows: default filter, default sort, hidden columns out."""
    columns = [c for c in section.get("columns") or [] if isinstance(c, dict) and c.get("key")]
    fkey = default_filter(section)
    flt = next((f for f in section.get("filters") or [] if isinstance(f, dict) and f.get("key") == fkey), None)
    rows = [r for r in section.get("rows") or [] if isinstance(r, dict) and matches(r, flt)]
    return [c for c in columns if not c.get("hidden")], sort_rows(rows, section.get("sort"), columns)


def table_html(section: dict) -> str:
    """The static table, the same markup as `table.js`'s `tableHtml` without settings."""
    cols, rows = view(section)
    if not rows:
        return f'<p class="empty">{esc(section.get("empty") or EMPTY)}</p>'
    sort = section.get("sort") or {}
    head = []
    for c in cols:
        on = c["key"] == sort.get("key")
        aria = ("descending" if sort.get("dir") == "desc" else "ascending") if on else "none"
        arrow = ("↓" if sort.get("dir") == "desc" else "↑") if on else ""
        head.append(f'<th data-key="{esc(c["key"])}" draggable="true" aria-sort="{aria}">'
                    f'{esc(c.get("label", c["key"]))}<span class="arrow">{arrow}</span><span class="grip"></span></th>')
    body = []
    for r in rows:
        cls = ' class="marked"' if r.get("_marked") else ""
        body.append(f"<tr{cls}>" + "".join(f"<td>{esc(r.get(c['key']))}</td>" for c in cols) + "</tr>")
    return f'<table class="grid-table"><thead><tr>{"".join(head)}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def grid_html(section: dict) -> str:
    """The whole grid section: head with an empty tools box, note, filters box, static table, JSON island."""
    gid = esc(section.get("id") or "")
    note = f'<p class="grid-note">{esc(section["note"])}</p>' if section.get("note") else ""
    body = table_html(section) if section.get("static", True) else f'<p class="empty">{esc(NEEDS_SCRIPT)}</p>'
    return (f'<section class="grid" data-grid="{gid}"><div class="grid-head"><h2>{esc(section.get("heading") or "")}</h2>'
            f'<div class="grid-tools"></div></div>{note}<div class="grid-filters"></div>'
            f'<div class="grid-body">{body}</div>{island_html(section)}</section>')


def assets() -> tuple[str, str]:
    """`table.css` and `table.js`, read beside this file, for `page.py` to inline."""
    return (HERE / "table.css").read_text(encoding="utf-8"), (HERE / "table.js").read_text(encoding="utf-8")
