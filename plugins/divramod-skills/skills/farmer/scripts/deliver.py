"""Templated messages to agent sessions without a model: typed into an idle session's empty prompt.

`send(pane, text)` types only when hal2 lists the agent in a resting state and its prompt box holds no draft
(no text typed by a person; the dim suggestion Claude Code shows there is no draft): hal2's own rule,
`hal2-cli-agents send --if-empty` (hal2 plan 0125), which exits 3 with the reason (busy, dialog, draft, no-agent)
and types nothing. `--submit` (hal2 plan 0139) sends it in the same call and confirms the session took it; when it
did not, hal2 removes the text again and exits 4, so no message is ever left in a box. Then the tick hands the
message to the woken farmer session as a relay (Claude Code's SendMessage queues for busy sessions).
"""

import json
import subprocess

READY = {"idle", "done", "sleeping"}
REFUSED = 3
NOT_SUBMITTED = 4


def cli(*args: str, timeout: int = 30) -> tuple[int, str]:
    code, out, _ = run(*args, timeout=timeout)
    return code, out


def run(*args: str, timeout: int = 30) -> tuple[int, str, str]:
    try:
        p = subprocess.run(["hal2-cli-agents", *args], capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, "", str(e)


def agent(pane: str) -> dict | None:
    code, out = cli("list", "--json")
    try:
        data = json.loads(out) if code == 0 else {}
    except json.JSONDecodeError:
        return None
    rows = data.get("list", []) if isinstance(data, dict) else data
    return next((a for a in rows if a.get("pane_id") == pane), None)


def if_empty(pane: str, text: str, states: set[str] = READY) -> list[str]:
    """The arguments of a send that types `text` only into a resting agent with an empty box; `states` beyond
    the resting ones are allowed with --allow-state."""
    extra = [arg for state in sorted(set(states) - READY) for arg in ("--allow-state", state)]
    return ["send", pane, text, "--paste", "--if-empty", "--submit", *extra]


def refusal(stderr: str) -> str:
    """hal2's reason from a refused send's stderr (`... not sent: draft: ...`, `... not submitted: not-taken: ...`)."""
    text = stderr.strip()
    for head in ("not sent: ", "not submitted: "):
        if head in text:
            return text.split(head, 1)[-1] or "refused"
    return text or "refused"


def old_cli(stderr: str) -> bool:
    """A hal2-cli-agents from before --submit (hal2 plan 0139) rejects it with its usage line."""
    return "send takes" in stderr and "--submit" not in stderr


def send(pane: str, text: str, states: set[str] = READY) -> str | None:
    """Type `text` and Enter into the agent at `pane`, confirmed. None when sent, else why it was not."""
    args = if_empty(pane, text, states)
    code, _, err = run(*args)
    if code == 1 and old_cli(err):
        code, _, err = run(*[a for a in args if a != "--submit"])
        if code == 0 and cli("send", pane, "enter", "--key")[0]:
            return "hal2-cli-agents send failed"
    if code in (REFUSED, NOT_SUBMITTED):
        return refusal(err)
    if code:
        return "hal2-cli-agents send failed"
    return None
