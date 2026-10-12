#!/usr/bin/env python3
"""Deterministic bookkeeping for research docs under research/ at the repository root.

A research doc is a folder research/<NNNN>-<slug>/ holding research.md and its helper files. research.md starts with
YAML front matter (the template's keys) and uses fixed H2 names in the template's order; the core H2s are required.
`new` writes the record envelope (hal2's decision record `record-formats`): `type: Research`, `schema: 1` and a
`description` (the question's first sentence, else the title; at most 200 characters). A doc without `type` is
legacy: it may lack the three keys.

  research.py new "<title>" [--question "<q>"] [--plan <path>] [--origin <ref>] [--kind <kind>] [--author <a>]
                                    [--fetch]
                                    create the next research doc from the template; its number is unique across
                                    all worktrees and branches (research_number.py; --fetch sees other clones too)
  research.py list                  every doc as JSON (front matter, sections present, missing, problems)
  research.py status <n>            one doc as JSON (<n>: number, 0019, or the folder name)
  research.py check [--branches]    every research/*/research.md: front matter, required keys and values,
                                    H1, required H2s in order, id = folder number, no number used twice;
                                    --branches also checks numbers across worktrees and branches; then hal2's
                                    records checker (`hal2-cli-records check --json`, checker.py:
                                    $HAL2_CLI_RECORDS, else on PATH) over the typed docs (`type: Research`), its
                                    problems ending in their rule; without it one line `records unchecked: ...`
                                    (advisory); exit 1 on problems
  research.py set <n> <key> <value> set one front matter field (bumps `updated`); lists as `a, b` or `[a, b]`
  research.py log <n> "<text>"      append `- <today>: <text>` to the Log and bump `updated`

Run from anywhere inside the repo, or pass --root. Prints JSON on stdout (check prints lines); exits 1 with a
message on stderr. The front matter is parsed without third-party modules: a YAML subset covering the template
(plain and quoted scalars, `>-`/`|` block scalars, flow lists and maps, block lists, comments).
"""
import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import checker
import research_number

RESEARCH = Path("research")
MAIN = "research.md"
DOC_RE = re.compile(r"^(\d{4})-[a-z0-9][a-z0-9-]*$")
TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "research.md"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SECTIONS = [  # the template's H2s in order; True = required
    ("Answer", True),
    ("Key findings", True),
    ("Recommendation", True),
    ("Decision", True),
    ("Question and scope", True),
    ("Method", True),
    ("Background", False),
    ("Findings", True),
    ("Options", False),
    ("Comparison", False),
    ("Assumptions and what would change our mind", False),
    ("Risks", False),
    ("Open questions", True),
    ("Next steps", False),
    ("Evidence", False),
    ("Sources", True),
    ("Log", True),
]
ORDER = [name for name, _ in SECTIONS]
REQUIRED_SECTIONS = [name for name, required in SECTIONS if required]
KEYS = ["type", "schema", "id", "title", "description", "question", "status", "answer", "confidence", "kind", "created", "updated", "revisit",
        "author", "origin", "plan", "follow_up", "decision", "supersedes", "superseded_by", "related", "tags",
        "sources", "claims"]
LIST_KEYS = {"follow_up", "supersedes", "superseded_by", "related", "tags"}
INT_KEYS = {"id", "sources", "schema"}
# The record envelope (hal2's decision record `record-formats`): `new` writes it; a doc from before it (no `type`)
# is legacy and may lack the three keys.
ENVELOPE = {"type": "Research", "schema": 1}
DESCRIPTION = 200
FOLDED_KEYS = {"question", "answer"}
STATUSES = ["planned", "researching", "verifying", "done", "decided", "abandoned", "superseded"]
CONFIDENCES = ["high", "moderate", "low"]
KINDS = ["decision", "investigation", "survey", "incident", "architecture"]
CLAIM_KEYS = ["total", "verified", "disputed"]
REVISIT_MONTHS = 6


