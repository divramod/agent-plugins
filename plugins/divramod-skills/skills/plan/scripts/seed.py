"""seed.py: the seed a plan grows from (research 0077, plan 0293 step 4): `plan.py new --seed <seedbag>#<n>` writes the
plan's Context line `- Seed: <seedbag>#<n> (<title>)` and marks the seed sent, through `hal2-cli-shooter` (the seed's
format is hal2's, read by hal2-nvim and hal9k: this module only calls the CLI). A global seedbag is written
`global:<seedbag>#<n>`. The CLI is `$HAL2_CLI_SHOOTER`, else `hal2-cli-shooter` on PATH; without it, or for a seed that is
unknown or already sent, the plan is still made and `marked` says why not. `plan.py` only wires this module in."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

ENV = "HAL2_CLI_SHOOTER"
NAME = "hal2-cli-shooter"
REF = re.compile(r"^(global:)?([a-z0-9_][a-z0-9_-]*)#([1-9][0-9]*)$")


class SeedError(Exception):
    """The `--seed` value is not `<seedbag>#<n>` or `global:<seedbag>#<n>`."""


def parse(value: str) -> tuple[str, str, bool]:
    """(seedbag, number, global) of `<seedbag>#<n>`; SeedError for anything else."""
    match = REF.match(value.strip())
    if not match:
        raise SeedError(f"--seed '{value}': write it as <seedbag>#<n> (global:<seedbag>#<n> for a global seedbag)")
    return match.group(2), match.group(3), bool(match.group(1))


def binary() -> str | None:
    """`$HAL2_CLI_SHOOTER` when it names a file, else the CLI on PATH; None when neither."""
    named = os.environ.get(ENV, "").strip()
    if named:
        return named if Path(named).expanduser().is_file() else None
    return shutil.which(NAME)


def worktree_name(root: Path, is_global: bool) -> str:
    """The name the shooter marks a sent seed with: the checkout's folder name (`main` for the main checkout);
    for a global seedbag `<repo>/<name>`."""
    is_worktree = (root / ".git").is_file()
    name = root.name if is_worktree else "main"
    return f"{root.parent.name if is_worktree else root.name}/{name}" if is_global else name


def run(root: Path, *args: str) -> subprocess.CompletedProcess | None:
    cli = binary()
    if cli is None:
        return None
    return subprocess.run([str(Path(cli).expanduser()), "shots", *args], cwd=root, capture_output=True, text=True)


def read(root: Path, value: str) -> dict:
    """{ref, title, why}: the open seed's title; `title` empty and `why` set when the CLI is missing, fails or the
    seed is not open (unknown, or already sent)."""
    bag, number, is_global = parse(value)
    ref = f"{'global:' if is_global else ''}{bag}#{number}"
    out = run(root, "list-open", bag, *(["--global"] if is_global else []), "--json")
    if out is None:
        return {"ref": ref, "title": "", "why": f"{NAME} is not installed"}
    if out.returncode != 0:
        return {"ref": ref, "title": "", "why": (out.stderr or out.stdout).strip() or f"{NAME} exited {out.returncode}"}
    try:
        shots = json.loads(out.stdout).get("shots", [])
    except (json.JSONDecodeError, AttributeError):
        return {"ref": ref, "title": "", "why": f"{NAME} printed no JSON"}
    shot = next((s for s in shots if s.get("file") == bag and str(s.get("number")) == number), None)
    if shot is None:
        return {"ref": ref, "title": "", "why": f"no open seed {number} in {bag} (unknown or already sent)"}
    return {"ref": ref, "title": " ".join(str(shot.get("title", "")).split()), "why": ""}


def context_line(info: dict) -> str:
    """The plan's Context line: `- Seed: <ref> (<title>)`, without the parentheses for a seed that was not read."""
    return f"- Seed: {info['ref']} ({info['title']})" if info["title"] else f"- Seed: {info['ref']}"


def mark(root: Path, info: dict) -> dict:
    """`info` with `marked`: true when the shooter marked the seed sent, else false with `why`. A seed that was not
    read as open is not marked."""
    if info["why"]:
        return {**info, "marked": False}
    bag, number, is_global = parse(info["ref"])
    out = run(root, "mark-sent", bag, number, "--worktree", worktree_name(root, is_global),
              *(["--global"] if is_global else []))
    if out is None or out.returncode != 0:
        why = f"{NAME} is not installed" if out is None else (out.stderr or out.stdout).strip() or f"exited {out.returncode}"
        return {**info, "marked": False, "why": why}
    return {**info, "marked": True}
