# Planning a spec in place

The plan skill's section on a plan that grows from a spec ([SKILL.md](../SKILL.md) step 2b points here; hal2 plans
0364 and 0502, D6, D7).

A spec is a plan in state `spec` from its start: `plans/<NNNN>-<slug>/` holds `plan.md` (`status: spec`, no step table,
a Brief pointing at the spec), `spec.md`, the ledgers and the handoff (the spec skill's `spec.py new`).

**Planning it** (`plan.py new --spec <n>`, and `/plan` while `CURRENT_PLAN` names a plan in state `spec`, whose number
is `n`): `spec_link.fill` rewrites that `plan.md` in place. The template's step table and Notes are added, `status:
spec` becomes `open`, `run` and (with `--manual-landing`) `landing` are set, `--goal` replaces the Goal, `--seed`
replaces the Seed line and marks the seed. The Brief is re-seeded from `spec.md` (In and Out from Scope, Must from
Requirements, Proof from the acceptance criteria) and the accepted designs (`design.py accepted --json`: a Must line
and the Proof "conforms to them"); a section the spec leaves as a placeholder stays one, which `plan.py check` reports
(`plan-brief-filled`). The Context's Spec line links `spec.md` and `design.html`. No second folder, no copy; decisions,
questions, handoff, `grilled` and `created` stay, so the autogrill reads the spec's decisions as settled. A schema 2
plan is refused (`--schema 2`; `plan.py convert` later), `--research`, `--masterplan` and `--parent` cannot be combined
with `--spec`. A spec folder of before plan 0502 (spec.md without plan.md) still gets a plan.md written into it. Without
`--spec`, `new` stops while `CURRENT_PLAN` names a spec not planned yet (`--no-spec` for an unrelated plan).

**Updating the spec later** (`/spec <n> update`, any time, D6): once the plan has steps, `spec.py update` sets
`spec_review: <round>` in `plan.md`'s front matter and rewrites nothing. `plan.py check` reports it (`plan-spec-review`:
"the spec changed in round <n>: review the Brief and the steps, then `spec.py reviewed <n>`"), `plan.py current` carries
`spec_review` (0 without). Review the Brief and the affected steps against the changed `spec.md`, adjust them with the
usual commands, then `spec.py reviewed <n>` clears the flag.

**Bringing a spec in for later**: after the landing `plan.py leave` deletes `CURRENT_PLAN` for a plan still in state
`spec` (it has no step to keep it); planning it later is `plan.py new --spec <n>` again.
