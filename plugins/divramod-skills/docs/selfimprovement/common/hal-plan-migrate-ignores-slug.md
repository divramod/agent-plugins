---
id: SI-0003
skill: hal-lc-auto
status: proposed
category: wrong-command
severity: medium
mechanical: true
occurrences: 1
first_seen: 2026-09-25
last_seen: 2026-09-25
---

`hal plan migrate 0003-tell-me-multi-source --apply` also migrated and committed `0001-summarize-video-v2`
(commit 3e18a22 "migrate 2 plans"): the `[SLUG]` argument narrows the dry-run report but not `--apply`.
Needed at end-of-feature because `hal plan uat render` refuses plans without `schema_version` (and a
`wave: "01"` string, an unquoted `:` in a phase description).

**Recommendation:** make `--apply` honor `[SLUG]`; have `hal plan uat render` (or `masterplan ship`) point at
`hal plan migrate <slug>` before the end-of-feature step, and have `/hal-lc-plan` write `wave` as an int and
quote descriptions.
