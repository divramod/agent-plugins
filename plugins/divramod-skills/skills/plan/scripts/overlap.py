"""The overlap check of every start path (hal2 plan 0593 step 6; plan 0592 D4, D5, D16): `hal2-cli-plans overlap
--goal "<title + goal>" [--files <path>...] [--research] --json` names the unfinished plans (and, for research, the
earlier research) a new plan, spec, research or delegated brief overlaps. Used by plan.py, spec.py, research.py, the
farmer's delegation and create.py (they reach this module through the plan skill's scripts/).

The CLI owns the text (plan 0684 D3, D6): its answer carries `text` {lines, context, report}, rendered once in Rust,
and this module prints it verbatim, never a format of its own over the hits. `scan` returns the CLI's schema 1 answer,
or None when it cannot be had (CLI missing, a failure, bad JSON, no or ill-typed `text` as an older CLI gives,
`HAL2_OVERLAP=off`): a missing CLI never blocks a start, the caller prints `UNCHECKED`, the skill's own wording (the CLI
did not run). `hits` counts the plans and research found. `write` puts the answer into the new folder as
`overlap.json`; `lines`, `context_line` and `report` are what the start prints and what goes into the Context, so the
model settles each hit (build on it, wait for it, merge into it) before it writes the plan."""
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
    return data if isinstance(data, dict) and text(data) is not None else None


def text(result: dict | None) -> dict | None:
    """The answer's `text` when well typed (`lines` a list of str, `context` and `report` str), else None."""
    found = (result or {}).get("text")
    if not isinstance(found, dict) or not isinstance(found.get("lines"), list):
        return None
    if not all(isinstance(line, str) for line in found["lines"]):
        return None
    return found if all(isinstance(found.get(key), str) for key in ("context", "report")) else None


def hits(result: dict | None) -> int:
    return len((result or {}).get("plans") or []) + len((result or {}).get("research") or [])


def lines(result: dict | None) -> list[str]:
    """The CLI's line per hit (plans first); `[overlap unchecked]` without a checked answer, `[]` for an empty one."""
    found = text(result)
    return [UNCHECKED] if found is None else list(found["lines"])


def context_line(result: dict | None) -> str:
    """The Context line for the new folder's plan.md / spec.md: the CLI's own, or the unchecked line."""
    found = text(result)
    return f"- Overlap: {UNCHECKED} (hal2-cli-plans overlap missing or failed)." if found is None else found["context"]


def write(folder: Path, result: dict | None, name: str = "overlap.json") -> Path | None:
    """`overlap.json` in `folder` (the answer verbatim), None when nothing was checked."""
    if result is None:
        return None
    target = Path(folder) / name
    target.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return target


def report(result: dict | None) -> str:
    """The text printed (stderr) after the start: the CLI's report (the hits and the settle hint, or `overlap:
    none`), or `overlap: overlap unchecked`."""
    found = text(result)
    return f"overlap: {UNCHECKED}" if found is None else found["report"]


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
