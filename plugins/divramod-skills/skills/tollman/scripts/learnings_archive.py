#!/usr/bin/env python3
"""Archiving learnings (hal2 plan 0490 step 14, decision D15): an entry whose case is ended (fixed in a commit,
taken by a plan) leaves the rules the tollman reads at every act and moves into the file's last section, `## Archive`.

    learnings.py [--role <name> | --dir <folder>] archive <n> [<n> ...] --why <commit|plan>

Each moved entry keeps its whole section and gains `**Archived:** <UTC date> <why>`. `learnings.read` (so `rules`,
`untaken` and verdicts.py's review) stops at the `## Archive` heading; `learnings.add` still counts the archived
numbers, so a number is never reused, and puts a new entry before the section. An unknown or already archived number
is left out of the result (the CLI exits 1 when nothing moved). Stdlib only.
"""

import datetime as dt

import learnings

HEADING = "## Archive"


def archive(directory, numbers, why, today=None):
    """Move the entries `numbers` into `## Archive`, return the numbers moved, sorted. `why` names the commit or plan
    that ended them (never empty)."""
    why = " ".join(str(why).split())
    if not why:
        raise ValueError("archive needs --why <commit|plan>")
    stamp = f"{today or dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d')} {why}"
    with learnings.locked(directory):
        path = directory / learnings.FILE
        if not path.is_file():
            return []
        text = path.read_text()
        lines = text.splitlines()
        moving = sorted((e for e in learnings.parse(text) if e.n in numbers), key=lambda e: e.start)
        if not moving:
            return []
        blocks = []
        for e in moving:
            block = lines[e.start:e.end]
            while block and not block[-1].strip():
                block.pop()
            blocks.append(block + [f"**Archived:** {stamp}"])
        gone = {i for e in moving for i in range(e.start, e.end)}
        kept = [l for i, l in enumerate(lines) if i not in gone]
        has_section = any(learnings.ARCHIVE.match(l) for l in kept)
        out = "\n".join(kept).rstrip("\n") + "\n"
        if not has_section:
            out += f"\n{HEADING}\n\nEntries whose case is ended: `rules`, `untaken` and the verdicts skip them.\n"
        out += "".join("\n" + "\n".join(b) + "\n" for b in blocks)
        learnings._write(path, out)
        return sorted(e.n for e in moving)
