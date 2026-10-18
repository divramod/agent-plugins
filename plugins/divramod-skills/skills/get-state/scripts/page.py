"""The role's state page (hal2 plan 0366, D3-D5): one self-contained HTML file, written to the state dir, opened by
the system's browser. `render` is pure; every value is escaped by `html.escape`; the page loads nothing from the network.

A section is a dict with a `heading` and one body:
    {"columns": [...], "rows": [[...], ...], "marked": [<row index>, ...]}   a table, marked rows bold
    {"text": "..."}                                                          a paragraph
    {"items": ["...", ...]}                                                  a list
    {"empty": "..."}                                                         an empty-state line
A table without rows and a list without items show the section's `empty` line (default "Nothing here.").
A section may also carry `"bar": [done, total]`: a progress bar (CSS width, no script) above its body.
A section with `"kind": "grid"` is the interactive table component (`grid.py`, plan 0369 D2-D6): only a page with a
grid carries script, `table.css` and `table.js` inlined; every other page stays script-free.
"""

import html
import os
import re
import sys
import webbrowser
from pathlib import Path

import grid

CSS = """
:root { --bg: #ffffff; --fg: #1d1d1f; --muted: #6e6e73; --line: #d2d2d7; --head: #f5f5f7; --accent: #0a66c2; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #1c1c1e; --fg: #f5f5f7; --muted: #a1a1a6; --line: #3a3a3c; --head: #2c2c2e; --accent: #4ea1ff; }
}
* { box-sizing: border-box; }
body { margin: 0; padding: 24px 32px; background: var(--bg); color: var(--fg);
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
h1 { margin: 0 0 4px; font-size: 22px; border-bottom: 2px solid var(--accent); padding-bottom: 6px; }
h2 { margin: 28px 0 8px; font-size: 16px; color: var(--accent); }
.meta, .empty { color: var(--muted); }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; vertical-align: top; padding: 6px 10px; border-bottom: 1px solid var(--line); }
th { background: var(--head); font-weight: 600; }
tr.marked td { font-weight: 700; }
ul { margin: 0; padding-left: 20px; }
.bar { height: 10px; margin: 4px 0 8px; background: var(--head); border: 1px solid var(--line); border-radius: 5px; overflow: hidden; }
.bar span { display: block; height: 100%; background: var(--accent); }
""".strip()

EMPTY = "Nothing here."


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def table_html(section: dict) -> str:
    marked = set(section.get("marked") or ())
    head = "".join(f"<th>{esc(c)}</th>" for c in section.get("columns") or ())
    body = []
    for i, row in enumerate(section["rows"]):
        cls = ' class="marked"' if i in marked else ""
        body.append(f"<tr{cls}>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def bar_html(section: dict) -> str:
    """The progress bar of `bar: [done, total]`, empty when the section has none or its total is not positive."""
    try:
        done, total = section["bar"]
        pct = max(0, min(100, round(100 * int(done) / int(total))))
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return ""
    return f'<div class="bar"><span style="width:{pct}%"></span></div>'


def body_html(section: dict) -> str:
    """The section's bar, then its table, paragraph or list, else its empty-state line."""
    return bar_html(section) + main_html(section)


def main_html(section: dict) -> str:
    if section.get("rows"):
        return table_html(section)
    if section.get("items"):
        return "<ul>" + "".join(f"<li>{esc(i)}</li>" for i in section["items"]) + "</ul>"
    if section.get("text"):
        return f"<p>{esc(section['text'])}</p>"
    return f'<p class="empty">{esc(section.get("empty") or EMPTY)}</p>'


def render(title: str, sections: list[dict], meta: str = "") -> str:
    """One self-contained HTML document: the title, an optional line under it, the sections in order."""
    parts = [f"<h1>{esc(title)}</h1>"] + ([f'<p class="meta">{esc(meta)}</p>'] if meta else [])
    for s in sections:
        if s.get("kind") == "grid":
            parts.append(grid.grid_html(s))
        else:
            parts.append(f"<section><h2>{esc(s.get('heading') or '')}</h2>{body_html(s)}</section>")
    css, script = CSS, ""
    if any(s.get("kind") == "grid" for s in sections):
        table_css, table_js = grid.assets()
        css, script = CSS + "\n" + table_css, f"\n<script>\n{table_js}</script>"
    return ("<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{esc(title)}</title><style>{css}</style></head>\n<body>\n" + "\n".join(parts) + script
            + "\n</body></html>\n")


def state_dir() -> Path:
    """`%LOCALAPPDATA%\\hal2\\get-state` on Windows, else `${XDG_STATE_HOME:-~/.local/state}/hal2/get-state` (D4)."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    else:
        base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(base) / "hal2" / "get-state"


def page_name(repo: str, checkout: str, role: str) -> str:
    """`<repo>-<checkout>-<role>.html`, every character outside `A-Za-z0-9._` replaced by `-`."""
    return "-".join(re.sub(r"[^A-Za-z0-9._]+", "-", p).strip("-") or "x" for p in (repo, checkout, role)) + ".html"


def write(name: str, text: str) -> Path:
    """Writes the page into the state dir (created when missing) and returns its path."""
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / name
    path.write_text(text, encoding="utf-8")
    return path


def open_page(path: Path) -> bool:
    """Opens the page in the system's browser; False when that fails (never raises)."""
    try:
        return bool(webbrowser.open(Path(path).resolve().as_uri()))
    except Exception:  # noqa: BLE001  (no browser, a headless box: the printed path is enough)
        return False
