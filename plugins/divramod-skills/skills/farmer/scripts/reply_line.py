"""The reply line that ends every message a role sends to a session, by the session's agent kind (hal2 plan 0731
D9, D11, D12): Claude Code answers by SendMessage; every other kind (codex, opencode, grok, antigravity), and a pane with
no listed row, runs the ack in its shell (`acks.py ack ...`, which records in the role's `log.jsonl` from any cwd)."""

import os
import re

CLAUDE = "claude"
SEND_MESSAGE = "Reply `ack {id}: started|done|refused <why>` by SendMessage to the {role} session."
SHELL = 'Reply by running `python3 {acks} ack {id} started|done|refused "<why>" --role {role} --repo {repo}`.'
DECISION = 'python3 {farmer} decision-check --message "<your message>" --repo {repo}'
_REPLY = re.compile(r"^(Reply `ack |Reply by running `python3 )")


def acks_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "acks.py")


def kind_of(agents: list[dict], pane: str | None = None, field: str | None = None, main: str = "") -> str | None:
    """The kind of the session at `pane` (else the field's session of the checkout `main`) in a `list --json`'s rows."""
    for a in agents or []:
        hit = pane and a.get("pane_id") == pane
        hit = hit or (not pane and field and a.get("slot") == field
                      and str(a.get("project") or "").rstrip("/") == main.rstrip("/"))
        if hit:
            return a.get("kind")
    return None


def line(kind: str | None, ack_id: str, role: str, repo: str) -> str:
    if (kind or "").lower() == CLAUDE:
        return SEND_MESSAGE.format(id=ack_id, role=role)
    return SHELL.format(acks=acks_path(), id=ack_id, role=role, repo=repo)


def swap(text: str, new: str) -> str:
    """`text` with its last line, when it is a reply line, replaced by `new` (a re-send to a pane of another kind)."""
    head, _, last = text.rpartition("\n")
    return f"{head}\n{new}" if head and _REPLY.match(last) else text


def decision_check(repo: str) -> str:
    """The command a non-Claude session runs for a decision check (D12)."""
    return DECISION.format(farmer=os.path.join(os.path.dirname(acks_path()), "farmer.py"), repo=repo)
