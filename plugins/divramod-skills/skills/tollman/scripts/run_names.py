"""Every name of a train's run, fix and resolve (hal2 plan 0610 D18; roles/tollman/ROLE.md's table, the user,
2026-11-04: "it should be systematic, like tollman-train-51-1"; "formalize and standardize that so that we will never
have these different train names and unsure work tree fix names. This needs to be bulletproof too"). The yard's
`roles/tollman/train_names.py` makes the same names (a published skill cannot import it; test_train_wt pins both).

  carrier of run <a> of train <n>   branch train-<n>-<a> (landed on land/train-<n>-<a>)   worktree tollman-train
  a foreman's fix                   <NN>-train-<n>-<a>-fix (resolve: -resolve)            worktree <NN>-fix
  the tollman's own fix             tollman-train-<n>-<a>-fix                             worktree tollman-fix

Each fix starts from `origin/train-<n>-<a>`, `<a>` the run of the carrier it starts from (`run_of`); one branch per
field and run, a second order adds to it. The worktree folders are kept, never renamed (the user, 2026-11-04: "The
warm cache is also really important"). A train without a number (formed before plan 0398) keeps the legacy names
`<NN>-train-fix`, `<NN>-train-resolve` and `tollman-train-fix` (also the barn's red without a train, own_fix.py).
"""

import re

KEPT = "tollman-train"  # the carrier's kept worktree
OWN_FIX = "tollman-train-fix"  # the legacy own fix branch
MAIN = "main"  # orders.MAIN: the tollman's own fix order
CARRIER = re.compile(r"^train-([1-9]\d*)-([1-9]\d*)$")
FIX = re.compile(r"^(\d{2}|tollman)-train-[1-9]\d*-[1-9]\d*-(fix|resolve)$")
RAN = ("landing", "red", "fixing", "paused")  # a train whose last start is the run a fix starts from


def carrier_name(n, a) -> str:
    """The carrier's branch of run `a` of train `n`: `train-<n>-<a>`."""
    if int(n) < 1 or int(a) < 1:
        raise ValueError("train and run start at 1")
    return f"train-{int(n)}-{int(a)}"


def fix_name(field: str, n, a, kind: str = "fix") -> str:
    """`<NN>-train-<n>-<a>-fix` (or `-resolve`); the tollman's own (`main`): `tollman-train-<n>-<a>-fix`."""
    who = "tollman" if field in (MAIN, "tollman") else str(field)
    if not re.fullmatch(r"\d{2}|tollman", who) or kind not in ("fix", "resolve"):
        raise ValueError(f"no fix name for field {field!r}, kind {kind!r}")
    return f"{who}-{carrier_name(n, a)}-{kind}"


def fix_worktree(field: str) -> str:
    """The kept worktree folder a field's fixes and resolves are worked in: `<NN>-fix`, the tollman's `tollman-fix`."""
    return "tollman-fix" if field in (MAIN, "tollman") else f"{field}-fix"


def run_of(train: dict) -> int:
    """The run of the carrier a fix starts from: the last start while it lands or after its red, else the next."""
    starts = int(train.get("starts") or 0)
    return max(starts, 1) if train.get("state") in RAN else starts + 1


def fix_branch(train: dict, field: str, kind: str = "fix") -> str:
    """The branch of `field`'s fix (or resolve) in the standing `train`; a train without a number: the legacy name."""
    if train.get("number"):
        return fix_name(field, train["number"], run_of(train), kind)
    return OWN_FIX if field == MAIN and kind == "fix" else f"{field}-train-{kind}"


def base_ref(train: dict, current: str) -> str:
    """The carrier's remote branch a fix starts from: `train-<n>-<a>` of a numbered train, else `current`."""
    return carrier_name(train["number"], run_of(train)) if train.get("number") else current


def base_of(branch: str) -> str | None:
    """The carrier's run `train-<n>-<a>` a systematic fix or resolve branch starts from, None for a legacy name."""
    m = FIX.match(branch) and re.search(r"-(train-[1-9]\d*-[1-9]\d*)-(?:fix|resolve)$", branch)
    return m.group(1) if m else None