class ResearchError(Exception):
    pass


# --- YAML subset ---------------------------------------------------------------------------------------------------

def strip_comment(text: str) -> str:
    """Drop a ` #` comment outside quotes."""
    quote, escaped = None, False
    for i, ch in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\" and quote == '"':
                escaped = True
            elif ch == quote:
                quote = None
        elif ch in "\"'" and (i == 0 or text[i - 1] in " [{,:"):
            quote = ch
        elif ch == "#" and (i == 0 or text[i - 1] in " \t"):
            return text[:i].rstrip()
    return text.rstrip()


def split_flow(text: str) -> list[str]:
    """Split the inside of `[..]` or `{..}` at top-level commas."""
    parts, depth, quote, current = [], 0, None, ""
    for ch in text:
        if quote:
            current += ch
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(current.strip())
            current = ""
            continue
        current += ch
    if current.strip():
        parts.append(current.strip())
    return parts


def scalar(text: str):
    text = text.strip()
    if text == "" or text in ("~", "null"):
        return None
    if text.startswith("[") and text.endswith("]"):
        return [scalar(part) for part in split_flow(text[1:-1])]
    if text.startswith("{") and text.endswith("}"):
        out = {}
        for part in split_flow(text[1:-1]):
            key, sep, value = part.partition(":")
            if not sep:
                raise ResearchError(f"flow map entry without a colon: {part}")
            out[key.strip()] = scalar(value)
        return out
    if len(text) >= 2 and text[0] == text[-1] == '"':
        return json.loads(text)
    if len(text) >= 2 and text[0] == text[-1] == "'":
        return text[1:-1].replace("''", "'")
    if text in ("true", "false"):
        return text == "true"
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if ": " in text or text.endswith(":"):
        raise ResearchError(f"plain value contains ': ' (quote it): {text}")
    return text


def parse_yaml(lines: list[str]) -> dict:
    """The front matter's lines (without the --- fences) as a dict; raises ResearchError on what it can't read."""
    data: dict = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if line[0] in " \t":
            raise ResearchError(f"unexpected indented line {i + 2}: {line.strip()}")
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s+(.*))?$", line)
        if not match:
            raise ResearchError(f"not a `key: value` line {i + 2}: {line}")
        key, rest = match.group(1), strip_comment(match.group(2) or "")
        if key in data:
            raise ResearchError(f"key `{key}` given twice")
        i += 1
        block = []
        while i < len(lines) and (not lines[i].strip() or lines[i][0] in " \t"):
            block.append(lines[i])
            i += 1
        while block and not block[-1].strip():
            block.pop()
        if rest in (">", ">-", ">+", "|", "|-", "|+"):
            body = textwrap.dedent("\n".join(block)).split("\n") if block else []
            if rest.startswith(">"):
                paragraphs, current = [], []
                for piece in body:
                    if piece.strip():
                        current.append(piece.strip())
                    else:
                        paragraphs.append(" ".join(current))
                        current = []
                paragraphs.append(" ".join(current))
                data[key] = "\n".join(paragraphs).strip()
            else:
                data[key] = "\n".join(body).rstrip("\n")
        elif block:
            if rest:
                raise ResearchError(f"`{key}` has a value and indented lines below it")
            items = []
            for piece in block:
                piece = piece.strip()
                if not piece or piece.startswith("#"):
                    continue
                if not piece.startswith("- "):
                    raise ResearchError(f"`{key}`: only block lists (`- item`) are read, got: {piece}")
                items.append(scalar(strip_comment(piece[2:])))
            data[key] = items
        else:
            data[key] = scalar(rest)
    return data


