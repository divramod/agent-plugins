"""The SendMessage name of a field's live Claude session (hal2 plan 0490 step 11, L77 and L98 of the tollman): a
relay carries it as `to`, so the woken session never picks a target by its field number (ListAgents names sessions
`<field>-<id>` without the farm: hal2's field 03 got voice-agent's 03-1a).

Claude Code keeps one file per running session, `<config dir>/sessions/<pid>.json` (`CLAUDE_CONFIG_DIR`, else
`~/.claude`), with its `cwd` and `name`; the field's is the newest live one whose cwd is the field's checkout. None
when no live session of the field has a socket name.
"""

import json
import os
from pathlib import Path


def folder() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "sessions"


def alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    return True


def name_of(checkout: str | Path, where: Path | None = None) -> str | None:
    """The `name` of the newest live session whose cwd is `checkout`."""
    here, best = str(Path(checkout).resolve()), None
    for f in (where or folder()).glob("*.json"):
        try:
            s = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(s, dict) or not s.get("name") or not s.get("cwd"):
            continue
        if str(Path(s["cwd"]).resolve()) == here and alive(s.get("pid")):
            if best is None or (s.get("updatedAt") or 0) > (best.get("updatedAt") or 0):
                best = s
    return best["name"] if best else None


def field_path(main: str, slot: str) -> Path:
    """A field's checkout: `~/.hal/git/worktree/<main checkout's folder>/<slot>` (roles.slot_dir's root)."""
    return Path.home() / ".hal/git/worktree" / Path(main).name / slot
