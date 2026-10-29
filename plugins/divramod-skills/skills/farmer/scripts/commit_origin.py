"""The origin paragraph of the farmer's own commits (hal2 plan 0355 D2): `-m "Worktree: <field>"`, none where the
farm's commits are neutral (hal2 plan 0409 D15: no trailer names a field; planread asks `hal2-cli-plans commits`
only where the checkout has a `hal.farm`)."""
import sys
from pathlib import Path

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import load  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)

planread = load("plan", "planread", __file__)


def paragraph(top: str) -> list[str]:
    """The `-m` arguments naming the field `top` as a commit's origin; none for a neutral farm."""
    return [] if planread.neutral(top) else ["-m", f"Worktree: {Path(top).name}"]
