"""What one fix-loc tick does, decided from plain inputs (no IO), so every outcome is testable.

The state (`state.json`): `servant` (the running unit: unit, slot, pane, worktree, plan, model and effort of its
coordinator session, step_model of its plan's rows, spawned_ms, before), `settings` (the loop's coordinator_model,
coordinator_effort and step_model, kept across ticks), `history` (landed units with code lines before/after),
`blocked` ({unit: until_ms}), `attempts` ({unit: landed plans that left it over the limit}), `started_ms` (the
loop's start, for the cron re-arm).
"""

import re

MINUTE = 60_000
DAY = 24 * 60 * MINUTE
DIALOG_LIMIT = 30 * MINUTE  # a dialog open this long blocks the servant
IDLE_LIMIT = 60 * MINUTE  # idle/done/sleeping this long without landing blocks it
BLOCK_FOR = 7 * DAY
GIVE_UP_FOR = 30 * DAY
MAX_ATTEMPTS = 2  # landed plans that still leave a unit over the limit
REARM_AFTER = 6 * DAY  # recurring cron jobs expire after 7 days
PLAN_SLUG = re.compile(r"^\d{4}-[\w.-]+$")


def servant_agent(agents, project, slot):
    """The agent running in the servant's slot of `project`, or None."""
    for agent in agents:
        if agent.get("project") == project and agent.get("slot") == slot:
            return agent
    return None


def holds_queue(queue, slot):
    """The servant's merge-queue ticket when it holds the queue after a failure."""
    for ticket in queue:
        if ticket.get("slot") == slot and ticket.get("state") == "held":
            return ticket
    return None


def decide(state, now_ms, *, project, agents, queue, landed, current_plan):
    """{action, reason} for a running servant: wait | landed | blocked | paused (| plan to record).

    `landed`: the default branch has the servant's plan with `Finished:`; `current_plan`: the servant's
    checkout's `plans/CURRENT_PLAN`.
    """
    servant = state["servant"]
    result = {"action": "wait", "reason": "", "plan": servant.get("plan")}
    if not servant.get("plan") and current_plan and PLAN_SLUG.match(current_plan):
        result["plan"] = current_plan
    if landed:
        return {**result, "action": "landed", "reason": f"plan {result['plan']} landed"}
    ticket = holds_queue(queue, servant["slot"])
    if ticket:
        reason = (ticket.get("hold") or {}).get("reason", "held")
        return {**result, "action": "paused", "reason": f"the servant's landing holds the merge queue ({reason})"}
    agent = servant_agent(agents, project, servant["slot"])
    if agent is None:
        if now_ms - servant["spawned_ms"] < 5 * MINUTE:
            return {**result, "reason": "the servant is starting"}
        return {**result, "action": "blocked", "reason": "the servant's agent is gone and its plan has not landed"}
    waited = now_ms - int(agent.get("since") or now_ms)
    agent_state = agent.get("state")
    if agent_state == "blocked" and waited > DIALOG_LIMIT:
        return {**result, "action": "blocked", "reason": f"a dialog waits for {waited // MINUTE} min"}
    if agent_state in ("idle", "done", "sleeping", "ended", "failed") and waited > IDLE_LIMIT:
        return {**result, "action": "blocked", "reason": f"the servant is {agent_state} for {waited // MINUTE} min"}
    return {**result, "reason": f"the servant is {agent_state}"}


def next_unit(units, state, now_ms):
    """The first unit of the scan (hotspot order) that is neither busy nor blocked, or None."""
    blocked = state.get("blocked", {})
    for unit in units:
        if not unit["busy"] and blocked.get(unit["unit"], 0) <= now_ms:
            return unit
    return None


def after_landing(state, unit, still_over, now_ms):
    """Record a landed unit; block it for a while when `MAX_ATTEMPTS` plans left files over the limit."""
    attempts = state.setdefault("attempts", {})
    if still_over:
        attempts[unit] = attempts.get(unit, 0) + 1
        if attempts[unit] >= MAX_ATTEMPTS:
            state.setdefault("blocked", {})[unit] = now_ms + GIVE_UP_FOR
            return f"{unit} is still over the limit after {attempts[unit]} plans: skipped for 30 days"
    else:
        attempts.pop(unit, None)
    return None


def needs_rearm(state, now_ms):
    """Whether the loop's cron job is old enough to be re-created before it expires."""
    return now_ms - state.get("started_ms", now_ms) > REARM_AFTER
