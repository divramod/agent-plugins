"""The role views of the state page (hal2 plan 0366): `VIEWS[role](data, ctx) -> (title, sections)`, pure.

`data` is `state.collect`'s dict (its line under the table stands under every page's title), `ctx` {"role", "repo"
(the repository's name), "checkout" (the own checkout's row name), "top", "main"}. Every role starts on `fallback`, today's table as one section; each later step registers
its own view from `view_<role>.py` here.
"""

import role as roles
import state_table
import view_farmer
import view_foreman
import view_goals
import view_steward
import view_tollman

ROLE_TITLES = {"unknown": "state"}


def title_of(ctx: dict) -> str:
    """`<repo> · <role> <checkout>`, e.g. `hal2 · foreman 10`; without the checkout for the main checkout and a
    role's own worktree (`farmer-hal2`)."""
    who = ROLE_TITLES.get(ctx["role"], ctx["role"])
    checkout = ctx.get("checkout") or ""
    named = checkout and checkout != "main" and not checkout.startswith(ctx["role"] + "-")
    return f"{ctx['repo']} · {who}" + (f" {checkout}" if named else "")


def fallback(data: dict, ctx: dict) -> tuple[str, list[dict]]:
    """Today's table as the page: the five columns, the own row marked (the line under the table is the page's meta)."""
    rows, marked = [], []
    for i, r in enumerate(data["rows"]):
        cells = list(r.get("cells") or state_table.cells(r, data["default"]))
        cells[0] = cells[0].replace("**", "")
        rows.append(cells)
        if r.get("own"):
            marked.append(i)
    return title_of(ctx), [
        {"heading": "Worktrees", "columns": state_table.HEADER, "rows": rows, "marked": marked, "empty": "No worktrees."}]


VIEWS = {r: fallback for r in (*roles.ROLES, roles.UNKNOWN)}
VIEWS["farmer"] = view_farmer.view
VIEWS.update({r: view_foreman.view for r in ("foreman", "servant")})
VIEWS.update({r: view_goals.view for r in view_goals.GOALS})  # mayor, lord, pope
VIEWS["steward"] = view_steward.view
VIEWS["tollman"] = view_tollman.view


def shows_cells(role: str) -> bool:
    """Whether the role's page is the five-cell table (`fallback`), the only page showing `state.TABLE_FACTS` (0369 D14)."""
    return VIEWS.get(role, fallback) is fallback


def build(role: str, data: dict, ctx: dict) -> tuple[str, list[dict]]:
    """The role's title and sections; an unregistered role gets the fallback."""
    return VIEWS.get(role, fallback)(data, {**ctx, "role": role})
