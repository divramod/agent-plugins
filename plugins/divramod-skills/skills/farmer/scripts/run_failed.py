"""A failed `run` action's follow-up carries what the run said: its exit and its output's tail (the tollman,
2026-11-04: "make these scripts bullet proof now"). Before, a wake only named the command and asked the session to run
it again "to see why"; for a train's start that rerun could have pushed a second landing beside a live one."""

TAIL = 600


def failed(follow: dict, code: int, text: str) -> dict:
    """`follow` (an `on_fail` action) with the run's exit and output: the tail in its `text` (the wake's line),
    the last 2000 characters as its `output` (the evidence)."""
    tail = " ".join((text or "").split())[-TAIL:] or "no output"
    return {**follow, "output": (text or "")[-2000:], "text": f"{follow.get('text', '')} [exit {code}: {tail}]".strip()}
