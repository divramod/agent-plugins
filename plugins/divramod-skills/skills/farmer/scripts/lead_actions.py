"""What the farmer's foreman duty does for a field's plan class (hal2 plan 0514 step 5, D8, D11): code, a quiet round 0 tokens.

- `done-not-hitched`: told once per field and plan to run `plan.py end` (it pushes and hitches; `/mtm` where the plan
  skill has no `end`); never a `pushing` field (that class is never an act here), never again for the same plan.
- `landed`: recorded and left to the prune round (`prune_round.py`, `/prune run`), whose proof is the one deletion path;
  the farmer never deletes a field.
- `waiting`: the questions of all waiting fields go in one wake per round (one relay to the user), not one per field.
- A stall class (`STALLS`) that the plan skill's `references/lessons.md` does not know wakes the farmer once per class
  for the judgment of a lesson; a known class never wakes. The file is written by the plan skill (`plan.py lesson add`);
  a class is known by a heading or a `class:` line naming it. A missing file means no lessons.
"""

import re
from pathlib import Path

import lead_fields
from tick import act

STALLS = ("done-not-hitched", "blocked-plan")  # classes that stopped a plan and needed the farmer
FOREVER = 3650 * 86400
TOLD = 30 * 86400  # a plan is told once; a month is longer than any plan stays done-not-hitched
ROUND = 6 * 3600  # the batched waiting relay comes back after this while the same fields wait
TEXT = ("farmer (development foreman): your plan is done and not hitched. Run `python3 <plan skill>/scripts/plan.py end` "
        "now (it pushes your branch and hitches it for the tollman); do not start over if a push is already running.")
TEXT_MTM = ("farmer (development foreman): your plan is done and not hitched. The plan skill here has no `plan.py end`: "
            "run /mtm (it commits, pushes and hitches).")


def lessons_file() -> Path | None:
    """The plan skill's references/lessons.md, beside the runstate reader it loaded; None without a plan skill."""
    rs = lead_fields.runstate
    return Path(rs.__file__).resolve().parent.parent / "references" / "lessons.md" if rs else None


def known(kind: str, text: str) -> bool:
    return bool(re.search(rf"^\s*(#+\s*|-?\s*class:\s*){re.escape(kind)}\b", text, re.M | re.I))


def has_end() -> bool:
    rs = lead_fields.runstate
    return bool(rs) and (Path(rs.__file__).resolve().parent / "plan_end.py").exists()


def acts(needs: list[dict], told: set, lessons: str | None = None) -> list[dict]:
    """The acts for the round's field-class entries of `needs` (kinds in lead_fields.KINDS)."""
    f = lessons_file()
    if lessons is None:
        lessons = f.read_text() if f and f.exists() else ""
    out, waiting, wake_classes = [], [], []
    for n in needs:
        kind, slot = n["kind"], n.get("slot") or "-"
        at = ((n.get("field") or {}).get("run_state") or {}).get("at", "")
        base = f"lead:{n['session']}:{n['since']}:{kind}:{at}"
        if kind == "pushing" or slot in told:
            if kind == "pushing":
                out.append(act("lead", kind, "record", slot, key=base, text=f"{kind}: {n.get('why', '')} (no action)"))
            continue
        if kind == "done-not-hitched":
            key = f"lead:{slot}:done-not-hitched:{n.get('plan') or ''}"
            out.append(act("lead", kind, "send", slot, pane=n.get("pane"), text=TEXT if has_end() else TEXT_MTM,
                           key=key, window=TOLD))
        elif kind == "landed":
            out.append(act("lead", kind, "record", slot, key=base,
                           text=f"landed: {n.get('why', '')}; left to the prune round (its proof), never deleted here"))
        elif kind == "waiting":
            waiting.append(n)
        else:
            out.append(act("lead", kind, "record", slot, key=base, text=f"{kind}: {n.get('why', '')} (no action)"))
        if kind in STALLS and not known(kind, lessons) and kind not in wake_classes:
            wake_classes.append(kind)
            out.append(act("lead", "new-stall-class", "wake", slot, key=f"lead:lesson:{kind}", window=FOREVER,
                           text=f"stall class `{kind}` is not in the plan skill's references/lessons.md: judge a "
                                f"lesson for it (plan.py lesson add), once per class", evidence=n))
    if waiting:
        lines = [f"field {n.get('slot') or '-'} ({n.get('plan') or '?'}): {n.get('why', '')}" for n in waiting]
        sig = ",".join(sorted(f"{n.get('slot')}@{((n.get('field') or {}).get('run_state') or {}).get('at', '')}"
                              for n in waiting))
        out.append(act("lead", "waiting", "wake", "-", key=f"lead:waiting:{sig}", window=ROUND,
                       text="plans wait for answers, relay them to the user in one message:\n" + "\n".join(lines),
                       evidence=waiting))
    return out
