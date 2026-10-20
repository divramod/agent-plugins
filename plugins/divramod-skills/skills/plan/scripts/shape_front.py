"""The front matter of the plan shape's files (hal2 plan 0376, design A1), the Python twin of hal2-core's
`plan_shape::front`: `Fields` takes a typed document's keys off its parsed envelope one by one (what is left are the
unknown keys, kept), `Writer` writes the canonical front matter back: the keys in the kind's order, `title` and
`description` quoted, other text plain where the envelope reads it back unchanged, the unknown keys last in file
order. Both are held byte-equal to the Rust ones on the golden fixture (test_shape.py).
"""
from __future__ import annotations

import re

import envelope
from shape_names import ShapeError

PLAIN_STARTS = tuple("[{&*!|>@`\"'#%")
WORD = re.compile(r"[A-Za-z0-9_./@-]+")


class Fields:
    """The keys of one front matter, taken one by one."""

    def __init__(self, file: str, rest: list[tuple[str, object]]):
        self.file = file
        self.rest = rest

    @classmethod
    def read(cls, file: str, text: str, kind: str) -> tuple["Fields", str]:
        """The front matter and body of `text`, which must be of `kind` (its `type`) with `schema: 1`."""
        try:
            front, body = envelope.split(text)
            if front is None:
                raise ShapeError(f"{file}: no front matter")
            meta = envelope.parse(front)
        except envelope.FormatError as error:
            raise ShapeError(f"{file}: {error}") from error
        fields = cls(file, list(meta.items()))
        found = fields.required("type")
        if found != kind:
            raise fields.error(f"is a `{found}`, not a `{kind}`")
        if fields.number("schema") != 1:
            raise fields.error("needs `schema: 1`")
        return fields, body

    def error(self, why: str) -> ShapeError:
        return ShapeError(f"{self.file}: {why}")

    def take(self, key: str):
        for i, (k, _) in enumerate(self.rest):
            if k == key:
                return self.rest.pop(i)[1]
        return None

    def text(self, key: str) -> str | None:
        """The scalar at `key` as text; None when missing or empty."""
        value = self.take(key)
        if value is None:
            return None
        if isinstance(value, (list, dict)):
            raise self.error(f"`{key}` must be one value")
        return str(value)

    def required(self, key: str) -> str:
        value = self.text(key)
        if value is None:
            raise self.error(f"needs `{key}`")
        return value

    def number(self, key: str) -> int | None:
        value = self.text(key)
        if value is None:
            return None
        if not re.fullmatch(r"[0-9]+", value):
            raise self.error(f"`{key}` must be a number, not `{value}`")
        return int(value)

    def parsed(self, key: str, parse) -> str | None:
        """The text at `key` checked by `parse` (raising ShapeError); None when missing."""
        value = self.text(key)
        if value is None:
            return None
        try:
            return parse(value)
        except ShapeError as error:
            raise self.error(str(error)) from error

    def list(self, key: str) -> list[str]:
        value = self.take(key)
        if value is None:
            return []
        if not isinstance(value, list):
            raise self.error(f"`{key}` must be a list `[a, b]`")
        return [str(item) for item in value]


def quote(text: str) -> str:
    mark = "'" if '"' in text else '"'
    return f"{mark}{text}{mark}"


def plain(text: str) -> bool:
    """Whether the envelope reads `text` back as the same plain text."""
    digits = text[1:] if text.startswith("-") else text
    return (bool(text) and text.strip() == text and not text.startswith(PLAIN_STARTS)
            and not text.startswith("- ") and ": " not in text and " #" not in text and not text.endswith(":")
            and not re.fullmatch(r"[0-9]*", digits))


def scalar(text: str) -> str:
    return text if plain(text) else quote(text)


def item(text: str) -> str:
    return text if WORD.fullmatch(text) and not text.startswith("@") else quote(text)


def inline_list(items: list[str]) -> str:
    return "[" + ", ".join(item(str(i)) for i in items) + "]"


def inline_map(pairs: dict) -> str:
    return "{" + ", ".join(f"{k}: {item(str(v))}" for k, v in pairs.items()) + "}"


class Writer:
    """The canonical front matter, built key by key."""

    def __init__(self, kind: str):
        self.out = f"---\ntype: {kind}\nschema: 1\n"

    def line(self, key: str, value: str) -> "Writer":
        self.out += f"{key}: {value}\n"
        return self

    def quoted(self, key: str, text: str) -> "Writer":
        return self.line(key, quote(text))

    def text(self, key: str, text: str) -> "Writer":
        return self.line(key, scalar(text))

    def number(self, key: str, n: int) -> "Writer":
        return self.line(key, str(n))

    def some_number(self, key: str, n: int | None) -> "Writer":
        return self if n is None else self.number(key, n)

    def some(self, key: str, text: str | None) -> "Writer":
        return self if text is None else self.text(key, text)

    def list(self, key: str, items: list[str]) -> "Writer":
        return self.line(key, inline_list(items)) if items else self

    def rest(self, rest: list[tuple[str, object]]) -> "Writer":
        """The unknown keys, as read."""
        for key, value in rest:
            if value is None:
                self.out += f"{key}:\n"
            elif isinstance(value, int):
                self.line(key, str(value))
            elif isinstance(value, list):
                self.line(key, inline_list(value))
            elif isinstance(value, dict):
                self.line(key, inline_map(value))
            else:
                self.line(key, scalar(str(value)))
        return self

    def finish(self, body: str) -> str:
        return self.out + "---\n" + body
