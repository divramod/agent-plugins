"""The farmer skill's helpers, imported from the sibling folder `../../farmer/scripts` by path (hal2 plan 0268, D16).

Each module is optional: without the farmer skill the module is None and the facts it gives are left out (the log's
asks and acks), while the few git facts the table cannot do without (the main checkout, the worktrees, the plans/LEAD
marker) have a small fallback here. Appended to sys.path, so the skill's own module names win.
"""

import importlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import sibling  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)
try:
    FARMER = sibling("farmer") / "scripts"
except FileNotFoundError:  # the farmer skill is optional here
    FARMER = Path("/nonexistent-farmer-skill")
BUSY = {"working", "starting"}  # the farmer's mtm_scan.BUSY


def load(name: str):
    """The farmer's module `name`, None when the farmer skill or the module is missing or fails to import."""
    if FARMER.is_dir() and str(FARMER) not in sys.path:
        sys.path.append(str(FARMER))
    try:
        return importlib.import_module(name)
    except Exception:  # noqa: BLE001  (a missing or broken farmer skill never fails the state call)
        return None


mtm_scan, acks, logstate, roles, lead_marker = (load(n) for n in ("mtm_scan", "acks", "logstate", "roles", "lead_marker"))
BUSY = mtm_scan.BUSY if mtm_scan else BUSY


def run(args: list[str], cwd: str | Path) -> str:
    try:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def main_checkout(repo: str) -> str:
    if mtm_scan:
        return mtm_scan.main_checkout(repo)
    common = run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], repo).strip()
    return str(Path(common).parent) if common else repo


def worktrees(main: str) -> list[dict]:
    """The linked worktrees (path, branch), the main checkout and prunable ones left out."""
    if mtm_scan:
        return mtm_scan.worktrees(main)
    items, cur = [], {}
    for line in run(["git", "worktree", "list", "--porcelain"], main).splitlines() + [""]:
        if not line:
            if cur.get("path") and cur["path"] != main and not cur.get("prunable"):
                items.append(cur)
            cur = {}
        elif line.startswith("worktree "):
            cur["path"] = line[9:]
        elif line.startswith("branch "):
            cur["branch"] = line[7:].removeprefix("refs/heads/")
        elif line.startswith("prunable"):
            cur["prunable"] = True
    return items


def _no_sessions(agents: list[dict]) -> dict[str, dict]:
    return {}


# The one lookup of live sessions (plan 0412, tmux and terminal host alike); without the farmer skill, no sessions (0426 D3).
agents_by_checkout = mtm_scan.agents_by_checkout if mtm_scan else _no_sessions


def foreman_of(path: str | Path) -> str | None:
    """The worktree named by the worktree's `plans/LEAD` (`<foreman-slot> <plan> <step>`), None without a usable marker."""
    if lead_marker:
        m = lead_marker.marker(path)
        return m.get("slot") if m and not m.get("bad") else None
    try:
        parts = (Path(path) / "plans" / "LEAD").read_text().split()
    except OSError:
        return None
    return parts[0] if len(parts) >= 3 and len(parts[0]) == 2 and parts[0].isdigit() else None
