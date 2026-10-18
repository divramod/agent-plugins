"""What the tollman's page reads (hal2 plan 0366 D9): the raw merge queue. `state_sources.queue_state` keeps only the
position, holding and state of each ticket; the tollman's page also needs the ready mark, the train and the smuggle,
so it reads `hal2-cli-git worktree queue --json` itself. Read-only; None when the tool gives nothing.
"""

import state_sources as src


def raw_queue(main: str) -> dict | None:
    """`{"queue": [ticket dicts as hal2-cli-git prints them], "mode": {...} | None}`; None when unknown."""
    raw = src.tool_json(["hal2-cli-git", "worktree", "queue", "--json"], main)
    if not isinstance(raw, dict) or not isinstance(raw.get("queue"), list):
        return None
    return {"queue": [t for t in raw["queue"] if isinstance(t, dict)],
            "mode": raw["mode"] if isinstance(raw.get("mode"), dict) else None}
