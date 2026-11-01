"""A stalled fake program for the tests of bounded.run (the farmer's test_bounded, the tollman's test_bounded_sites),
free of the machine's load (hal2 plan 0532 step 16).

A tiny time limit cuts the stall; on a loaded machine the fake may not even have started within it, and a test then
saw one try, not two. `Ready` stands in for `subprocess.Popen` and starts a stalled fake's first limit only once the
fake says it stalls (a line in $READY), GUARD at most; a fake that answers is never held. The proof that the limit cut
a stall is that the stall never reached its end ($DONE), not a wall time. `FAKE_SLOW=<s>` delays every fake's start:
a loaded machine without the load."""

import os
import subprocess
import time
from pathlib import Path
from unittest import mock

GUARD = 120  # seconds: the outer guard of a wait for an event; only a hang meets it
STALL = 'echo x >> "$COUNT"\nsleep 300 &\necho $! > "$CHILD"\necho x >> "$READY"\nwait\necho x >> "$DONE"\n'
POPEN = subprocess.Popen


def lines(path: Path) -> int:
    return len(path.read_text().split()) if path.exists() else 0


class Ready(POPEN):
    """`subprocess.Popen` whose first time limit of a stalled fake (a name in `stalls`) starts once the fake stalls."""

    stalls: set = set()

    def __init__(self, args, *a, **kw):
        self._ready = Path(os.environ.get("READY", "/nonexistent"))
        self._before = lines(self._ready)
        self._waited = False
        super().__init__(args, *a, **kw)

    def communicate(self, input=None, timeout=None):
        name = os.path.basename(str(self.args[0])) if isinstance(self.args, (list, tuple)) and self.args else ""
        if timeout is not None and not self._waited and name in Ready.stalls:
            self._waited = True
            end = time.monotonic() + GUARD
            while lines(self._ready) <= self._before and self.poll() is None and time.monotonic() < end:
                time.sleep(0.01)
        return super().communicate(input, timeout)


def install(case, folder: Path) -> dict:
    """`Ready` as `subprocess.Popen` for the test `case`; the environment of the stall's files in `folder`."""
    Ready.stalls = set()
    patcher = mock.patch.object(subprocess, "Popen", Ready)
    patcher.start()
    case.addCleanup(patcher.stop)
    return {"CHILD": str(folder / "child"), "READY": str(folder / "ready"), "DONE": str(folder / "done")}


def fake(path: Path, body: str) -> None:
    """A fake program at `path` (started $FAKE_SLOW seconds late); a STALL body is held by `Ready`."""
    path.write_text(f'#!/bin/sh\nsleep "${{FAKE_SLOW:-0}}"\n{body}')
    path.chmod(0o755)
    if body == STALL:
        Ready.stalls.add(path.name)


def cut(case, folder: Path) -> None:
    """The stall was cut by its limit: its `wait` never ended."""
    case.assertFalse((folder / "done").exists(), "the stall ran to its end: no limit cut it")
