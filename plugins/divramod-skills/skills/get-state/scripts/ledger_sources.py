"""The farmer page's ledgers (hal2 plan 0369, D11, D12): the questions and the decisions of every numbered field's
current plan, read from the plan folder `<row path>/plans/<plan>/` (`questions.md`, `decisions.md`). Read-only, no model
call; a missing file, a missing CLI or a garbled entry gives fewer rows, never an error.

- `questions(rows)`: one dict per question entry: `wt`, `plan`, `n` (`Q3`), `state` (`open`, `answered`, `dropped`),
  `date`, `question`, `options` (the a) b) c) texts), `answer`. `hal2-cli-plans questions list --all --json` is asked,
  once per plan (D15, record questions-through-hal2-cli-plans); when it is missing or fails, `parse_questions` reads
  the file. `submit_questions(rows, pool)` runs the calls in a caller's pool (the collector's, beside `gh`).
- `decisions(rows)`: one dict per ledger entry: `wt`, `plan`, `n` (`D12`), `date`, `who`, `state` (`in-force`,
  `promoted`, `superseded`, `ended`), `decision`, `words`, `why`.

Each plan's ledgers are read once, from the field `sources(rows)` picks (D14); `read_questions` is injectable
(`questions(rows, read=...)`).
"""

import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PureWindowsPath

CLI = "hal2-cli-plans"
TIMEOUT = 15
POOL = 6

Q_HEAD = re.compile(r"^## Q(\d+) · (\S+) · (\S+) · (\w+)[^\n]*$", re.M)
D_HEAD = re.compile(r"^## D(\d+) · (\S+) · (\S+) · ([\w-]+)[^\n]*$", re.M)
FIELD = re.compile(r"^\*\*([A-Za-z][^*\n]*?):\*\*[ \t]*", re.M)
OPTION = re.compile(r"(?:^|(?<=[\s(,;]))([a-c])\) ")


def plan_folder(row: dict) -> tuple[Path, str] | None:
    """(plan folder, plan name) of a field row: its CURRENT_PLAN text as a folder under `<path>/plans/`, else None."""
    path, text = row.get("path"), row.get("plan")
    if not path or not text:
        return None
    slug = text.strip().removesuffix("/plan.md").rstrip("/").removeprefix("plans/")
    parts = slug.replace("\\", "/").split("/")
    if not slug or slug.startswith((".", "/", "\\", "-")) or ".." in parts or PureWindowsPath(slug).anchor:
        return None  # a CURRENT_PLAN naming a folder outside the field's plans/ (absolute, `..`, a drive) is no plan
    folder = Path(path) / "plans" / slug
    return (folder, slug) if folder.is_dir() else None


def read_text(file: Path) -> str:
    try:
        return file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def entries(text: str, head: re.Pattern) -> list[dict]:
    """The ledger's entries in file order: heading groups plus `fields`, the `**Name:** text` blocks folded to one line."""
    marks = list(head.finditer(text))
    out = []
    for i, m in enumerate(marks):
        body = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        parts = list(FIELD.finditer(body))
        fields = {}
        for j, f in enumerate(parts):
            end = parts[j + 1].start() if j + 1 < len(parts) else len(body)
            fields.setdefault(f.group(1).strip().lower(), " ".join(body[f.end():end].split()))
        out.append({"n": int(m.group(1)), "date": m.group(2), "who": m.group(3), "state": m.group(4), "fields": fields})
    return out


def split_options(text: str) -> tuple[str, list[str]]:
    """A question text `... a) x, b) y, c) z?` as (the question before a), the option texts); no a) b) gives no options."""
    marks = list(OPTION.finditer(text))
    if [m.group(1) for m in marks][:2] != ["a", "b"]:
        return text, []
    options = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        options.append(text[m.end():end].strip().rstrip(",;").strip())
    return text[:marks[0].start()].strip(), options


