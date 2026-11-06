"""The related plans' questions in sections (plan 0683): the current plan, its masterplan, the masterplan's rows
running in this field, each under its `<NNNN> <title>` heading. Only by `hal2-cli-plans`; None means "print as before"
(no CLI, no related plan, or the current plan's own lookup failed)."""

import json
import re
import subprocess
from pathlib import Path


def cli_out(cli: str, root: Path, *args: str) -> str | None:
    """The CLI's stdout (maybe empty) when it exits 0, else None."""
    try:
        run = subprocess.run([cli, *args], cwd=root, text=True, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return run.stdout if run.returncode == 0 else None


def cli_json(cli: str, root: Path, *args: str) -> dict | None:
    out = cli_out(cli, root, *args, "--json")
    try:
        data = json.loads(out) if out and out.strip() else None
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def number_of(text: str) -> int | None:
    m = re.match(r"(\d{1,4})(?:-|$)", text)
    return int(m.group(1)) if m else None


def show(cli: str, root: Path, number: int) -> dict | None:
    info = cli_json(cli, root, "show", str(number), "--repo", str(root))
    return info if info and info.get("slug") else None


def entry(info: dict, number: int, role: str) -> dict:
    return {"number": number, "title": info.get("title", ""), "slug": info["slug"], "role": role}


def related(cli: str, root: Path, current: Path) -> list[dict]:
    """The plans to print, in order and each once: [{number, title, slug, role}]; empty when none is related."""
    number = number_of(current.name)
    info = show(cli, root, number) if number is not None else None
    parent = (info or {}).get("parent")
    if info is None or parent in (None, ""):
        return []
    parent = int(parent)
    found = [entry(info, number, "current")]
    if master := show(cli, root, parent):
        found.append(entry(master, parent, "masterplan"))
    rows = (cli_json(cli, root, "masterplan", str(parent), "--repo", str(root)) or {}).get("rows") or []
    mine = sorted(r["number"] for r in rows if r.get("status") == "running" and r.get("checkout") == root.name
                  and isinstance(r.get("number"), int) and r["number"] not in (number, parent))
    for n in mine:
        if row := show(cli, root, n):
            found.append(entry(row, n, "row"))
    return found


def store_json(cli: str, root: Path, rel: str, mode: str) -> dict | None:
    """{store, mode, entries, problems} of one store; None when the CLI's list fails."""
    out = cli_out(cli, root, "questions", "list", f"--{mode}", "--json", "--store", rel)
    if out is None:
        return None
    try:
        entries = json.loads(out).get("entries", []) if out.strip() else []
    except ValueError:
        return None
    checked = cli_json(cli, root, "questions", "check", "--store", rel) or {}
    return {"store": rel, "mode": mode, "entries": entries, "problems": checked.get("problems", [])}


def body_of(cli: str, root: Path, slug: str, mode: str, as_json: bool):
    """A store's list: its JSON dict, or the CLI's markdown ('' when it prints nothing); None when the CLI fails."""
    rel = f"plans/{slug}/questions.md"
    if as_json:
        return store_json(cli, root, rel, mode)
    out = cli_out(cli, root, "questions", "list", f"--{mode}", "--markdown", "--store", rel)
    return None if out is None else out.strip()


def sections(cli: str | None, root: Path, current: Path | None, mode: str, none_line: str, as_json: bool):
    """The sections as text (or the --json dict); None when q.py prints the single store as before. The current plan's
    own list is asked first: when it fails, or no plan is related, nothing else is asked."""
    if not cli or current is None:
        return None
    first = body_of(cli, root, current.name, mode, as_json)
    plans = related(cli, root, current) if first is not None else []
    if not plans:
        return None
    bodies = [first] + [body_of(cli, root, p["slug"], mode, as_json) for p in plans[1:]]
    shown = [(p, b) for p, b in zip(plans, bodies) if b is not None]
    if as_json:
        return {**first, "plans": [{"number": p["number"], "title": p["title"], "role": p["role"],
                                    "store": b["store"], "entries": b["entries"], "problems": b["problems"]} for p, b in shown]}
    return "\n\n".join(f"{p['number']:04d} {p['title']}\n{b or none_line}" for p, b in shown)
