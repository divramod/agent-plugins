"""How each role carries on after the check (plan 0592's D3): the duties to load, then the role's own continuation.
Pure; the SKILL.md's "Carry on" section says what each `way` means.

    way(role, facts) -> {role, load, way, then}

`load` the role skill to print first (a clear wipes it), `way` the key of the continuation, `then` one line for the
report.
"""

WAYS = {
    "foreman": ("/foreman duties", "plan",
                "the plan's next step, as the plan skill's \"Run the plan\" says (a masterplan: its next plan)"),
    "servant": ("/servant duties", "lead-step",
                "the one step (or sub-plan) plans/LEAD names, then the report to the foreman; never the plan's next "
                "step, never a landing"),
    "farmer": ("/farmer duties", "wake", "the farmer's wake items (`farmer.py wake`), DO FIRST of its handoff first"),
    "tollman": ("/tollman duties", "act", "the tollman's act items (`tollman.py act`), DO FIRST of its handoff first"),
    "steward": ("/steward duties", "daybook", "today's daybook (`/daybook`) and the handoff's Next"),
    "mayor": ("/mayor duties", "handoff", "the handoff's Next (the village's stop or continue)"),
    "lord": ("/lord duties", "handoff", "the handoff's Next (the city's goals)"),
    "pope": ("/pope duties", "handoff", "the handoff's Next (the life goals)"),
}
NONE = (None, "stop", "no session's role here (a train's field or outside git): say so and stop")


def way(role: str | None, facts: dict | None = None) -> dict:
    load, key, then = WAYS.get(role or "", NONE)
    if role == "foreman" and facts is not None and not facts.get("plan"):
        key, then = "handoff", "the handoff's Next (no plan in CURRENT_PLAN)"
    if role == "servant" and facts is not None and facts.get("lead"):
        lead = facts["lead"]
        then = f"step {lead.get('step')} of {lead.get('plan')} for the foreman of field {lead.get('field')}; " + then
    return {"role": role, "load": load, "way": key, "then": then}
