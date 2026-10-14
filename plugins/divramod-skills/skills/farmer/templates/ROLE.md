---
# The farmer skill's settings for this repository: the user's word, and only the user changes it.
# Nothing is implicit. Only the duties listed here run, each on its own cron
# (5-field cron: minute hour day-of-month month day-of-week, local time).
duties:
  lead: "*/15 * * * *"        # development foreman: unstick sessions
  ci: "*/30 * * * *"          # GitHub Actions green
  sync: "*/30 * * * *"        # farmer branch onto main: a foreman merges main, then farmer, and lands
  prs: "23 * * * *"           # pull requests clean: Dependabot PRs batched to one foreman, leftovers closed
  watch: "*/15 * * * *"       # sanity-watch: resume abnormal stops
  autoclear: "0 * * * *"      # fix-autoclear: autoclear failures
  prune: "*/15 * * * *"       # landed worktrees: 00-09 cleaned, 10-99 removed with their branch; free disk
servant_limit: auto            # farmer-started foremen: auto (by load) or a number at once
servant_model: opus            # a foreman's coordinator session: model alias or id (default opus)
servant_effort: medium         # and its effort: low | medium | high | xhigh | max (default medium)
notify: every-round           # every-round | hourly | daily | never (required)
---

# <repo>'s farmer role

The farmer gets <repo> running and keeps it running, autonomously wherever possible.

## Priorities

1. <what must never be down or red>

## Rules

- <what the farmer may decide here, what it must leave to the user>
- Landings and wagon trains are the wagon master's (`roles/wagon-master/ROLE.md`), never the farmer's.

## Tasks

### <task name>

- **Cron**: `*/15 * * * *`
- **Check**: <what to look at, a command>
- **Act**: <what the farmer does: delegate a fix, notify, or a right this task grants, such as a redeploy>
- **Done when**: <the check that says it is fine>
