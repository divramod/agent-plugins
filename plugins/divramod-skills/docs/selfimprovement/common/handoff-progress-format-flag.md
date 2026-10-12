---
id: SI-0001
skill: hal-lc-handoff
status: proposed
category: wrong-command
severity: low
mechanical: true
occurrences: 3
first_seen: 2026-09-25
last_seen: 2026-09-25
---

Half 0 step 4 says to verify with `hal plan progress <plan> --format=ai`, but `hal plan progress` takes no
`--format` flag (`error: unexpected argument '--format'`) and only prints `started=… unshipped=…`.

**Recommendation:** point step 4 at a verb that shows per-phase N/M shipped (e.g. `hal plan summary <plan> ai`
or `/hal-lc-plan-state`), or add `--format` to `hal plan progress`.
