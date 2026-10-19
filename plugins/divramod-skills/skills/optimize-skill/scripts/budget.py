"""The run's token ledger and its hard caps (plan 0390 step 1; research 0100 L14). Stdlib only.

A JSONL file in the run folder (`ledger.jsonl`). Its first line holds the caps (a changed cap
adds a newer one, which wins), every model call adds one line:

    {"kind": "caps", "at": <UTC>, "max_tokens": 5000000, "max_rollouts": 80}
    {"kind": "rollout" | "reflect" | "edit", "at": <UTC>, "tokens": <total>, "input", "output", "cache_read",
     "cache_creation", "cost_usd", ...the caller's fields (eval_id, candidate, epoch)}

Exact usage is charged (a rollout result's `usage`, stream.py). The one exception is a call cut off before its
`result` event (a timeout, a crash): its stream under-counts it, so the caller charges `floored(usage, estimate)`
(at least the largest call so far, else the estimate) and marks the line `floored`. `tokens` are processed
tokens: input + output + cache read + cache creation. A cap must be a positive number (ValueError otherwise). The loop calls `check()` before every model call: it raises
`BudgetExceeded` when the caps are reached or the call's estimate would pass them, so the run stops before the call;
a call that went over is still charged in full. Reopening the file reloads what was spent and keeps its caps.
"""

import datetime as dt
import json
from pathlib import Path

DEFAULT_MAX_TOKENS = 5_000_000
DEFAULT_MAX_ROLLOUTS = 80
KINDS = ("rollout", "reflect", "edit")
FIELDS = ("input", "output", "cache_read", "cache_creation")


class BudgetExceeded(Exception):
    """A hard cap is reached: the loop stops and keeps the best validated candidate."""


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def tokens(usage):
    """The processed tokens of a usage dict: its `total`, else the sum of its four fields."""
    usage = usage or {}
    if usage.get("total") is not None:
        return int(usage["total"])
    return sum(int(usage.get(key) or 0) for key in FIELDS)


def floored(usage, minimum):
    """`usage` whose `total` is at least `minimum`: the charge of a call cut off before its result event."""
    out = dict(usage or {})
    out["total"] = max(tokens(out), int(minimum or 0))
    return out


def _cap(name, given, saved, default):
    value = int(given if given is not None else saved if saved is not None else default)
    if value <= 0:
        raise ValueError(f"{name} must be a positive number, got {value}")
    return value


def _lines(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            out.append(entry)
    return out


class Ledger:
    """The ledger at `path`; caps given here win (a changed cap adds a caps line), else the file's newest caps
    line, else the defaults."""

    def __init__(self, path, max_tokens=None, max_rollouts=None):
        self.path = Path(path)
        lines = _lines(self.path)
        caps = next((line for line in reversed(lines) if line.get("kind") == "caps"), {})
        self.max_tokens = _cap("max_tokens", max_tokens, caps.get("max_tokens"), DEFAULT_MAX_TOKENS)
        self.max_rollouts = _cap("max_rollouts", max_rollouts, caps.get("max_rollouts"), DEFAULT_MAX_ROLLOUTS)
        self.spent = sum(int(line.get("tokens") or 0) for line in lines if line.get("kind") in KINDS)
        self.cost_usd = sum(float(line.get("cost_usd") or 0) for line in lines if line.get("kind") in KINDS)
        self.rollouts = sum(1 for line in lines if line.get("kind") == "rollout")
        if not caps or (self.max_tokens, self.max_rollouts) != (caps.get("max_tokens"), caps.get("max_rollouts")):
            self._append({"kind": "caps", "at": _now(), "max_tokens": self.max_tokens,
                          "max_rollouts": self.max_rollouts})

    def _append(self, entry):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def remaining(self):
        return {"tokens": max(self.max_tokens - self.spent, 0), "rollouts": max(self.max_rollouts - self.rollouts, 0)}

    def would_exceed(self, estimate=0, kind="rollout"):
        """Why the next call of `kind` with `estimate` tokens may not run, or None when it may."""
        if self.spent >= self.max_tokens:
            return f"token cap reached: {self.spent} of {self.max_tokens}"
        if self.spent + max(int(estimate or 0), 0) > self.max_tokens:
            return f"token cap: {self.spent} spent + {int(estimate)} estimated > {self.max_tokens}"
        if kind == "rollout" and self.rollouts >= self.max_rollouts:
            return f"rollout cap reached: {self.rollouts} of {self.max_rollouts}"
        return None

    def check(self, estimate=0, kind="rollout"):
        """Raise BudgetExceeded when the next call may not run (call before every model call)."""
        reason = self.would_exceed(estimate, kind)
        if reason:
            raise BudgetExceeded(reason)

    def charge(self, usage, kind="rollout", cost_usd=0.0, **fields):
        """Record one finished call's exact usage; returns the ledger line."""
        if kind not in KINDS:
            raise ValueError(f"unknown kind: {kind!r}")
        usage = usage or {}
        entry = {"kind": kind, "at": _now(), "tokens": tokens(usage)}
        entry.update({key: int(usage.get(key) or 0) for key in FIELDS})
        entry["cost_usd"] = float(cost_usd or 0)
        entry.update(fields)
        self._append(entry)
        self.spent += entry["tokens"]
        self.cost_usd += entry["cost_usd"]
        self.rollouts += kind == "rollout"
        return entry

    def summary(self):
        return {"spent": self.spent, "rollouts": self.rollouts, "cost_usd": round(self.cost_usd, 6),
                "max_tokens": self.max_tokens, "max_rollouts": self.max_rollouts, "remaining": self.remaining()}
