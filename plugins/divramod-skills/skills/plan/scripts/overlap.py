"""The overlap check of every start path (hal2 plan 0593 step 6; plan 0592 D4, D5, D16): `hal2-cli-plans overlap
--goal "<title + goal>" [--files <path>...] [--research] --json` names the unfinished plans (and, for research, the
earlier research) a new plan, spec, research or delegated brief overlaps. Used by plan.py, spec.py, research.py, the
farmer's delegation and create.py (they reach this module through the plan skill's scripts/).

`scan` returns the CLI's schema 1 answer, or None when it cannot be had (CLI missing or older, a failure, bad JSON,
`HAL2_OVERLAP=off`): a missing CLI never blocks a start, the caller prints `UNCHECKED`. `hits` counts the plans and
research found. `write` puts them into the new folder as `overlap.json`; `lines` is what the start prints and what
goes into the Context, so the model settles each hit (build on it, wait for it, merge into it) before it writes the
plan, recording a ledger entry with a link; a tie goes to the farmer."""
import json
import os
import shutil
import subprocess
from pathlib import Path

CLI = "hal2-cli-plans"
UNCHECKED = "overlap unchecked"
TIMEOUT = 180  # the scan takes ~25 s under load


def off() -> bool:
    """`HAL2_OVERLAP=off`: the tests' switch (the scan takes ~25 s), for a start path that changes a prompt."""
    return os.environ.get("HAL2_OVERLAP", "").lower() == "off"


def scan(root: Path, goal: str, files: list[str] | None = None, research: bool = False) -> dict | None:
    """The overlap answer for `goal`, or None (never raises)."""
    if off() or not shutil.which(CLI):
        return None
    command = [CLI, "overlap", "--goal", " ".join(goal.split()), "--json", "--repo", str(root)]
    for path in files or []:
        command += ["--files", path]
    if research:
        command.append("--research")
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT, check=False)
        data = json.loads(done.stdout) if done.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def hits(result: dict | None) -> int:
    return len((result or {}).get("plans") or []) + len((result or {}).get("research") or [])


def lines(result: dict | None) -> list[str]:
    """One line per hit, plans first; `[overlap unchecked]` for None, `[]` for an empty answer."""
    if result is None:
        return [UNCHECKED]
    out = []
    for p in result.get("plans") or []:
        why = "; ".join(p.get("why") or [])
        out.append(f"plan {p.get('slug')} ({p.get('state') or '?'}, field {p.get('field') or '-'}"
                   f"{', paused' if p.get('paused') else ''}, score {p.get('score')}): {p.get('title') or ''}"
                   f" -- {why} -> {p.get('path')}")
    for r in result.get("research") or []:
        flags = ("stale, " if r.get("stale") else "") + (f"superseded by {r['superseded_by']}, " if r.get("superseded_by") else "")
        out.append(f"research {r.get('slug')} ({flags}{r.get('status') or '?'}, score {r.get('score')}): "
                   f"{r.get('question') or ''} -- {'; '.join(r.get('why') or [])} -> {r.get('path')}")
    return out


def context_line(result: dict | None) -> str:
    """The Context line for the new folder's plan.md / spec.md."""
    if result is None:
        return f"- Overlap: {UNCHECKED} (hal2-cli-plans overlap missing or failed)."
    if not hits(result):
        return "- Overlap: checked (hal2-cli-plans overlap), nothing over the threshold."
    names = ", ".join([p.get("slug", "?") for p in result.get("plans") or []]
                      + [r.get("slug", "?") for r in result.get("research") or []])
    return f"- Overlap: {names} (see [overlap.json](overlap.json)); each settled in the ledger: built on, waited for or merged into."


def write(folder: Path, result: dict | None, name: str = "overlap.json") -> Path | None:
    """`overlap.json` in `folder` (the answer verbatim), None when nothing was checked."""
    if result is None:
        return None
    target = Path(folder) / name
    target.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return target


def report(result: dict | None, folder: Path | None = None) -> str:
    """The text printed (stderr) after the start: the hits and what to do with them."""
    out = lines(result)
    if result is not None and hits(result):
        out.append("settle each hit before writing: build on it, wait for it, or merge into it; record a ledger "
                   "entry with a link; a tie goes to the farmer" + (f" ({folder.name}/overlap.json)" if folder else ""))
    return "\n".join(f"overlap: {l}" for l in out) if result is None or hits(result) else "overlap: none"


def attach(doc: Path, result: dict | None) -> None:
    """Record the check in a new plan.md / spec.md: `overlap.json` beside it and the Context line under `## Context`
    (appended at the end when the document has no such heading)."""
    write(doc.parent, result)
    text = doc.read_text()
    line = context_line(result)
    marker = "## Context\n"
    if marker not in text:
        doc.write_text(text.rstrip("\n") + f"\n\n## Context\n\n{line}\n")
        return
    start = text.index(marker) + len(marker)
    end = text.find("\n## ", start)
    end = len(text) if end < 0 else end + 1
    block = text[start:end].rstrip("\n")
    doc.write_text(text[:start] + block + f"\n{line}\n" + ("\n" if end < len(text) else "") + text[end:])
