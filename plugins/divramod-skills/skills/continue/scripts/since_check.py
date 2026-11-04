"""The consistency check's code part (plan 0592's D15, D16): `hal2-cli-plans since <plan> --repo <root> --json`
(schema 1) and what of it the model judges.

    check(root, plan) -> {state, plan, why, report, items, steps}

`state`: `empty` (nothing changed around the plan: no model judgment, continue at once), `judge` (each item gets a
verdict before any code), `none` (no plan to check: the role's own handoff is the check), `unavailable` (no CLI with
`since`, or it refused: the handoff skill's `decisions.py` and `since.sh` are the check by hand). `items` is one flat
list, each `{kind, ref, text, steps, why, strength}`; `steps` maps each open step to the refs that bear on it.
`strength` is `strong` when a reason names the plan, a shared file, a record's `applies_to`, the field or the plan
itself (`link`, `file`, `applies`, `field`, `own`), else `weak` (shared units or words only): the model judges each
strong item, the weak ones as a list.
"""

import clis

SCHEMA = 1
STRONG = ("link", "file", "applies", "field", "own")
KINDS = (("decisions", "decision"), ("questions", "question"), ("records", "record"), ("farmer", "farmer"),
         ("landed", "landed"), ("overlaps", "overlap"))


def ref_of(kind: str, hit: dict) -> str:
    if kind in ("decision", "question"):
        return f"{hit.get('plan')} {hit.get('id')}"
    if kind == "record":
        return f".adr/{hit.get('slug')}.md"
    if kind == "farmer":
        return f"farmer log {hit.get('at')}"
    if kind == "landed":
        return f"landed {hit.get('plan')}"
    return f"overlap {hit.get('slug') or hit.get('plan') or hit.get('title')}"


def text_of(kind: str, hit: dict) -> str:
    if kind == "record":
        return hit.get("rule") or hit.get("title") or ""
    if kind == "landed":
        return hit.get("subject") or ""
    if kind == "overlap":
        return hit.get("title") or hit.get("goal") or ""
    words = hit.get("text") or ""
    return words + (f" (by {hit['by']})" if hit.get("by") else "")


def items_of(report: dict) -> list[dict]:
    found = []
    for key, kind in KINDS:
        for hit in report.get(key) or []:
            if isinstance(hit, dict):
                why = hit.get("why") or []
                strong = any(isinstance(w, dict) and w.get("kind") in STRONG for w in why)
                found.append({"kind": kind, "ref": ref_of(kind, hit), "text": text_of(kind, hit),
                              "steps": [str(s) for s in hit.get("steps") or []], "why": why,
                              "strength": "strong" if strong else "weak"})
    return found


def by_step(report: dict, items: list[dict]) -> dict:
    steps = {str(s.get("number")): [] for s in report.get("open_steps") or [] if isinstance(s, dict)}
    for item in items:
        for step in item["steps"]:
            steps.setdefault(step, []).append(item["ref"])
    return steps


def check(root, plan: str | None) -> dict:
    if not plan:
        return {"state": "none", "plan": None, "why": "no plan: the role's handoff is the check", "report": None,
                "items": [], "steps": {}}
    report = clis.run_json("plans", ["since", plan, "--repo", str(root), "--json"], root)
    if report is None or report.get("schema") != SCHEMA:
        return {"state": "unavailable", "plan": plan, "report": None, "items": [], "steps": {},
                "why": "hal2-cli-plans since gave no schema 1 report (an older CLI?): run decisions.py and since.sh"}
    items = items_of(report)
    empty = bool(report.get("empty")) and not items
    return {"state": "empty" if empty else "judge", "plan": report.get("plan") or plan, "report": report,
            "why": "nothing changed since the plan last moved" if empty else
            f"{sum(i['strength'] == 'strong' for i in items)} strong, {sum(i['strength'] == 'weak' for i in items)} "
            "weak items to judge",
            "items": items, "steps": by_step(report, items)}
