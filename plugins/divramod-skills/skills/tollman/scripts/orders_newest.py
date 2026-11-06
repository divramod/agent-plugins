"""Only the newest answer of a fix order counts (hal2 plan 0717 step 2, D3; tollman learning L265, train 56-5): a
foreman that answers `done fixed <sha>` again has superseded its older shas. The newest is the sha the train's `fixed`
line took, else the order's last answer. An older sha gets no proof run and no refusal for its foreman. Pure
filtering on the log and train lines the round already reads: nothing new on the critical path (plan 0490 D9)."""

import re

FIXED = re.compile(r"\bfixed\s+([0-9a-f]{7,40})\b")


def answer_shas(order_id: str, log: list[dict], what: str = "fix order") -> list[str]:
    """The shas the order's message's acks answered `done fixed <sha>`, oldest first."""
    asks = {e["id"] for e in log if e.get("kind") == "ask-ack" and e.get("id")
            and f"{what} {order_id} " in (e.get("text") or "")}
    return [m.group(1) for e in log if e.get("kind") == "ack" and e.get("id") in asks and e.get("what") == "done"
            and (m := FIXED.search(e.get("note") or ""))]


def same(a: str, b: str) -> bool:
    return a.startswith(b) or b.startswith(a)


def newest(order_id: str, rows: list[dict], log: list[dict]) -> str | None:
    """The sha that counts for the order: the one its `fixed` line took, else its last answer, else None."""
    taken = [e.get("sha") for e in rows if e.get("kind") == "fixed" and e.get("id") == order_id and e.get("sha")]
    return taken[-1] if taken else next(iter(reversed(answer_shas(order_id, log))), None)


def superseded(order_id: str, sha: str, rows: list[dict], log: list[dict]) -> str | None:
    """The newer sha that supersedes `sha` when `sha` is one of the order's older answers, else None (a sha the
    order never answered, a manual `fixed`, is no answer to supersede)."""
    best = newest(order_id, rows, log)
    older = any(same(sha, s) for s in answer_shas(order_id, log))
    return best if best and older and not same(sha, best) else None
