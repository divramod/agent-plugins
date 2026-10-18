"""An ERD design drawn as HTML entity cards (hal2 plan 0364, D5): one card per table, its columns as rows, coloured
by the diff of `current.dbml` against `new.dbml` (green added, yellow changed, red removed) with a legend, and the
relations listed under the cards. The page's CSS styles the classes `erd-*` and `st-*`.
"""

from html import escape

import dbml

LEGEND = (("added", "added"), ("changed", "changed"), ("removed", "removed"))
OPS = {">": "many-to-one", "<": "one-to-many", "-": "one-to-one", "<>": "many-to-many"}


def _column_row(column: dict) -> str:
    kind = escape(column["type"])
    if column["old_type"]:
        kind = f'<s>{escape(column["old_type"])}</s> &rarr; {kind}'
    settings = escape(", ".join(column["settings"]))
    extra = f'<span class="erd-set">[{settings}]</span>' if settings else ""
    return (f'<tr class="st-{column["status"]}"><td class="erd-col">{escape(column["name"])}</td>'
            f'<td class="erd-type">{kind}{extra}</td></tr>')


def card(table: dict) -> str:
    rows = "".join(_column_row(c) for c in table["columns"])
    return (f'<div class="erd-card st-{table["status"]}" data-table="{escape(table["name"])}">'
            f'<div class="erd-head">{escape(table["name"])}</div><table>{rows}</table></div>')


def _ref_line(ref: dict) -> str:
    label = OPS.get(ref["op"], ref["op"])
    return (f'<li class="st-{ref["status"]}"><code>{escape(ref["from"])} {escape(ref["op"])} '
            f'{escape(ref["to"])}</code> <span class="erd-set">{label}</span></li>')


def legend() -> str:
    items = "".join(f'<span class="erd-key st-{cls}">{label}</span>' for cls, label in LEGEND)
    return f'<div class="erd-legend">{items}</div>'


def draw(model: dict, with_legend: bool) -> str:
    """The cards and relations of a diff model (dbml.diff or dbml.plain)."""
    cards = "".join(card(t) for t in model["tables"])
    refs = "".join(_ref_line(r) for r in model["refs"])
    relations = f'<ul class="erd-refs">{refs}</ul>' if refs else ""
    head = legend() if with_legend else ""
    return f'<div class="erd">{head}<div class="erd-cards">{cards}</div>{relations}</div>'


def diff_html(current: str, new: str) -> str:
    """`new.dbml` against `current.dbml`: removed tables, columns and refs stay visible in red."""
    return draw(dbml.diff(dbml.parse(current), dbml.parse(new)), with_legend=True)


def plain_html(text: str) -> str:
    return draw(dbml.plain(dbml.parse(text)), with_legend=False)
