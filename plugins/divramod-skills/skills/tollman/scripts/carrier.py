#!/usr/bin/env python3
"""The carrier's git (hal2 plan 0313 steps 1 and 14): the tollman's field carries every train, and each train's
landing pushes its head to the field's remote branch (`origin/tollman-<repo>`) without force. A train that does
not land leaves its head there, and the next train's push would be refused as not a fast-forward. `push_base` puts
the remote branch back on a base with a leased push (D2, D6, D11): a breakup on the dead train's base, a new train's
form on its own base."""

import subprocess

Done = tuple[int, str]  # the exit code and what happened, one line


def git(top: str, *args: str) -> Done:
    p = subprocess.run(["git", *args], cwd=top, capture_output=True, text=True, timeout=600)
    return p.returncode, (p.stdout + p.stderr).strip()


def push_base(top: str, field: str, base: str) -> str:
    """The carrier's remote branch back on `base` (plan 0313, D2, D6): leased on the tip the remote has now, never a
    bare force; a failure is told, the local field stands as it is. "": nothing to push (no remote branch, or its tip
    is in the base's history: the base itself, or a train that landed before; its next push fast-forwards)."""
    ref = "refs/heads/" + (git(top, "branch", "--show-current")[1] or field)
    code, out = git(top, "ls-remote", "origin", ref)
    if code:
        return f"origin's {ref} not read, it may still hold the dead train: {out[-200:]}"
    tip = next((w[0] for w in (line.split() for line in out.splitlines()) if w[1:] == [ref]), "")
    if not tip or git(top, "merge-base", "--is-ancestor", tip, base)[0] == 0:  # a tip it lacks: not in the history
        return ""
    code, out = git(top, "push", "-q", f"--force-with-lease={ref}:{tip}", "origin", f"{base}:{ref}")
    if code:
        return f"origin's {ref} still holds the dead train {tip[:12]}, not pushed: {out[-200:]}"
    return f"origin's {ref} back on {base[:12]} (was {tip[:12]})"
