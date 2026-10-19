"""Score rollout results against an eval's checks (plan 0390 step 2). Stdlib only, no model call.

`judge_eval(eval, result)` takes an eval of evalset.py and a rollout result of rollout.py (`final_text`,
`tool_calls`, `error`) and returns

    {"eval_id": str, "score": float, "error": str or None,
     "checks": [{"op", "passed": bool, "detail": str}]}

The score is the fraction of checks passed; a result with an `error` (or none at all) scores 0, its checks all
failed with the error as the detail. `judge_split(evals, results)` takes the evals of one split and the results by
eval id and returns `{"mean": float, "n": int, "evals": [judge_eval, ...]}`.
"""

import json
import re


def _text_check(check, text):
    op, value = check["op"], check["value"]
    if op == "contains":
        found = value in text
        return found, "found" if found else f"{value!r} not in the answer"
    if op == "not_contains":
        found = value in text
        return not found, f"{value!r} is in the answer" if found else "absent"
    found = re.search(value, text) is not None
    return found, "matched" if found else f"{value!r} does not match"


def _tool_check(check, calls):
    needle = check.get("input")
    for call in calls:
        if call.get("name") != check["name"]:
            continue
        if needle is None:
            return True, f"{check['name']} called"
        given = call.get("input")
        text = given if isinstance(given, str) else json.dumps(given, ensure_ascii=False, sort_keys=True)
        if needle in text:
            return True, f"{check['name']} called with {needle!r}"
    suffix = f" with {needle!r}" if needle is not None else ""
    return False, f"{check['name']} not called{suffix}"


def run_check(check, result):
    """(passed, detail) of one check on a rollout result."""
    op = check["op"]
    text = result.get("final_text") or ""
    if op == "max_chars":
        passed = len(text) <= check["value"]
        return passed, f"{len(text)} chars" + (" within" if passed else " over") + f" {check['value']}"
    if op == "tool_called":
        return _tool_check(check, result.get("tool_calls") or [])
    return _text_check(check, text)


def judge_eval(item, result):
    checks = item["checks"]
    eval_id = str(item["id"])
    error = "no result" if result is None else result.get("error")
    if error:
        failed = [{"op": c["op"], "passed": False, "detail": f"rollout failed: {error}"} for c in checks]
        return {"eval_id": eval_id, "score": 0.0, "error": error, "checks": failed}
    rows = []
    for check in checks:
        passed, detail = run_check(check, result)
        rows.append({"op": check["op"], "passed": bool(passed), "detail": detail})
    score = sum(1 for r in rows if r["passed"]) / len(rows)
    return {"eval_id": eval_id, "score": score, "error": None, "checks": rows}


def judge_split(evals, results):
    """Mean score over `evals`; `results` maps eval id (str or int) to its rollout result, a missing one scores 0."""
    by_id = {str(k): v for k, v in results.items()}
    judged = [judge_eval(e, by_id.get(str(e["id"]))) for e in evals]
    mean = sum(j["score"] for j in judged) / len(judged) if judged else 0.0
    return {"mean": mean, "n": len(judged), "evals": judged}
