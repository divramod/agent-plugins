# Proposal: hal2's OWNER-ROLE.md tasks in the machine form

For the user to apply in the owner's worktree (`~/.hal/git/worktree/hal2/owner/OWNER-ROLE.md`, the user's file: the owner
never edits it). It replaces the `## Tasks` section; `python3 <owner>/scripts/due.py check` then names all four
"run by the tick". The form: [tasks.py](../../code/agents/apps/skills/skills/owner/scripts/tasks.py)'s docstring. What changes: each Check is
commands only, each Act commands and `notify`/`delegate`/`wake`, the prose moves to **Why**. Nothing changes in what
the owner may do: the n8n redeploy stays the one production deploy this file allows.

## Tasks

### n8n.hal9k.app stays up

- **Cron**: `*/15 * * * *`
- **Check**: `curl -fsS -m 20 https://n8n.hal9k.app/healthz`
- **Act**: `python3 code/python/scripts/hal9k/main.py deploy app --service n8n n8n-runners`, notify
- **Still failing**: delegate, notify
- **Why**: production the user depends on. **This task allows that production deploy** (the Caddy reload
  included); the data volume `hal9k_n8n` stays.
- **Done when**: `/healthz` answers 200.

### hal9k production healthy

- **Cron**: `0 * * * *`
- **Check**: `python3 code/python/scripts/hal9k/main.py status`
- **Act**: notify
- **Why**: an unhealthy service is the user's call; no automatic redeploy except n8n's above. The notice carries
  the status output (the failing check's tail).
- **Done when**: every service reports healthy (exit 0).

### Disabled tests come back

- **Cron**: `7 9 * * *`
- **Check**: `owner check flaky`
- **Act**: delegate
- **Why**: one worker makes the listed tests load-proof (budgets scaled by load, or out of the landing's gate into
  a timing suite) and enables them again.
- **Done when**: every ledger entry is `landed` (re-enabled) or has a running plan.

### Orphaned slots finished

- **Cron**: `0 * * * *`
- **Check**: `owner check orphans`
- **Act**: wake
- **Why**: the `mtm` duty already starts a session in an orphaned worktree that has a HANDOFF.md (`/handoff c`); what
  this check still finds has none, and the model decides (`/plan n`, or ask the user).
- **Done when**: every worktree with work has a session.