def dump_scalar(value) -> str:
    """One value as the template writes it."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(dump_scalar(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}: {dump_scalar(v)}" for k, v in value.items()) + "}"
    text = str(value)
    plain = (text and text == text.strip() and ": " not in text and " #" not in text and not text.endswith(":")
             and text[0] not in "[]{}&*!|>'\"%@`#,-?" and not re.fullmatch(r"-?\d+|true|false|null|~", text))
    return text if plain else json.dumps(text, ensure_ascii=False)


def dump_field(key: str, value) -> list[str]:
    if key in FOLDED_KEYS and isinstance(value, str) and value:
        return [f"{key}: >-"] + textwrap.wrap(value, 114, initial_indent="  ", subsequent_indent="  ")
    text = dump_scalar(value)
    return [f"{key}: {text}" if text else f"{key}:"]


# --- documents -----------------------------------------------------------------------------------------------------

def repo_root(start: Path) -> Path:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True, text=True)
    return Path(out.stdout.strip()) if out.returncode == 0 else start


def split_doc(text: str) -> tuple[list[str], list[str]]:
    """(front matter lines, body lines); raises when there is no front matter."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise ResearchError("no YAML front matter (the file must start with ---)")
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], lines[i + 1:]
    raise ResearchError("front matter is not closed with ---")


def headings(body: list[str], level: int) -> list[tuple[int, str]]:
    """(line index, text) of every heading of `level` outside fenced code."""
    found, fence = [], None
    prefix = "#" * level + " "
    for i, line in enumerate(body):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            mark = stripped[:3]
            fence = None if fence == mark else (fence or mark)
            continue
        if fence is None and line.startswith(prefix):
            found.append((i, line[len(prefix):].strip()))
    return found


def doc_folders(root: Path) -> list[Path]:
    folder = root / RESEARCH
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_dir() and DOC_RE.match(p.name))


def validate(folder: Path, meta: dict | None, body: list[str], today: dt.date) -> list[str]:
    problems = []
    number = int(folder.name[:4])
    if meta is not None:
        typed = "type" in meta
        for key in KEYS:
            if key not in meta and (typed or key not in (*ENVELOPE, "description")):
                problems.append(f"front matter: `{key}` is missing")
        for key, value in ENVELOPE.items():
            if key in meta and meta[key] != value:
                problems.append(f"front matter: {key} {meta[key]!r} is not {value!r}")
        if typed and len(str(meta.get("description") or "")) > DESCRIPTION:
            problems.append(f"front matter: `description` has {len(str(meta['description']))} characters, over "
                            f"{DESCRIPTION}")
        for key in meta:
            if key not in KEYS:
                problems.append(f"front matter: unknown key `{key}`")
        if "id" in meta and meta["id"] != number:
            problems.append(f"front matter: id {meta['id']!r} is not the folder's number {number}")
        for key in ("title", "question", "answer", "author") + (("description",) if typed else ()):
            if key in meta and not (isinstance(meta[key], str) and meta[key].strip()):
                problems.append(f"front matter: `{key}` is empty")
        if meta.get("status") not in STATUSES and "status" in meta:
            problems.append(f"front matter: status {meta['status']!r} is not one of {', '.join(STATUSES)}")
        if meta.get("confidence") not in CONFIDENCES and "confidence" in meta:
            problems.append(f"front matter: confidence {meta['confidence']!r} is not one of {', '.join(CONFIDENCES)}")
        if meta.get("kind") not in KINDS and "kind" in meta:
            problems.append(f"front matter: kind {meta['kind']!r} is not one of {', '.join(KINDS)}")
        for key in ("created", "updated", "revisit"):
            if key in meta and not (isinstance(meta[key], str) and DATE_RE.match(meta[key])):
                problems.append(f"front matter: `{key}` is not a YYYY-MM-DD date: {meta[key]!r}")
        for key in LIST_KEYS:
            if key in meta and not isinstance(meta[key], list):
                problems.append(f"front matter: `{key}` is not a list")
        if "sources" in meta and not (isinstance(meta["sources"], int) and meta["sources"] >= 0):
            problems.append("front matter: `sources` is not a count")
        claims = meta.get("claims")
        if "claims" in meta and not (isinstance(claims, dict) and all(isinstance(claims.get(k), int)
                                                                    for k in CLAIM_KEYS)):
            problems.append("front matter: `claims` is not {total: n, verified: n, disputed: n}")
        if meta.get("status") in ("done", "decided"):
            answer = meta.get("answer") or ""
            if isinstance(answer, str) and answer.startswith("<"):
                problems.append("front matter: status is done but `answer` is still the template's placeholder")
        if meta.get("status") == "decided" and not meta.get("decision"):
            problems.append("front matter: status is decided but `decision` names no record")
    titles = headings(body, 1)
    expected = f"Research {number:04d}: "
    if not titles:
        problems.append(f"no H1 `# {expected}<title>`")
    elif not titles[0][1].startswith(expected):
        problems.append(f"H1 `{titles[0][1]}` does not start with `{expected}`")
    elif len(titles) > 1:
        problems.append(f"{len(titles)} H1 headings; one is allowed")
    names = [name for _, name in headings(body, 2)]
    for name in names:
        if name not in ORDER:
            problems.append(f"unknown H2 `{name}` (the template's names: {', '.join(ORDER)})")
    for name in set(names):
        if names.count(name) > 1:
            problems.append(f"H2 `{name}` appears {names.count(name)} times")
    known = [ORDER.index(n) for n in names if n in ORDER]
    if known != sorted(known):
        problems.append("H2s are not in the template's order: " + ", ".join(n for n in names if n in ORDER))
    for name in REQUIRED_SECTIONS:
        if name not in names:
            problems.append(f"required H2 `{name}` is missing")
    return problems


