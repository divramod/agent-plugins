"""watches.yaml: the stdlib reader and writer of the YAML subset PyYAML's safe_dump writes, and the cron due check.

The file is `watches:` with a list of flat mappings (jobsearch's `daily/watches.yaml`). Block scalars, flow
collections, anchors, tags and nested maps are refused (YamlError with the line number), never guessed.
"""
import datetime as dt
import re

HEADER = ["# Watches of the daybook: checks an agent session repeats (CronCreate) until `until` holds.",
          "# A session's cron jobs end with the session, so the daybook skill sets every active one up again."]
REFUSED = tuple("|>[{&*!%@`")
KEY_RE = re.compile(r"^(- |  )([A-Za-z_][A-Za-z0-9_]*):(?: (.*))?$")
INT_RE = re.compile(r"^[-+]?(0|[1-9][0-9]*)$")
ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "/": "/", " ": " ", "0": "\0", "r": "\r", "b": "\b"}
# What PyYAML would read as something other than the same string (YAML 1.1 resolvers): those values get quoted.
SPECIAL_RE = re.compile(r"^(?:[-+]?[0-9][0-9_]*(?:\.[0-9_]*)?(?:[eE][-+]?[0-9]+)?|[-+]?\.[0-9_]+|0x[0-9a-fA-F_]+|"
                        r"0b[01_]+|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN)|[0-9]+(?::[0-5]?[0-9])+(?:\.[0-9_]*)?|"
                        r"yes|Yes|YES|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF|y|Y|n|N|"
                        r"null|Null|NULL|~|=|<<|[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}(?:[Tt ].*)?)$")


class YamlError(ValueError):
    pass


def fold(parts, keep_escaped_breaks=False):
    """Join a multi-line scalar's lines: a break is a space, an empty line a newline (`\\` at the end joins)."""
    out = parts[0]
    pending = 0
    for part in parts[1:]:
        if not part:
            pending += 1
            continue
        if keep_escaped_breaks and re.search(r"(?<!\\)(\\\\)*\\$", out):
            out = out[:-1] + part
        else:
            out += ("\n" * pending if pending else " ") + part
        pending = 0
    return out


def unescape(body, lineno):
    def repl(m):
        code = m.group(1)
        if code in ESCAPES:
            return ESCAPES[code]
        if code[0] in "xuU":
            return chr(int(code[1:], 16))
        raise YamlError(f"line {lineno}: unknown escape \\{code}")
    return re.sub(r"\\(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|.)", repl, body)


def scalar(parts, lineno):
    """One value from its lines (first line's text after `key:`, then the continuation lines, stripped)."""
    text = parts[0]
    if text.startswith("'"):
        whole = fold(parts)
        m = re.fullmatch(r"'((?:[^']|'')*)'", whole, re.S)
        if not m:
            raise YamlError(f"line {lineno}: unterminated single-quoted value")
        return m.group(1).replace("''", "'")
    if text.startswith('"'):
        whole = fold(parts, keep_escaped_breaks=True)
        m = re.fullmatch(r'"((?:[^"\\]|\\.)*)"', whole, re.S)
        if not m:
            raise YamlError(f"line {lineno}: unterminated double-quoted value")
        return unescape(m.group(1), lineno)
    if text.startswith(REFUSED) or text == "-" or text.startswith("- "):
        raise YamlError(f"line {lineno}: unsupported YAML ({text[:20]!r}); write it as PyYAML's safe_dump would")
    plain = re.sub(r"\s+#.*$", "", fold(parts)).strip()
    if any(p.startswith("- ") or re.match(r"^[A-Za-z_][\w]*:( |$)", p) for p in parts[1:]) or ": " in plain:
        raise YamlError(f"line {lineno}: nested mappings and lists are not supported")
    if plain in ("true", "True", "TRUE"):
        return True
    if plain in ("false", "False", "FALSE"):
        return False
    if plain in ("", "null", "Null", "NULL", "~"):
        return None
    if INT_RE.match(plain):
        return int(plain)
    return plain


