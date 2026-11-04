# Lessons

What went wrong in a run and the rule that prevents it; one entry per lesson, written by `plan.py lesson add`, read by
grill-plan's Auto round (`plan.py lesson list`) and by the farmer, which wakes once for a stall class that has no
entry here. An entry is a `## <class>` heading and the lines `- date:`, `- plan:`, `- lesson:`.

## done-not-hitched
- date: 2026-10-30
- plan: 0514
- lesson: The end of a plan is code (`plan.py end`), never prose a session may skip or hand off before; the push is a state, not a step.

## pushing
- date: 2026-10-30
- plan: 0514
- lesson: A field in `git push` (pre-push hook, workqueue holds) is working, not stuck: never nudge it to start over; show it as `pushing` with its why.

## landing-per-plan
- date: 2026-10-30
- plan: 0514
- lesson: A plan lands once, after all its steps; never plan a step that waits for the landing or runs after it, except UAT checks.
