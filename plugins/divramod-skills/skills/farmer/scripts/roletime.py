"""One time shape for every farmer and tollman state file (hal2 plan 0530, record role-folder-formats).

Writers write RFC 3339 UTC with `Z` and whole seconds (`now`, `stamp`); readers (`parse`, `age`) take every shape the
live files hold (`Z`, `+hh:mm`, an offset-less legacy value = the machine's local time, a bare date) and return an
aware UTC datetime, so comparing, sorting and subtracting never raises "can't compare offset-naive and offset-aware".
"""

import datetime as dt
import re

_UTC = dt.timezone.utc


_FRACTION = re.compile(r"(\.\d+)")


def _six_digits(match):
    """Pad or cut a fraction to six digits: Python before 3.11 parses no other length."""
    return (match.group(1) + "000000")[:7]


def utcnow():
    """Return the current time as an aware UTC datetime (for the `now` argument of code that compares)."""
    return dt.datetime.now(_UTC)


def _aware(t):
    """Return `t` as an aware UTC datetime; a naive one is the machine's local time (DST-safe via astimezone)."""
    return t.astimezone(_UTC)


def stamp(t):
    """Return any datetime (naive = local) as `2026-10-31T09:52:24Z`, whole seconds."""
    return _aware(t).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def now(clock=None):
    """Return the current time as `2026-10-31T09:52:24Z`; `clock` is an injectable datetime for tests."""
    return stamp(clock if clock is not None else utcnow())


def parse(value):
    """Return `value` as an aware UTC datetime, or None for None, "", garbage or a non-string; never raises.

    Takes `Z`, `+hh:mm` offsets, fractional seconds, a naive value (the machine's local time) and a date only
    (midnight local).
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text[-1] in "zZ":
        text = text[:-1] + "+00:00"
    text = _FRACTION.sub(_six_digits, text, count=1)
    try:
        return _aware(dt.datetime.fromisoformat(text))
    except (ValueError, OverflowError, OSError):
        return None


def aware(t=None):
    """Return a `now` argument as an aware UTC datetime: None is the current time, a naive datetime local time, a
    string is parsed (None when it does not parse). For the entries that take a `now` from tests or other scripts."""
    if t is None:
        return utcnow()
    if isinstance(t, dt.datetime):
        return _aware(t)
    return parse(t)


def age(value, now):
    """Return `now - parse(value)` as a timedelta, or None when `value` does not parse.

    `now` is normalised the same way (a naive `now` is local time, a string is parsed); None if it is unusable too.
    """
    then = parse(value)
    if then is None:
        return None
    if isinstance(now, dt.datetime):
        current = _aware(now)
    else:
        current = parse(now)
    if current is None:
        return None
    return current - then
