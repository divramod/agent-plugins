"""Who this session is (plan 0592's D12): hal2's one rule, `hal2-cli-agents role --path <checkout> --json`, through
get-state's `role.from_cli`; without the CLI (an older one) get-state's own `detect` and the pointers. One shape:

    `{role, why, field, checkout, main, repo, lead: {field, plan, step} | None, plan, plan_label, source: cli | fallback}`

`plan` is the CURRENT_PLAN pointer's text (a slug, a shot's name), `plan_label` the CLI's `0593 · <title>`.

`role` is None where the rule gives none (a train's carrier field `tollman-train-*`, a folder outside git).
"""

import sys
from pathlib import Path

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import load, sibling  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)

sys.path.insert(0, str(sibling("get-state") / "scripts"))
import role as state_role  # noqa: E402  (get-state's: the CLI call and the fallback rule)

import clis  # noqa: E402

pointers = load("plan", "pointers")
TRAIN_PREFIX = "tollman-train-"


def lead_of(text: str) -> dict | None:
    """`<field> <plan> <step>` of a LEAD marker; None for an empty one."""
    parts = text.split()
    if not parts:
        return None
    return {"field": parts[0], "plan": parts[1] if len(parts) > 1 else None, "step": " ".join(parts[2:]) or None}


def facts(path: str | Path) -> dict:
    """The session's role facts for the folder `path`."""
    top = clis.git(path, "rev-parse", "--show-toplevel")
    common = clis.git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    main = str(Path(common).parent) if common else None
    here = top or str(Path(path).resolve())
    found = state_role.from_cli(here)
    lead = lead_of(pointers.read(here, pointers.LEAD)) if top else None
    plan = (pointers.read(here, pointers.CURRENT_PLAN) or None) if top else None
    if found is not None:
        cli_lead = found.get("lead") if isinstance(found.get("lead"), dict) else None
        return {"role": found.get("role") if found.get("role") in state_role.ROLES else None,
                "why": found.get("why") or "", "field": found.get("field"), "checkout": found.get("checkout") or top,
                "main": main, "repo": found.get("repo") or (Path(main).name if main else None),
                "lead": cli_lead and {k: cli_lead.get(k) for k in ("field", "plan", "step")} or lead,
                "plan": plan, "plan_label": found.get("plan"), "source": "cli"}
    role = state_role.detect(top, main)
    if top and Path(top).name.startswith(TRAIN_PREFIX):  # hal2's rule: the tollman's engine owns it, no session
        role = state_role.UNKNOWN
    return {"role": None if role == state_role.UNKNOWN else role, "why": "get-state's folder rule (no role CLI)",
            "field": Path(top).name if top else None, "checkout": top, "main": main,
            "repo": Path(main).name if main else None, "lead": lead, "plan": plan, "plan_label": plan, "source": "fallback"}
