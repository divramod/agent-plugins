"""What prune reads once per plan instead of once per field (hal2 plan 0480 step 04.02, D5; research 0118 #6).

`Processes`: one `ps -A` for every field's "is a build running in it" (cleanup's `busy`). `Refs`: one
`git for-each-ref` with `%(ahead-behind:<default>)` for every field's "commits origin's default branch lacks". Both
read lazily on first use, once, and hand a caller that cannot use the answer (no listing, no git ahead-behind, a HEAD
that is no branch tip) nothing, so it asks the old way: a batch never makes the proof weaker. The executor takes
fresh ones for every action (its `collect({slot})`), so a field is re-proved against the moment of the action.
"""

import importlib.util
import os
import threading

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import tick
from skillpath import sibling

CLEANUP = sibling("cleanup") / "scripts/cleanup.py"
_module = []


def cleanup():
    """cleanup.py loaded as a module (import-safe: its commands run only under `__main__`), for `busy_hits`."""
    if not _module:
        spec = importlib.util.spec_from_file_location("cleanup_busy", CLEANUP)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _module.append(mod)
    return _module[0]


class Processes:
    """One process listing for many fields; `running(path)` is cleanup's `busy` on it. An empty or unreadable
    listing counts as busy (never "idle" from a failed `ps`)."""

    def __init__(self, listing: str | None = None):
        self._text, self._lock = listing, threading.Lock()

    def text(self) -> str:
        with self._lock:
            if self._text is None:
                try:
                    self._text = cleanup().process_listing()
                except OSError:
                    self._text = ""
            return self._text

    def running(self, path: str) -> bool:
        text = self.text()
        return not text.strip() or bool(cleanup().busy_hits(os.path.realpath(path), text))


class Refs:
    """The local branches with their commit and how far they are ahead of `base` (origin's default branch), read by one
    `git for-each-ref` from the main checkout (every worktree shares the refs)."""

    def __init__(self, main: str, base: str | None = None):
        self.main, self._base, self._rows, self._ok, self._lock = main, base, None, False, threading.Lock()

    @property
    def base(self) -> str:
        with self._lock:
            if self._base is None:
                self._base = tick.default_ref(self.main)
            return self._base

    def rows(self) -> list[tuple[str, str, int]] | None:
        """[(branch, sha, commits ahead of base)], None when git cannot say (older than 2.41, an error)."""
        base = self.base
        with self._lock:
            if self._rows is None:
                out = tick.git(self.main, "for-each-ref", f"--format=%(refname) %(objectname) %(ahead-behind:{base})",
                               "refs/heads")
                rows = []
                for line in out.splitlines():
                    parts = line.split()
                    if len(parts) != 4 or not parts[2].isdigit():
                        rows = None
                        break
                    rows.append((parts[0].removeprefix("refs/heads/"), parts[1], int(parts[2])))
                self._rows = rows if rows is not None else []
                self._ok = rows is not None and bool(out)
            return self._rows if self._ok else None

    def ahead(self, head: str | None) -> int | None:
        """Commits `head` has that base lacks, when a local branch is at `head`; else None (ask rev-list)."""
        rows = self.rows() if head else None
        return next((n for _, sha, n in rows if sha == head), None) if rows else None

    def side(self, slot: str) -> list[tuple[str, int]] | None:
        """[(branch, ahead)] for the side branches `<slot>-*` that are ahead of base; None when git cannot say."""
        rows = self.rows()
        if rows is None:
            return None
        return [(name, n) for name, _, n in rows if name.startswith(f"{slot}-") and n]
