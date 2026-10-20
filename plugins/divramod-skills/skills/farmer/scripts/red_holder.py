"""A red holder: the merge queue's head whose smuggle or landing failed and which keeps the place until it lands (hal2
plan 0370, D1, D6; `.adr/merge-queue-policy.md`, amendment 2026-10-18).

Two shapes, both `held`: a smuggle or landing hold with reason `failed` (step, message, attempts), and a CI landing's
`reserved` hold whose newest land run failed. Nothing gives such a place up but a recorded stop or release on the user's
or the farmer's word: the boss wakes the holder's session to fix the reasons and rerun, and never releases it.
"""


def of(ticket: dict, landings=()) -> dict | None:
    """`{"what", "step", "attempts"}` of a red holder, else None. `landings`: the recent landing rows, newest first
    (`slot`, `outcome`)."""
    if ticket.get("state") != "held" or ticket.get("paused_by"):
        return None
    hold = ticket.get("hold") or {}
    what = "smuggle" if ticket.get("smuggle") else "landing"
    if hold.get("reason") == "failed":
        attempts = hold.get("attempts")
        return {"what": what, "step": hold.get("step") or None,
                "attempts": attempts if isinstance(attempts, int) and attempts > 0 else 1}
    if hold.get("reason") == "reserved" and not ticket.get("smuggle"):
        last = next((x for x in landings if x.get("slot") == ticket.get("slot")), None)
        if last and last.get("outcome") == "failed":
            return {"what": "landing", "step": last.get("task") or "land run", "attempts": 1}
    return None


def finding(ticket: dict, red: dict, agent, failure: str, tests: list) -> dict:
    """The scan finding `red-holder`; `failure` and `tests` are read from the hold's message by the scan."""
    step = f"{red['step']}, " if red["step"] else ""
    return {"kind": "red-holder", "slot": ticket["slot"], "seq": ticket.get("seq"), "what": red["what"],
            "step": red["step"], "attempts": red["attempts"],
            "why": f"red {red['what']} holds the queue ({step}attempt {red['attempts']}), no run goes, its agent is "
                   f"{agent}",
            "failure": failure or red["step"] or "red", "tests": tests}
