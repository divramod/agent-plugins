---
id: SI-0002
skill: hal-lc-avoid-drift
status: proposed
category: wrong-command
severity: low
mechanical: true
occurrences: 3
first_seen: 2026-09-25
last_seen: 2026-09-25
---

Step 1 (Recite) says `hal plan goals show <plan>`, but the verb takes `--plan <slug>`
(`error: unexpected argument '0003-tell-me-multi-source' found`).

**Recommendation:** change the command in the skill to `hal plan goals show --plan <plan>`.
