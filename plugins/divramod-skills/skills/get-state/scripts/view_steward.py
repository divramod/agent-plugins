"""The steward's page (hal2 plan 0366 D9): the next actions of the project in three sections, each with its empty
state: the daybook's open chores, the unfinished plans (from the rows) and the open UAT checks. The readers are in
steward_sources.py; a reader that gives nothing (None) shows its section as unknown, never as an error.
"""

import datetime as dt

import steward_sources as ss

UAT_LIMIT = 15


def chore_section(found: dict | None) -> dict:
    if found is None:
        return {"heading": "Daybook", "empty": "No daybook day file found (the daybook skill creates one with /daybook)."}
    heading = f"Daybook {found['date']}: open chores ({len(found['items'])})"
    rows = [[("Today" if sec == "today" else "Later"), text] for sec, text in found["items"]]
    return {"heading": heading, "columns": ["When", "Chore"], "rows": rows, "empty": "No open chores."}


def plan_section(rows: list[dict]) -> dict:
    """Plans with steps left, by field number (main last): `Field | Plan | Steps`."""
    open_rows = [r for r in rows if r.get("plan_number") and isinstance(r.get("steps_total"), int)
                 and (r.get("steps_done") or 0) < r["steps_total"]]
    open_rows.sort(key=lambda r: (not r["wt"].isdigit(), r["wt"]))
    table = [[r["wt"], f"{r['plan_number']} {r['plan_name']}", f"{r.get('steps_done') or 0}/{r['steps_total']}"] for r in open_rows]
    return {"heading": f"Unfinished plans ({len(table)})", "columns": ["Field", "Plan", "Steps"], "rows": table,
            "empty": "No unfinished plan."}


def uat_section(plans: list[dict] | None) -> dict:
    if plans is None:
        return {"heading": "Open UAT checks", "empty": "UAT state unknown (hal2-cli-plans is not available)."}
    plans = sorted(plans, key=lambda p: (-p["failed"], p["plan"] or ""))
    shown = plans[:UAT_LIMIT]
    rows = [[p["plan"], p["open"], p["failed"], p["next"]] for p in shown]
    if len(plans) > len(shown):
        rows.append([f"... and {len(plans) - len(shown)} more plans", "", "", ""])
    return {"heading": f"Open UAT checks ({len(plans)} plans)", "columns": ["Plan", "Open", "Failed or blocked", "Next check"],
            "rows": rows, "empty": "No open UAT check."}


def view(data: dict, ctx: dict) -> tuple[str, list[dict]]:
    import views  # late: views registers this module
    today = ctx.get("today") or dt.date.today()
    sections = [chore_section(ss.chores(data["repo"], today)), plan_section(data["rows"]), uat_section(ss.open_uats(data["repo"]))]
    return views.title_of(ctx), sections