def parse_questions(text: str) -> list[dict]:
    """The stored format (`## Q<n> · date · who · open|answered <date>|dropped <date>`, `**Q:**`, `**A:**`) as dicts."""
    out = []
    for e in entries(text, Q_HEAD):
        question, options = split_options(e["fields"].get("q", ""))
        out.append({"n": e["n"], "state": e["state"], "date": e["date"], "question": question, "options": options,
                    "answer": e["fields"].get("a") or None})
    return out


def cli_questions(path: str, slug: str) -> list[dict] | None:
    """`hal2-cli-plans questions list --all --json` for one plan; None when the CLI is missing, fails or answers garbage."""
    try:
        done = subprocess.run([CLI, "questions", "list", "--all", "--json", "--repo", path, "--plan", slug],
                              capture_output=True, text=True, timeout=TIMEOUT, check=False)
        found = json.loads(done.stdout)["entries"] if done.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(found, list):
        return None
    return [{k: e.get(k) for k in ("n", "state", "date", "question", "options", "answer")} for e in found if isinstance(e, dict)]


def read_questions(row: dict) -> list[dict]:
    """One field's questions: the CLI's, else the parsed file."""
    found = plan_folder(row)
    if not found:
        return []
    folder, slug = found
    entries_ = cli_questions(row["path"], slug)
    return entries_ if entries_ is not None else parse_questions(read_text(folder / "questions.md"))


def fields_with_plan(rows: list[dict]) -> list[dict]:
    return [r for r in rows if str(r.get("wt", "")).isdigit() and not r.get("is_main") and plan_folder(r)]


def sources(rows: list[dict]) -> list[dict]:
    """One field per plan, in the rows' order (plan 0369 D14): the field that runs the plan itself, else (only servants hold
    it, `foreman` set by their plans/LEAD) the lowest numbered servant's copy. Each plan's ledgers are read once."""
    fields = fields_with_plan(rows)
    best: dict[str, dict] = {}
    for r in sorted(fields, key=lambda r: (bool(r.get("foreman")), int(r["wt"]))):
        best.setdefault(plan_folder(r)[1], r)
    chosen = {id(r) for r in best.values()}
    return [r for r in fields if id(r) in chosen]


def submit_questions(rows: list[dict], pool, read=read_questions):
    """Starts one read per plan (`sources`) in `pool`; returns a function that waits and gives `questions`' list."""
    fields = sources(rows)
    futures = [pool.submit(_safe, read, r) for r in fields]
    return lambda: assemble(fields, [f.result() for f in futures])


def questions(rows: list[dict], read=read_questions) -> list[dict]:
    """The questions of every plan of a numbered field (`sources`), in field order, newest question first within a field."""
    with ThreadPoolExecutor(POOL) as pool:
        return submit_questions(rows, pool, read)()


def assemble(fields: list[dict], found: list[list[dict]]) -> list[dict]:
    out = []
    for r, items in zip(fields, found):
        for q in sorted(items, key=_number, reverse=True):
            out.append({"wt": r["wt"], "plan": plan_folder(r)[1], "options": [], "answer": None, **q,
                        "n": f"Q{q.get('n')}"})
    return out


def _number(q: dict) -> int:
    """A question's number for sorting; a CLI answer with a missing or non-integer `n` sorts as 0, never raises."""
    n = q.get("n")
    return n if isinstance(n, int) and not isinstance(n, bool) else 0


def _safe(read, row: dict) -> list[dict]:
    try:
        return [q for q in read(row) if isinstance(q, dict)]
    except Exception:  # noqa: BLE001  (one field's broken ledger never fails the page)
        return []


def decisions(rows: list[dict]) -> list[dict]:
    """The ledger entries of every plan of a numbered field (`sources`), in field order, newest decision first per field."""
    out = []
    for r in sources(rows):
        folder, slug = plan_folder(r)
        for e in sorted(entries(read_text(folder / "decisions.md"), D_HEAD), key=lambda e: e["n"], reverse=True):
            f = e["fields"]
            out.append({"wt": r["wt"], "plan": slug, "n": f"D{e['n']}", "date": e["date"], "who": e["who"],
                        "state": e["state"], "decision": f.get("d", ""), "words": f.get("words", ""), "why": f.get("why", "")})
    return out
