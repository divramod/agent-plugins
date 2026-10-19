"""Bounded edits of a SKILL.md (plan 0390 step 3; research 0100: SkillOpt's add / delete / replace by anchor). Stdlib.

An edit set is a JSON list (or `{"edits": [...]}`) of

    {"op": "add" | "delete" | "replace", "anchor": "<exact text of the skill>", "text": "<new text>"}

`apply(incumbent, edits)` applies them in order, each against the text the earlier ones left:

- `replace` puts `text` in place of the anchor, `delete` removes the anchor (`text` is ignored), `add` inserts `text`
  after the anchor; when the anchor ends a line and `text` does not start with a line break, `text` becomes its own
  line(s) right after the anchor's line.
- An anchor must be non-empty and occur exactly once (overlapping occurrences count); else the edit is rejected.
- At most `max_edits` (4) edits; the ones after are rejected. An edit that changes nothing is rejected.
- The front matter's `name` never changes: an edit that changes, removes or duplicates it is rejected.
- Size cap: an edit that would make the text longer than the incumbent's length times 1 + `max_growth` (20%) is
  rejected, so the result never passes the cap.

A rejected edit leaves the text as it was; every edit gets a verdict `{index, op, ok, reason}` (reason None when ok).
`unified_diff(old, new, path)` is the `best.diff` form (`a/<path>`, `b/<path>`, git apply's no-newline marker).
"""

import difflib
import re

OPS = ("add", "delete", "replace")
MAX_EDITS = 4
MAX_GROWTH = 0.20
FRONT = re.compile(r"\A---\n(.*?)\n---(?:\n|\Z)", re.S)
NAME_LINE = re.compile(r"^name:\s*(.*?)\s*$", re.M)


class EditError(Exception):
    """An edit set that is no list of edits at all."""


def parse_edits(obj):
    """The edit list of a decoded edit set (a list or {"edits": list}); each item's shape is checked by apply()."""
    if isinstance(obj, dict) and "edits" in obj:
        obj = obj["edits"]
    if not isinstance(obj, list):
        raise EditError(f"an edit set is a JSON list, got {type(obj).__name__}")
    return obj


def front_names(text):
    """Every `name:` value of the front matter, [] without front matter."""
    match = FRONT.match(text or "")
    return NAME_LINE.findall(match.group(1)) if match else []


def size_cap(incumbent, max_growth=MAX_GROWTH):
    """The longest text (characters) a candidate of this incumbent may have."""
    return int(len(incumbent) * (1 + max_growth))


def occurrences(text, anchor):
    """How often `anchor` occurs in `text`, overlapping ones counted."""
    count, start = 0, text.find(anchor)
    while start != -1:
        count += 1
        start = text.find(anchor, start + 1)
    return count


def shape_error(edit):
    """Why an edit is malformed, or None."""
    if not isinstance(edit, dict):
        return "an edit is a JSON object"
    if edit.get("op") not in OPS:
        return f"unknown op {edit.get('op')!r} (add, delete, replace)"
    if not isinstance(edit.get("anchor"), str) or not edit["anchor"]:
        return "anchor must be non-empty text"
    if edit["op"] != "delete" and not isinstance(edit.get("text"), str):
        return f"{edit['op']} needs a text"
    return None


def _added(text, end, new):
    if (end == len(text) or text[end] == "\n") and not new.startswith("\n"):
        return text[:end] + "\n" + new.rstrip("\n") + text[end:]
    return text[:end] + new + text[end:]


def apply_one(text, edit):
    """(new text, None) or (text, reason) for one edit."""
    reason = shape_error(edit)
    if reason:
        return text, reason
    anchor = edit["anchor"]
    found = occurrences(text, anchor)
    if found != 1:
        return text, f"anchor occurs {found} times, must be exactly once"
    start = text.index(anchor)
    end = start + len(anchor)
    if edit["op"] == "replace":
        new = text[:start] + edit["text"] + text[end:]
    elif edit["op"] == "delete":
        new = text[:start] + text[end:]
    else:
        new = _added(text, end, edit["text"])
    if new == text:
        return text, "the edit changes nothing"
    if front_names(new) != front_names(text):
        return text, "the front matter's name must not change"
    return new, None


def apply(incumbent, edits, max_edits=MAX_EDITS, max_growth=MAX_GROWTH):
    """Apply an edit list to the incumbent: {text, verdicts, applied, changed} (module doc)."""
    cap = size_cap(incumbent, max_growth)
    text, verdicts = incumbent, []
    for index, edit in enumerate(parse_edits(edits)):
        op = edit.get("op") if isinstance(edit, dict) else None
        if index >= max_edits:
            new, reason = text, f"over the edit limit ({max_edits})"
        else:
            new, reason = apply_one(text, edit)
        if reason is None and len(new) > cap:
            new, reason = text, f"size cap: {len(new)} chars > {cap} (incumbent {len(incumbent)} + {max_growth:.0%})"
        verdicts.append({"index": index, "op": op, "ok": reason is None, "reason": reason})
        text = new
    applied = sum(1 for verdict in verdicts if verdict["ok"])
    return {"text": text, "verdicts": verdicts, "applied": applied, "changed": text != incumbent}


def unified_diff(old, new, path):
    """The unified diff of old -> new as `git apply` reads it ('' when equal)."""
    out = []
    for line in difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                     fromfile=f"a/{path}", tofile=f"b/{path}"):
        out.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return "".join(out)
