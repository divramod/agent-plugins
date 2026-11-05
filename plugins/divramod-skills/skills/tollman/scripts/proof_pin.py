#!/usr/bin/env python3
"""A car's records checker pin against its own crate (hal2 plan 0614 step 2, L53): proof.py's light check `pin`, for a
crop that changes `.hal/records.toml`.

Train 8 of 2026-10-20 (01+50+54+36+07) went red at its generated files: car 07 pinned `checker = ">=0.8.0"`, the
version its own landing's bump would give hal2-records, while the head's crate still said 0.7.0. The train's
generated step runs before the bump with the candidate's 0.7.0 checker, so such a pin can never pass; installing a
CLI from the candidate gives 0.7.0 too. So a pin whose minimum is above the head's own `hal2-records` crate version
is the car's red: pin the current version in this landing, raise it in a later one, never install a CLI to get past
it. Both files are read at the hitched head (`git show <head>:<path>`), so a scratch proves it the same; a file
that cannot be read or parsed is a check that cannot run (127: skipped, never red).
"""

import re
import tomllib

PIN = ".hal/records.toml"
CRATE = "code/rust/libs/hal2-records/Cargo.toml"
MINIMUM = re.compile(r"^\s*(?:>=|\^|~|=)?\s*v?(\d+(?:\.\d+){0,2})\s*$")


def wanted(files: list[str]) -> bool:
    """Whether the crop changes the pin's file."""
    return PIN in files


def version(text: str) -> tuple[int, ...] | None:
    """`0.8.0`, `>=0.8.0` as (0, 8, 0), padded to three parts; None for another form (`<1`, `>=0.7, <0.9`)."""
    m = MINIMUM.match(text or "")
    return tuple(int(p) for p in m[1].split(".")) + (0,) * (2 - m[1].count(".")) if m else None


def read(field: str, head: str, path: str, run) -> dict | None:
    code, text = run(["git", "show", f"{head}:{path}"], field)
    try:
        return tomllib.loads(text) if code == 0 else None
    except tomllib.TOMLDecodeError:
        return None


def check(field: str, head: str, run) -> tuple[int, str]:
    """proof.py's `(exit, text)`: 1 with a `.hal/records.toml: ...` line when the pin is above the crate's version."""
    pin, crate = read(field, head, PIN, run), read(field, head, CRATE, run)
    if pin is None or crate is None:
        return 127, ""
    want, have = str(pin.get("checker") or ""), str((crate.get("package") or {}).get("version") or "")
    low, own = version(want), version(have)
    if not want or not low or not own:
        return (0, "") if not want else (127, "")
    if low <= own:
        return 0, ""
    return 1, (f"{PIN}: checker pin `{want}` is above the head's own hal2-records crate version {have} ({CRATE}): "
               f"the train's generated step runs the candidate's {have} checker before the landing's bump, so it can "
               f"never pass; pin the current version (`>={have}`) in this landing and raise it in a later one, never "
               "install a CLI to get past it (L53)")
