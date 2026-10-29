# The store home

The plan skill's section on a farm whose plans live in its plan store ([SKILL.md](../SKILL.md#the-one-plan-shape-schema-2)
points here; hal2 plan 0409 step 8).

A farm whose `hal2-cli-plans home` says `store` keeps no plan file in the tree: every `plan.py` command works as the SKILL.md
documents it and prints the same, on a copy (`scripts/planhome.py`, `storerun.py`: the plans it needs rendered
outside the tree, applied back, a done or dropped step's sync triggered); its paths still read `plans/<plan>/...`.
Your own edits of a plan's files (a step's `## Task`, plan.md's sections, a ledger) go into the copy that
`plan.py edit [--plan <n>]` names (`dir`, in the farm's edit folder outside the tree), then `plan.py apply`; a
records problem the edit adds refuses it (fix the copy, apply again). Never create `plans/<plan>/` in the tree there
(only the pointers live under `plans/` until 0409's step 12) and commit no plan file. In the files home `edit` names
the plan's own folder and `apply` does nothing.

**Neutral commits** (hal2 plan 0409 D15): in a farm whose commits are neutral (`python3 $S/planread.py neutral`
prints `on`: the store's `commits.neutral`, on by default in the store home) `plan.py scope` and `plan.py trailers
<step>` print nothing: the head is `<type>(<unit>): ...` or `<type>: ...`, the message has no `Worktree:`, `Plan:` or
`Step:`, and `trailers <step>` has told the store which plan and step the next commit links to (the post-commit
hook's `hal2-cli-plans link-commit`).
