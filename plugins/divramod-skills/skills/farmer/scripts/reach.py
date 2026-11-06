"""The one way the farmer reaches a field's session: by its pane, found by the field's cwd, never by a name (hal2 plan
0695 step 40, D41 H8). A send by name (SendMessage, ListAgents' `<field>-<id>`) failed for busy sessions (02-54,
farmer-hal2-0f, 2026-11-05); `hal2-cli-agents list --json` names each agent's field and `project` (its checkout), so
the field's pane is the agent in that field whose project is this farm's, and `hal2-cli-agents send` types
into it. A busy (`working`) session takes the text too: Claude Code queues what is typed into a working session.
`acks.py instruct --send`, the tick's relays and `farmer.py stop` all send through `send` here.
"""

import json

import deliver

BUSY = deliver.READY | {"working"}


def pane_in(agents: list[dict], field: str, main: str) -> str | None:
    """The pane of the agent working in `field` of the repository `main`, else None."""
    for a in agents:
        if a.get("slot") == field and str(a.get("project") or "").rstrip("/") == main.rstrip("/"):
            return a.get("pane_id")
    return None


def agents_listed() -> list[dict]:
    code, out = deliver.cli("list", "--json")
    try:
        data = json.loads(out) if code == 0 else {}
    except ValueError:
        return []
    rows = data.get("agents", []) if isinstance(data, dict) else data
    return rows if isinstance(rows, list) else []


def pane_of(field: str, main: str) -> str | None:
    return pane_in(agents_listed(), field, main)


def send(field: str, main: str, text: str, pane: str | None = None,
         agents: list[dict] | None = None) -> tuple[str | None, str | None]:
    """Type `text` into the field's session, busy or resting: (the pane, None when sent else why not). No pane: (None,
    "no session"). `agents`: a round's one `list --json` (tick's `agent_rows`, plan 0480 step 02.02), else read here."""
    pane = pane or pane_in(agents if agents is not None else agents_listed(), field, main)
    if not pane:
        return None, "no session"
    return pane, deliver.send(pane, text, BUSY)
