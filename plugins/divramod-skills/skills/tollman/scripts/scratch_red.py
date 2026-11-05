"""A records-check red in its state-scratch phase that no car caused (plan 0623 step 4, D6, learning L151): hal2-cli-state
(`code/rust/apps/hal2-cli-state/src/scratch.rs`) fails with `a test run left ~/<file> under the real roots, which no
declared store covers` when a file appeared under the user's real roots while its suites ran. On the shared runner user
another job can write them: train 32 attempt 5 (run 41144448386, hz01) was red with claude `usage-ids.bin` and
`usage-index.json`, which no car writes. Such a finding whose named files no car's diff touches is a runner red: the
same train is retried, no car is ordered. A suite failure (`a suite failed: ...`) or an undeclared write of a test
(`wrote ~/<file>, which no declared store covers`) stays the car's.

`read` parses the log text (pure); `touching` names the cars whose files could write a finding's path: the finding's
file name or its stem (`usage-ids.bin`, `usage-ids`) is part of a car's changed file path, `_` and `-` alike (a car
that changes the code writing a store changes a file named like it). Conservative: a doubt keeps the red the car's.
"""

import re

STRAY = re.compile(r"a test run left ~/(?P<path>\S+) under the real roots")
SUITE = re.compile(r"a suite failed:")
WROTE = re.compile(r"wrote ~/\S+, which no declared store covers")
SHORT = 4  # a name shorter than this is too common to tie a car to a store


def read(text: str) -> dict | None:
    """{paths: [the files left under the real roots]}, or None: no such finding, or a suite that failed or an
    undeclared write of a test beside it (the car's own)."""
    text = text or ""
    paths = sorted({m["path"].rstrip(".,;:") for m in STRAY.finditer(text)})
    if not paths or SUITE.search(text) or WROTE.search(text):
        return None
    return {"paths": paths}


def names(path: str) -> set[str]:
    """The file name of a path and its stem, lower case with `-` for `_`."""
    leaf = path.rstrip("/").rsplit("/", 1)[-1].lower().replace("_", "-")
    stem = "" if leaf.startswith(".") else leaf.split(".", 1)[0]
    return {n for n in (leaf, stem) if len(n) >= SHORT}


def touching(paths: list[str], cars: list[dict]) -> list[str]:
    """The fields of the cars whose changed files could write one of the paths (see the module doc)."""
    wanted = set().union(*(names(p) for p in paths)) if paths else set()
    return sorted({c.get("field") for c in cars or [] for f in c.get("files") or []
                   if any(n in f.lower().replace("_", "-") for n in wanted)} - {None})


def runner(found: dict | None, cars: list[dict]) -> dict | None:
    """The scratch evidence {paths, touched} when `found` is a runner red: no car touches any path; else None."""
    if not found:
        return None
    touched = touching(found["paths"], cars)
    return None if touched else {"paths": found["paths"], "touched": touched}


def match(scratch: dict) -> str:
    """The evidence's words: what was left and that no car writes it."""
    return "state-scratch: a test run left ~/" + ", ~/".join(scratch["paths"][:3]) + " under the real roots; no car writes them"
