---
id: SI-0004
skill: hal-lc-auto
status: proposed
category: unclear-contract
severity: low
mechanical: true
occurrences: 1
first_seen: 2026-09-25
last_seen: 2026-09-25
---

`hal plan update --id` says `<plan-relative-path>/T<NNN>/<state>`, but `0003-x/phases/006-y/T501/reviewed`
fails (no such file) and `.../plan.md/T501/reviewed` fails (not a directory); only the repo-relative phase dir
`plans/0003-x/phases/006-y/T501/reviewed` works.

**Recommendation:** accept the plan-relative form the help text names (resolve under plans/), or fix the
help text to "repo-relative phase directory".