def parse(text):
    """Text -> (leading comment lines, [watch dict, ...])."""
    lines = text.splitlines()
    comments, i = [], 0
    while i < len(lines) and (lines[i].startswith("#") or not lines[i].strip()):
        if lines[i].startswith("#"):
            comments.append(lines[i])
        i += 1
    if i == len(lines):
        return comments, []
    top = re.sub(r"\s+#.*$", "", lines[i]).rstrip()
    if top == "watches: []":
        return comments, []
    if top != "watches:":
        raise YamlError(f"line {i + 1}: expected 'watches:'")
    watches, key = [], None
    for n in range(i + 2, len(lines) + 2):
        line = lines[n - 1] if n <= len(lines) else None
        if line is not None and (line.startswith("#") or (not line.strip() and key is None)):
            continue
        m = KEY_RE.match(line) if line is not None else None
        if line is not None and not m and (not line.strip() or line.startswith("   ")):
            if key is None:
                raise YamlError(f"line {n}: unsupported YAML ({line.strip()[:30]!r})")
            key[2].append(line.strip())
            continue
        if key:
            while key[2] and not key[2][-1]:
                key[2].pop()
            watches[-1][key[0]] = scalar(key[2], key[1])
            key = None
        if line is None:
            break
        if not m:
            raise YamlError(f"line {n}: unsupported YAML ({line.strip()[:30]!r})")
        if m.group(1) == "- ":
            watches.append({})
        elif not watches:
            raise YamlError(f"line {n}: a key outside a list entry")
        if m.group(2) in watches[-1]:
            raise YamlError(f"line {n}: duplicate key {m.group(2)}")
        key = (m.group(2), n, [(m.group(3) or "").strip()])
    return comments, watches


def plain_ok(value):
    if not value or value != value.strip() or SPECIAL_RE.match(value):
        return False
    if value[0] in "-?:,[]{}#&*!|>'\"%@`" or value.endswith(":"):
        return False
    if ": " in value or " #" in value or "\t" in value:
        return False
    return value.isprintable()


def dump_value(value):
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, int):
        return str(value)
    value = str(value)
    if plain_ok(value):
        return value
    if value.isprintable():
        return "'" + value.replace("'", "''") + "'"
    out = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
    return '"' + "".join(c if c.isprintable() else f"\\u{ord(c):04x}" for c in out) + '"'


def dump(comments, watches):
    lines = list(comments or HEADER)
    if not watches:
        return "\n".join(lines + ["watches: []"]) + "\n"
    lines.append("watches:")
    for watch in watches:
        for n, key in enumerate(sorted(watch)):
            lines.append(f"{'- ' if n == 0 else '  '}{key}: {dump_value(watch[key])}")
    return "\n".join(lines) + "\n"


def field(spec, low, high, lineno=None):
    """One cron field -> the set of values it allows."""
    allowed = set()
    for part in spec.split(","):
        m = re.fullmatch(r"(\*|(\d+)(?:-(\d+))?)(?:/(\d+))?", part)
        if not m:
            raise ValueError(f"bad cron field {spec!r}")
        start, end = (low, high) if m.group(1) == "*" else (int(m.group(2)), int(m.group(3) or m.group(2)))
        if m.group(4) and m.group(1) != "*" and not m.group(3):
            end = high
        step = int(m.group(4) or 1)
        if start < low or end > high or start > end or step < 1:
            raise ValueError(f"cron field {spec!r} out of range {low}-{high}")
        allowed.update(range(start, end + 1, step))
    return allowed


def parse_cron(cron):
    parts = str(cron).split()
    if len(parts) != 5:
        raise ValueError(f"cron {cron!r} needs 5 fields")
    minute, hour, dom, month, dow = (field(p, lo, hi) for p, (lo, hi) in
                                     zip(parts, [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]))
    dow = {d % 7 for d in dow}
    return minute, hour, dom, month, dow, parts[2] != "*", parts[4] != "*"


def latest(cron, now):
    """The newest time the cron fires at or before `now` (naive local time), None within 400 days."""
    minute, hour, dom, month, dow, dom_set, dow_set = parse_cron(cron)
    for back in range(400):
        day = now.date() - dt.timedelta(days=back)
        by_dom, by_dow = day.day in dom, (day.weekday() + 1) % 7 in dow
        day_ok = (by_dom or by_dow) if dom_set and dow_set else (by_dom and by_dow)
        if day.month not in month or not day_ok:
            continue
        for h in sorted(hour, reverse=True):
            for m in sorted(minute, reverse=True):
                at = dt.datetime.combine(day, dt.time(h, m))
                if at <= now:
                    return at
    return None


def due(watch, now):
    """Active and the newest cron time at or before now lies after last_run (no last_run: due)."""
    if watch.get("active", True) is False:
        return False
    try:
        fired = latest(watch.get("cron", ""), now.replace(tzinfo=None))
    except ValueError:
        return None
    last = watch.get("last_run")
    if not last:
        return True
    try:
        last = dt.datetime.fromisoformat(str(last))
    except ValueError:
        return True
    if last.tzinfo is not None:
        last = last.astimezone(now.tzinfo).replace(tzinfo=None) if now.tzinfo else last.replace(tzinfo=None)
    return fired is not None and fired > last
