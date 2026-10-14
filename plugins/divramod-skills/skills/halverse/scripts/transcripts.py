#!/usr/bin/env python3
"""The user's own typed prompts from the Claude Code transcripts (plan 0270, D5).

`user_messages(days)` yields what the user typed in the last `days` days; `clean(text)` cuts from one message
everything the user did not write (reminders, command wrappers, pasted content, skill bodies, code, URLs, paths).
Only reads; stores and sends nothing. Python stdlib only.
"""
import glob
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Iterator, NamedTuple, Optional

ROOT_ENV = "HALVERSE_PROJECTS_ROOT"


class Message(NamedTuple):
    text: str
    timestamp: datetime
    path: str


# Blocks the harness or a tool put into a user line: the tag and everything up to its closing tag.
_TAGS = ("system-reminder", "task-notification", "cross-session-message", "pasted_content",
         "local-command-caveat", "local-command-stdout", "local-command-stderr")
_BLOCKS = [re.compile(r"<%s\b[^>]*>.*?(?:</%s>|\Z)" % (t, t), re.S) for t in _TAGS]
_COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)
_COMMAND_TAG = re.compile(r"</?command-[a-z]+>(?:.*?</command-[a-z]+>)?", re.S)
_SKILL_BODY = re.compile(r"Base directory for this skill:.*\Z", re.S)
_FENCE = re.compile(r"```.*?(?:```|\Z)", re.S)
_INLINE = re.compile(r"`[^`\n]*`")
_URL = re.compile(r"\b(?:https?|ftp|file)://\S+|\bwww\.\S+")
# a path: absolute, home or dot-relative; or a relative one with two slashes or a file extension
_PATH = re.compile(
    r"(?<![\w/.])(?:~|\.{1,2})?/[\w.@+~-]+(?:/[\w.@+~-]*)+"
    r"|(?<![\w/.])[\w.@+~-]+(?:/[\w.@+~-]+){2,}"
    r"|(?<![\w/.])[\w@+~-]+(?:/[\w.@+~-]+)*/[\w@+~-]+\.\w{1,8}\b")
_PLACEHOLDER = re.compile(r"\[(?:Image|Pasted text|Pasted image)[^\]]*\]")
_SLASH_FIRST = re.compile(r"^\s*/[A-Za-z][\w:.-]*(?=\s|$)")
# Prompts other sessions or hal2 itself type into a session (the terminal gives them the same `typed` source as the
# user's own keys): the start of their first line. Seen in the real transcripts 2026-10; extend when a new one shows.
_GENERATED = re.compile(
    r"^\s*(?:"
    r"hal2 (?:stopped|resumed|watcher)\b"
    r"|run /mfm(?: \([^)]*\))? first, then:"
    r"|/mfm, then\b"
    r"|you are (?:a|an|the) [\w -]{0,30}(?:servant|agent|foreman|farmer|coordinator|steward)\b"
    r"|(?:owner|farmer|coordinator|project manager|merge-to-main boss)\b[^:\n]{0,60}:"
    r"|wagon-master [^:\n]{0,60}:"  # the wagon master's messages: `wagon-master [<id>] (wagon train): ...`
    r"|# post watch digest"
    r"|<!--"
    r")", re.I)


def is_generated(raw: str) -> bool:
    """True for a prompt another session or hal2 typed (a launch prompt, a farmer's message, a guard notice)."""
    return bool(_GENERATED.match(raw))


def clean(text: str) -> str:
    """The part of a user message the user wrote as words; '' when nothing is left."""
    args = _COMMAND_ARGS.search(text)
    if args:
        text = args.group(1)  # a command wrapper keeps only its arguments
    text = _SKILL_BODY.sub("", text)
    for block in _BLOCKS:
        text = block.sub(" ", text)
    text = _COMMAND_TAG.sub(" ", text)
    text = _SLASH_FIRST.sub("", text, count=1)
    for rx in (_FENCE, _INLINE, _URL, _PATH, _PLACEHOLDER):
        text = rx.sub(" ", text)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()


def _projects_root(root: Optional[str]) -> str:
    return root or os.environ.get(ROOT_ENV) or os.path.expanduser("~/.claude/projects")


def _parse_time(value: object) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _typed_text(line: dict) -> Optional[str]:
    """The raw text of a line the user typed, else None (D5; keys seen in real transcripts 2026-10)."""
    if line.get("type") != "user" or line.get("isMeta") or line.get("isSidechain"):
        return None
    if line.get("toolUseResult") is not None or line.get("isCompactSummary"):
        return None
    if line.get("promptSource") == "system":
        return None
    origin = line.get("origin")
    if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
        return None  # peer session, task notification, ...
    message = line.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if not isinstance(content, list) or any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return None
    texts = [b.get("text") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return "\n".join(t for t in texts if isinstance(t, str))


def _may_be_typed(raw: str) -> bool:
    """A cheap test on the raw line, before json.loads: only `user` lines without a tool result can be typed.

    The transcripts are gigabytes, mostly tool output: parsing every line takes seconds. Claude Code writes compact
    JSON; the escaped quotes inside a message's own text never match these plain-quote tests.
    """
    return ('"type":"user"' in raw or '"type": "user"' in raw) and '"tool_result"' not in raw


def _read_lines(path: str) -> Iterator[dict]:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                if not _may_be_typed(raw):
                    continue
                try:
                    obj = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    yield obj
    except OSError:
        return


def user_messages(days: float, root: Optional[str] = None,
                  now: Optional[datetime] = None) -> Iterator[Message]:
    """The user's typed prompts of the last `days` days, cleaned, empty ones left out."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    for path in sorted(glob.glob(os.path.join(_projects_root(root), "*", "*.jsonl"))):
        try:
            if os.path.getmtime(path) < cutoff.timestamp():
                continue  # the file was last written before the window: no line in it is inside
        except OSError:
            continue
        for line in _read_lines(path):
            stamp = _parse_time(line.get("timestamp"))
            if stamp is None or stamp < cutoff or stamp > now:
                continue
            raw = _typed_text(line)
            text = clean(raw) if raw and not is_generated(raw) else ""
            if text:
                yield Message(text, stamp, path)
