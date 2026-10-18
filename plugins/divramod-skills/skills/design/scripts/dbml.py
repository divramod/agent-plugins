"""The DBML subset an ERD design uses (hal2 plan 0364, D5) and the diff of `current.dbml` against `new.dbml`.

Read: `Table <name> [as <alias>] [settings] { <column> <type> [settings] ... }` (a column's type may hold spaces, as
`decimal(10, 2)`; `Note:` lines and `indexes { }` blocks are skipped), `Ref [name]: a.b > c.d` and the long form
`Ref [name] { a.b > c.d }`, and an inline `ref: > c.d` setting. `Enum`, `Project` and `TableGroup` are skipped.
Comments `//` and `/* */` are dropped.

A diff marks each table and column `added`, `removed`, `changed` or `same`, and each ref `added`, `removed` or `same`.
"""

import re

TABLE = re.compile(r'\bTable\s+("[^"]+"|[\w.]+)(?:\s+as\s+\w+)?\s*(?:\[[^\]]*\])?\s*\{', re.I)
REF = re.compile(r'\bRef\b[^:{\n]*[:{]\s*([\w."]+)\s*(<>|<|>|-)\s*([\w."]+)', re.I)
COLUMN = re.compile(r'^("[^"]+"|\S+)\s+(.+?)\s*(?:\[(.*)\])?\s*$')
INLINE_REF = re.compile(r'^ref\s*:\s*(<>|<|>|-)\s*([\w."]+)$', re.I)
BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
LINE_COMMENT = re.compile(r"//[^\n]*")


def _unquote(name: str) -> str:
    return name.strip().strip('"')


def _block(text: str, start: int) -> tuple[str, int]:
    """The text inside the brace opened just before `start`, and the index after its closing brace."""
    depth, i = 1, start
    while i < len(text) and depth:
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    return text[start:i - 1], i


def split_settings(raw: str) -> list[str]:
    """`pk, note: 'a, b'` -> ['pk', "note: 'a, b'"]: commas inside quotes stay."""
    parts, quote, current = [], "", ""
    for ch in raw:
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "'\"`":
            quote = ch
        elif ch == ",":
            parts.append(current.strip())
            current = ""
            continue
        current += ch
    if current.strip():
        parts.append(current.strip())
    return parts


def _body_lines(body: str) -> list[str]:
    """The column lines of a table body: `indexes { }` blocks and notes dropped."""
    lines, i = [], 0
    while i < len(body):
        nl = body.find("\n", i)
        end = nl if nl >= 0 else len(body)
        line = body[i:end].strip()
        if line.lower().startswith(("indexes", "note")) and "{" in line:
            _, i = _block(body, body.find("{", i) + 1)
            continue
        i = end + 1
        if line and not re.match(r"^note\s*:", line, re.I):
            lines.append(line)
    return lines


def _column(line: str, table: str, refs: list) -> dict | None:
    match = COLUMN.match(line)
    if not match:
        return None
    name, ctype, raw = _unquote(match.group(1)), match.group(2).strip(), match.group(3) or ""
    settings = []
    for setting in split_settings(raw):
        inline = INLINE_REF.match(setting)
        if inline:
            refs.append(_ref(f"{table}.{name}", inline.group(1), inline.group(2)))
        else:
            settings.append(setting)
    return {"name": name, "type": ctype, "settings": settings}


def _ref(left: str, op: str, right: str) -> dict:
    return {"from": ".".join(_unquote(p) for p in left.split(".")), "op": op,
            "to": ".".join(_unquote(p) for p in right.split("."))}


def parse(text: str) -> dict:
    """{"tables": {name: {"name", "columns": [{"name", "type", "settings"}]}}, "refs": [{"from", "op", "to"}]}"""
    text = LINE_COMMENT.sub("", BLOCK_COMMENT.sub("", text))
    tables, refs, pos, outside = {}, [], 0, []
    while True:
        match = TABLE.search(text, pos)
        if not match:
            break
        outside.append(text[pos:match.start()])
        name = _unquote(match.group(1))
        body, pos = _block(text, match.end())
        columns = [c for c in (_column(l, name, refs) for l in _body_lines(body)) if c]
        tables[name] = {"name": name, "columns": columns}
    outside.append(text[pos:])
    refs += [_ref(*m.groups()) for m in REF.finditer("\n".join(outside))]
    return {"tables": tables, "refs": refs}


def _column_status(old: dict | None, new: dict | None) -> str:
    if old is None:
        return "added"
    if new is None:
        return "removed"
    same = old["type"] == new["type"] and sorted(old["settings"]) == sorted(new["settings"])
    return "same" if same else "changed"


def _table_diff(old: dict | None, new: dict | None) -> dict:
    old_cols = {c["name"]: c for c in (old or {}).get("columns", [])}
    new_cols = {c["name"]: c for c in (new or {}).get("columns", [])}
    names = list(new_cols) + [n for n in old_cols if n not in new_cols]
    columns = []
    for name in names:
        before, after = old_cols.get(name), new_cols.get(name)
        status = _column_status(before, after)
        columns.append({"name": name, "status": status, "type": (after or before)["type"],
                        "old_type": before["type"] if status == "changed" and before["type"] != after["type"] else "",
                        "settings": (after or before)["settings"]})
    if old is None or new is None:
        status = "added" if old is None else "removed"
    else:
        status = "same" if all(c["status"] == "same" for c in columns) else "changed"
    return {"name": (new or old)["name"], "status": status, "columns": columns}


def _ref_key(ref: dict) -> tuple:
    return (ref["from"], ref["op"], ref["to"])


def diff(old: dict, new: dict) -> dict:
    """Tables in the new order, removed ones last; refs with their status. A table whose refs changed is `changed`."""
    names = list(new["tables"]) + [n for n in old["tables"] if n not in new["tables"]]
    tables = [_table_diff(old["tables"].get(n), new["tables"].get(n)) for n in names]
    old_refs, new_refs = {_ref_key(r) for r in old["refs"]}, {_ref_key(r) for r in new["refs"]}
    refs = [{**r, "status": "same" if _ref_key(r) in old_refs else "added"} for r in new["refs"]]
    refs += [{**r, "status": "removed"} for r in old["refs"] if _ref_key(r) not in new_refs]
    touched = {r["from"].rsplit(".", 1)[0] for r in refs if r["status"] != "same"}
    for table in tables:
        if table["status"] == "same" and table["name"] in touched:
            table["status"] = "changed"
    return {"tables": tables, "refs": refs}


def plain(model: dict) -> dict:
    """One schema without a counterpart, in the diff's shape, everything `same`."""
    return diff(model, model)
