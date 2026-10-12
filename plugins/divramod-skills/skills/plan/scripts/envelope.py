"""The envelope of a record (a plan, its two ledgers, its handoff): restricted YAML front matter, and the body's
headings and links. The format is hal2's decision record `record-formats`; hal2-records reads the same subset in Rust.

The subset is its rule 2: `key: scalar`, `key: "quoted"`, `key: >-` with indented lines,
`key: [a, b]`, `key: {a: 1}` (one level), `# comments`. Anything else is a FormatError.
"""

import re

KEY = re.compile(r"^([a-z][a-z0-9_]*):(?:[ \t]+(.*))?$")
FENCE = re.compile(r"^(```|~~~)")
LINK = re.compile(r"\]\(([^)\s]+)\)")


class FormatError(ValueError):
    pass


def split(text: str) -> tuple[str | None, str]:
    """The front matter's text (None when the file has none) and the body."""
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 3)
    if end < 0:
        raise FormatError("front matter is not closed with `---`")
    return text[4:end + 1], text[end + 5:]


def strip_comment(value: str) -> str:
    """The value without a trailing ` # comment` (a `#` inside quotes stays)."""
    quote = ""
    for i, ch in enumerate(value):
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or value[i - 1] in " \t"):
            return value[:i].rstrip()
    return value.rstrip()


def scalar(value: str):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if value[:1] in "[{&*!|>@`" or value.startswith("- "):
        raise FormatError(f"not a plain scalar: {value}")
    return value


def items(inner: str) -> list[str]:
    """The comma-separated items of an inline list or map; commas inside quotes do not split."""
    out, cur, quote = [], "", ""
    for ch in inner:
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch == ",":
            out.append(cur)
            cur = ""
            continue
        cur += ch
    return [i for i in out + [cur] if i.strip()]


def value_of(raw: str):
    if raw.startswith("[") and raw.endswith("]"):
        return [scalar(i) for i in items(raw[1:-1])]
    if raw.startswith("{") and raw.endswith("}"):
        pairs = [i.split(":", 1) for i in items(raw[1:-1])]
        if any(len(p) != 2 for p in pairs):
            raise FormatError(f"not an inline map: {raw}")
        return {k.strip(): scalar(v) for k, v in pairs}
    return scalar(raw)


def parse(front: str) -> dict:
    """The front matter as a dict, keys in file order. An empty value is None."""
    data: dict = {}
    lines = front.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = KEY.match(line)
        if not m:
            raise FormatError(f"not `key: value`: {line.strip()}")
        key, raw = m.group(1), strip_comment(m.group(2) or "")
        if key in data:
            raise FormatError(f"key used twice: {key}")
        if raw == ">-":
            folded = []
            while i < len(lines) and (lines[i].startswith("  ") or not lines[i].strip()):
                folded.append(lines[i].strip())
                i += 1
            data[key] = " ".join(f for f in folded if f)
        else:
            data[key] = value_of(raw) if raw else None
    return data


def prose(body: str) -> list[str]:
    """The body's lines outside fenced code blocks."""
    out, fenced = [], False
    for line in body.split("\n"):
        if FENCE.match(line.strip()):
            fenced = not fenced
        elif not fenced:
            out.append(line)
    return out


def headings(body: str, level: int) -> list[str]:
    mark = "#" * level + " "
    return [line[len(mark):].strip() for line in prose(body) if line.startswith(mark)]


def section(body: str, title: str) -> str:
    """The text of the `## <title>` section, without its heading."""
    out, inside = [], False
    for line in prose(body):
        if line.startswith("## "):
            inside = line[3:].strip() == title
        elif inside:
            out.append(line)
    return "\n".join(out)


def entries(body: str) -> list[tuple[str, str]]:
    """Every `## ` heading with the text below it: a ledger's entries."""
    parts = re.split(r"^## (.*)$", "\n".join(prose(body)), flags=re.M)
    return list(zip(parts[1::2], parts[2::2]))


def field(text: str, name: str) -> str:
    """The text of a `**<name>:**` line and the lines that continue it."""
    m = re.search(rf"^\*\*{name}:\*\*[ \t]*(.*?)(?=^\*\*[A-Za-z]+:\*\*|\Z)", text, re.M | re.S)
    return " ".join(m.group(1).split()) if m else ""


def links(body: str) -> list[str]:
    """The relative link targets of the body, without anchors; code spans and fences do not count."""
    out = []
    for line in prose(body):
        for target in LINK.findall(re.sub(r"`[^`]*`", "", line)):
            path = target.split("#", 1)[0]
            if path and not re.match(r"^[a-z][a-z0-9+.-]*:", path):
                out.append(path)
    return out


def quote(value: str) -> str:
    """`value` as a quoted scalar on one line. The subset knows no escapes: a text holding both kinds of quote loses
    its double ones."""
    value = " ".join(str(value).split())
    if '"' not in value:
        return f'"{value}"'
    return f"'{value}'" if "'" not in value else '"' + value.replace('"', "'") + '"'


def get(text: str, key: str):
    """One key of a file's front matter; None when the file has none, or not this key."""
    front, _ = split(text)
    return parse(front).get(key) if front is not None else None


def set_key(text: str, key: str, raw: str | None) -> str:
    """The file's text with the front matter line `key: raw` set (appended when missing); `raw` None removes it."""
    front, body = split(text)
    if front is None:
        raise FormatError("the file has no front matter")
    lines, out, done = front.rstrip("\n").split("\n"), [], False
    for line in lines:
        m = KEY.match(line)
        if m and m.group(1) == key:
            done = True
            if raw is not None:
                out.append(f"{key}: {raw}")
        else:
            out.append(line)
    if not done and raw is not None:
        out.append(f"{key}: {raw}")
    return "---\n" + "\n".join(out) + "\n---\n" + body