def load(folder: Path, root: Path, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    path = folder / MAIN
    info = {"number": int(folder.name[:4]), "slug": folder.name, "path": str(path.relative_to(root))}
    if not path.is_file():
        return {**info, "problems": [f"{MAIN} is missing"]}
    meta, body, problems = None, [], []
    try:
        fm, body = split_doc(path.read_text())
        meta = parse_yaml(fm)
    except ResearchError as error:
        problems.append(f"front matter: {error}")
        try:
            body = split_doc(path.read_text())[1]
        except ResearchError:
            body = path.read_text().split("\n")
    problems += validate(folder, meta, body, today)
    names = [name for _, name in headings(body, 2)]
    revisit = (meta or {}).get("revisit")
    stale = bool(isinstance(revisit, str) and DATE_RE.match(revisit) and revisit < today.isoformat()
                 and (meta or {}).get("status") in ("done", "decided"))
    return {**info, **({k: (meta or {}).get(k) for k in KEYS}), "stale": stale, "sections": names,
            "missing": [n for n in REQUIRED_SECTIONS if n not in names], "problems": problems}


def find(root: Path, ref: str) -> Path:
    for folder in doc_folders(root):
        if ref in (folder.name, folder.name[:4]) or (ref.isdigit() and int(ref) == int(folder.name[:4])):
            return folder
    raise ResearchError(f"no research doc {ref!r} in {root / RESEARCH}")


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not slug:
        raise ResearchError("title needs at least one letter or digit")
    return slug[:60].rstrip("-")


def add_months(day: dt.date, months: int) -> dt.date:
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    for last in (31, 30, 29, 28):
        try:
            return dt.date(year, month, min(day.day, last))
        except ValueError:
            continue
    raise ValueError(day)


def describe(question: str, title: str) -> str:
    """The doc's `description`: the question's first sentence (the title without a question), at most 200
    characters, cut at a word."""
    text = " ".join((question or title).split())
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    if len(first) <= DESCRIPTION:
        return first
    return first[:DESCRIPTION - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def default_author(root: Path) -> str:
    out = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=root,
                         capture_output=True, text=True)
    common = Path(out.stdout.strip()) if out.returncode == 0 else root / ".git"
    main = common.parent if common.name == ".git" else common
    return f"claude ({main.name})" if main == root else f"claude ({main.name} worktree {root.name})"


def new(root: Path, title: str, question: str = "", plan: str = "", origin: str = "", kind: str = "investigation",
        author: str = "", fetch: bool = False, today: dt.date | None = None) -> Path:
    today = today or dt.date.today()
    if kind not in KINDS:
        raise ResearchError(f"kind {kind!r} is not one of {', '.join(KINDS)}")
    slug = slugify(title)
    if fetch:
        research_number.plan_number.git(root, "fetch", "--all", "--quiet")
    try:
        number = research_number.next_number(root, slug)
    except research_number.NumberError as error:
        raise ResearchError(str(error)) from error
    folder = root / RESEARCH / f"{number:04d}-{slug}"
    if folder.exists():
        raise ResearchError(f"{folder} exists already")
    text = TEMPLATE.read_text().format(
        id=number, number=f"{number:04d}", title=dump_scalar(title), description=dump_scalar(describe(question, title)),
        question=question or "<the question>",
        kind=kind, date=today.isoformat(), revisit=add_months(today, REVISIT_MONTHS).isoformat(),
        author=dump_scalar(author or default_author(root)), origin=dump_scalar(origin or "user request"),
        plan=dump_scalar(plan))
    text = text.replace(f"# Research {number:04d}: {dump_scalar(title)}", f"# Research {number:04d}: {title}")
    folder.mkdir(parents=True)
    (folder / MAIN).write_text(text)
    return folder


def rewrite_meta(folder: Path, change) -> None:
    """Apply `change(meta, lines)` to the front matter lines of folder's research.md and write it back."""
    path = folder / MAIN
    fm, body = split_doc(path.read_text())
    meta = parse_yaml(fm)
    fm = change(meta, fm)
    path.write_text("\n".join(["---", *fm, "---", *body]))


def replace_field(lines: list[str], key: str, value) -> list[str]:
    """The front matter lines with `key`'s line (and its indented continuation) replaced; appended when absent."""
    new_lines = dump_field(key, value)
    for i, line in enumerate(lines):
        if re.match(rf"^{re.escape(key)}:(\s|$)", line):
            j = i + 1
            while j < len(lines) and lines[j].strip() and lines[j][0] in " \t":
                j += 1
            comment = ""
            if len(new_lines) == 1:  # keep the line's comment (the template documents allowed values there)
                rest = line.split(":", 1)[1]
                tail = rest[len(strip_comment(rest)):].strip()
                comment = f"  {tail}" if tail.startswith("#") else ""
            return lines[:i] + [new_lines[0] + comment] + new_lines[1:] + lines[j:]
    return lines + new_lines


def coerce(key: str, raw: str):
    if key not in KEYS:
        raise ResearchError(f"unknown key {key!r} (keys: {', '.join(KEYS)})")
    if key in LIST_KEYS:
        raw = raw.strip()
        if raw.startswith("["):
            return scalar(raw)
        return [scalar(part) for part in split_flow(raw)] if raw else []
    if key == "claims":
        value = scalar(raw if raw.strip().startswith("{") else "{" + raw + "}")
        return {k: value.get(k, 0) for k in CLAIM_KEYS}
    if key in INT_KEYS:
        if not re.fullmatch(r"\d+", raw.strip()):
            raise ResearchError(f"{key} must be a number")
        return int(raw)
    choices = {"status": STATUSES, "confidence": CONFIDENCES, "kind": KINDS}.get(key)
    if choices and raw not in choices:
        raise ResearchError(f"{key} {raw!r} is not one of {', '.join(choices)}")
    if key in ("created", "updated", "revisit") and not DATE_RE.match(raw):
        raise ResearchError(f"{key} must be YYYY-MM-DD")
    return raw


def set_field(folder: Path, key: str, raw: str, today: dt.date | None = None) -> None:
    today = today or dt.date.today()
    value = coerce(key, raw)

    def change(meta, lines):
        lines = replace_field(lines, key, value)
        if key != "updated":
            lines = replace_field(lines, "updated", today.isoformat())
        return lines

    rewrite_meta(folder, change)


def add_log(folder: Path, text: str, today: dt.date | None = None) -> None:
    today = today or dt.date.today()
    path = folder / MAIN
    fm, body = split_doc(path.read_text())
    h2 = headings(body, 2)
    names = [name for _, name in h2]
    if "Log" not in names:
        raise ResearchError(f"{path} has no `## Log` section")
    start = h2[names.index("Log")][0]
    following = [i for i, _ in h2 if i > start]
    end = following[0] if following else len(body)
    last = end
    while last > start + 1 and not body[last - 1].strip():
        last -= 1
    entry = f"- {today.isoformat()}: {text.strip()}"
    body = body[:last] + [entry] + body[last:]
    if not following and (not body or body[-1] != ""):
        body.append("")
    fm = replace_field(fm, "updated", today.isoformat())
    path.write_text("\n".join(["---", *fm, "---", *body]))


def check(root: Path, branches: bool = False) -> list[str]:
    lines = []
    seen: dict[int, list[str]] = {}
    for folder in doc_folders(root):
        seen.setdefault(int(folder.name[:4]), []).append(folder.name)
        for problem in load(folder, root)["problems"]:
            lines.append(f"{folder.name}: {problem}")
    for number, names in sorted(seen.items()):
        if len(names) > 1:
            lines.append(f"{number:04d} is used by: {', '.join(names)}")
    if branches:
        for number, slugs in sorted(research_number.duplicates(root).items()):
            lines.append(f"{number:04d} is used across branches by: "
                         + "; ".join(f"{s} ({research_number.plan_number.places(p)})" for s, p in slugs.items()))
    return lines


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    p_new = sub.add_parser("new")
    p_new.add_argument("title")
    p_new.add_argument("--question", default="")
    p_new.add_argument("--plan", default="")
    p_new.add_argument("--origin", default="")
    p_new.add_argument("--kind", default="investigation", choices=KINDS)
    p_new.add_argument("--author", default="")
    p_new.add_argument("--fetch", action="store_true")
    sub.add_parser("list")
    p_status = sub.add_parser("status")
    p_status.add_argument("ref")
    p_check = sub.add_parser("check")
    p_check.add_argument("--branches", action="store_true")
    p_set = sub.add_parser("set")
    p_set.add_argument("ref")
    p_set.add_argument("key")
    p_set.add_argument("value")
    p_log = sub.add_parser("log")
    p_log.add_argument("ref")
    p_log.add_argument("text")
    args = parser.parse_args(argv)
    root = (args.root or repo_root(Path.cwd())).resolve()

    try:
        if args.command == "new":
            folder = new(root, args.title, args.question, args.plan, args.origin, args.kind, args.author, args.fetch)
            print(json.dumps(load(folder, root), indent=2))
        elif args.command == "list":
            print(json.dumps([load(f, root) for f in doc_folders(root)], indent=2))
        elif args.command == "status":
            print(json.dumps(load(find(root, args.ref), root), indent=2))
        elif args.command == "check":
            problems = check(root, args.branches)
            try:
                found = checker.check(repo=root)
            except checker.CheckerError as error:
                print(error, file=sys.stderr)
                return error.code
            if found is None:
                print(checker.NOT_INSTALLED)
            else:
                problems += [checker.line(p) for p in found["problems"] if p["path"].startswith(f"{RESEARCH}/")]
            for line in problems:
                print(line)
            if problems:
                return 1
            count = len(doc_folders(root))
            print(f"ok: {count} research docs valid, no research number used twice")
        elif args.command == "set":
            folder = find(root, args.ref)
            set_field(folder, args.key, args.value)
            print(json.dumps(load(folder, root), indent=2))
        elif args.command == "log":
            folder = find(root, args.ref)
            add_log(folder, args.text)
            print(json.dumps(load(folder, root), indent=2))
        return 0
    except ResearchError as error:
        print(f"research.py: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
