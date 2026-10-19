"""Parse `claude -p --output-format stream-json --verbose` output into a rollout's facts. Stdlib only.

The stream is one JSON event per line: `system/init`, then `assistant` and `user` messages (one event per content
block, the same `message.id` repeated), at the end one `result`. Usage is exact, never estimated (spike of plan 0390
step 1): the `result` event's `modelUsage` (per model, summed) is the cumulative count; `result.usage` is partial on
an `error_max_budget_usd` stop and the assistant events' `output_tokens` are only the stream's first value, so each
field is the largest of `modelUsage`, `result.usage` and the assistant messages summed by id. Without a `result`
event (a timeout, a crash) the assistant messages alone give it.
"""

import json

TEXT_LIMIT = 2000
USAGE_FIELDS = (("input", "input_tokens", "inputTokens"), ("output", "output_tokens", "outputTokens"),
                ("cache_read", "cache_read_input_tokens", "cacheReadInputTokens"),
                ("cache_creation", "cache_creation_input_tokens", "cacheCreationInputTokens"))


def events(text):
    """The stream's events; a line that is no JSON object is skipped."""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            out.append(event)
    return out


def empty_usage():
    return {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0, "total": 0}


def _with_total(usage):
    usage["total"] = usage["input"] + usage["output"] + usage["cache_read"] + usage["cache_creation"]
    return usage


def _int(value):
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _from_api(raw, index):
    """Our usage from an API usage dict (index 1: snake_case keys) or a modelUsage entry (index 2: camelCase)."""
    raw = raw if isinstance(raw, dict) else {}
    return {field[0]: _int(raw.get(field[index])) for field in USAGE_FIELDS}


def _sum(usages):
    total = {field[0]: 0 for field in USAGE_FIELDS}
    for usage in usages:
        for key in total:
            total[key] += usage[key]
    return total


def usage_of(evts):
    """The run's exact usage {input, output, cache_read, cache_creation, total} (see the module doc)."""
    messages = {}
    for event in evts:
        message = event.get("message") if event.get("type") == "assistant" else None
        if isinstance(message, dict) and isinstance(message.get("usage"), dict):
            messages[message.get("id") or id(message)] = _from_api(message["usage"], 1)
    candidates = [_sum(messages.values())]
    result = result_event(evts)
    if result:
        candidates.append(_from_api(result.get("usage"), 1))
        model_usage = result.get("modelUsage")
        if isinstance(model_usage, dict):
            candidates.append(_sum(_from_api(entry, 2) for entry in model_usage.values()))
    usage = {key: max(candidate[key] for candidate in candidates) for key in candidates[0]}
    return _with_total(usage)


def result_event(evts):
    for event in reversed(evts):
        if event.get("type") == "result":
            return event
    return None


def _cut(text):
    text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    return text if len(text) <= TEXT_LIMIT else text[:TEXT_LIMIT] + " [cut]"


def _result_text(content):
    if isinstance(content, list):
        return "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)


def _blocks(event):
    content = (event.get("message") or {}).get("content")
    return [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []


def transcript(evts):
    """The tool calls in order and a compact transcript (text, tool_use, tool_result; texts cut to 2000 chars)."""
    calls, steps = [], []
    for event in evts:
        kind = event.get("type")
        for block in _blocks(event) if kind in ("assistant", "user") else []:
            if kind == "assistant" and block.get("type") == "text" and block.get("text"):
                steps.append({"type": "text", "text": _cut(block["text"])})
            elif kind == "assistant" and block.get("type") == "tool_use":
                call = {"id": block.get("id"), "name": block.get("name"), "input": block.get("input") or {}}
                calls.append(call)
                steps.append({"type": "tool_use", "name": call["name"], "input": _cut(call["input"])})
            elif kind == "user" and block.get("type") == "tool_result":
                steps.append({"type": "tool_result", "is_error": bool(block.get("is_error")),
                              "text": _cut(_result_text(block.get("content")))})
    return calls, steps


def _last_text(steps):
    texts = [step["text"] for step in steps if step["type"] == "text"]
    return texts[-1] if texts else ""


def _error(result):
    if result is None:
        return "no result event"
    if result.get("is_error") or result.get("subtype") != "success":
        errors = result.get("errors") if isinstance(result.get("errors"), list) else []
        return "; ".join([str(result.get("subtype") or "error")] + [str(e) for e in errors])
    return None


def parse(text):
    """The facts of one stream: {final_text, tool_calls, skills, transcript, usage, cost_usd, num_turns, subtype,
    error}; `error` is None only for a `result` event with subtype `success`."""
    evts = events(text)
    calls, steps = transcript(evts)
    result = result_event(evts)
    final = result.get("result") if result and isinstance(result.get("result"), str) else _last_text(steps)
    return {"final_text": final, "tool_calls": calls,
            "skills": [str(c["input"].get("skill")) for c in calls
                       if c["name"] == "Skill" and isinstance(c["input"], dict) and c["input"].get("skill")],
            "transcript": steps, "usage": usage_of(evts),
            "cost_usd": float((result or {}).get("total_cost_usd") or 0),
            "num_turns": _int((result or {}).get("num_turns")), "subtype": (result or {}).get("subtype"),
            "error": _error(result)}
