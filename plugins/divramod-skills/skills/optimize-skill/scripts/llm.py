"""The optimizer's one-shot model call: reflection and edit proposals (plan 0390 step 3). Stdlib only.

    claude -p "<prompt>" --safe-mode --setting-sources "" --tools "" --strict-mcp-config --no-session-persistence
      --output-format stream-json --verbose --model <model> --max-turns 1 --max-budget-usd <usd>

No tools, no skills, plugins, CLAUDE.md or hooks (`--safe-mode`), no user, project or local settings (so no `env`
or `apiKeyHelper` there brings an API key back), a fresh context per call. The cwd is the caller's empty folder
(the loop's one per run, removed with it), else a temp folder removed after the call. The binary and the env scrub are rollout's
(`$OPTIMIZE_SKILL_CLAUDE`, the API keys dropped: the login pays); the stream is parsed by stream.py, so the usage is
exact. `call()` runs `ledger.check(estimate, kind)` before (BudgetExceeded stops the run before the call) and
`ledger.charge()` after, every call charged, also a failed one; a call cut off before its result event (a timeout, a
crash) is charged at least its estimate (budget.floored).

`call(...)` returns {"text": str, "usage": {...}, "cost_usd": float, "error": str or None, "truncated": bool,
    "duration_s": float}.
"""

import os
import tempfile

import budget
import proc
import rollout
import stream

DEFAULT_MODEL = "sonnet"
DEFAULT_BUDGET_USD = "0.50"
DEFAULT_TIMEOUT = 300
ESTIMATES = {"reflect": 65_000, "edit": 30_000}  # research 0100's cost table, per call


def command(claude, prompt, *, model=DEFAULT_MODEL, budget_usd=DEFAULT_BUDGET_USD):
    return [claude, "-p", prompt, "--safe-mode", "--setting-sources", "", "--tools", "", "--strict-mcp-config",
            "--no-session-persistence",
            "--output-format", "stream-json", "--verbose", "--model", model, "--max-turns", "1",
            "--max-budget-usd", str(budget_usd)]


def _run(argv, cwd, env, timeout):
    if cwd is not None:
        return proc.run(argv, cwd=str(cwd), env=env, stdin=b"", timeout=timeout)
    with tempfile.TemporaryDirectory(prefix="optimize-skill-llm-") as folder:
        return proc.run(argv, cwd=folder, env=env, stdin=b"", timeout=timeout)


def call(prompt, *, ledger, kind, model=DEFAULT_MODEL, estimate=None, budget_usd=DEFAULT_BUDGET_USD,
         timeout=DEFAULT_TIMEOUT, claude=None, env=None, cwd=None, **fields):
    """One tool-less call of `kind` (reflect, edit) charged to `ledger`; the dict of the module doc."""
    guess = ESTIMATES.get(kind, 0) if estimate is None else estimate
    ledger.check(guess, kind)
    argv = command(rollout.claude_binary(claude), prompt, model=model, budget_usd=budget_usd)
    child = _run(argv, cwd, rollout.scrub_env(dict(os.environ) if env is None else env), timeout)
    seconds = round(child["ms"] / 1000, 3)
    truncated = False
    if child["error"]:
        facts = dict(stream.parse(""), error=f"start: {child['error']}")
    else:
        facts = stream.parse(child["out"].decode("utf-8", errors="replace"))
        truncated = child["timed_out"] or facts["error"] == "no result event"
        if child["timed_out"]:
            facts["error"] = "timeout"
        elif facts["error"] == "no result event":
            facts["error"] = f"no result event (exit {child['code']}): {proc.tail(child['err'], 300).strip()}"
    usage = budget.floored(facts["usage"], guess) if truncated else facts["usage"]
    extra = {"floored": True} if truncated else {}
    ledger.charge(usage, kind=kind, cost_usd=facts["cost_usd"], model=model, error=facts["error"], **extra, **fields)
    return {"text": facts["final_text"] or "", "usage": facts["usage"], "cost_usd": facts["cost_usd"],
            "error": facts["error"], "truncated": truncated, "duration_s": seconds}
