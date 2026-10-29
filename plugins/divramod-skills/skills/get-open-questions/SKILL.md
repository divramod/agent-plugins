---
name: get-open-questions
description: List the questions of the session's store on demand, printed by a script in the Q form (`Q<n>: ...` with the options a) b) c) as written, an answered one followed by its answer) — `/q` the open ones, `/q a` the answered ones, `/q l` all (the open first). The store is the current plan's `plans/<plan>/questions.md`, else the checkout's gitignored root `QUESTIONS.md`. No model call, read-only, for every session in every repository (farmer, foreman, servant). A session lists its open questions only when the user asks with /q or when it cannot continue; otherwise it continues and records them. Use when the user says /q, "what questions are open", "show the open questions" or "list the questions". `/q h` shows help.
---

# get-open-questions (alias q)

`S=<skill-dir>/scripts`. Read-only, no model work: a script reads the store and prints it. The list is printed by
`hal2-cli-plans questions list` (the CLI of hal2's `questions` module, `$HAL2_CLI_PLANS` or the one on PATH); where it is
missing or fails, `q.py` prints through its own parser (the handoff skill's `qform.py`, the one Q form, plus `qshape.py`), which also puts an old entry's inline options
a) b) c) onto their own lines (split only on the ordered ` a) `, ` b) `, ` c) `).

| Call | Does |
|---|---|
| `/get-open-questions` | the open questions |
| `/get-open-questions a` or `/get-open-questions answered` | the answered questions, each with its answer |
| `/get-open-questions l` or `/get-open-questions list` | all questions: the open first, then the answered and dropped |
| `... --repo <dir>` | another checkout; `--json` the same as data (the CLI's JSON), `--path` only the store's path |
| `/get-open-questions` in the farmer's worktree `farmer-<repo>` | the farmer's joined list instead (`farmer.py questions`): its own questions, the log's open asks and every worktree's store, each under its worktree |
| `/get-open-questions h` | print this table and stop |

## Run

`python3 $S/q.py [a|l] [--repo <dir>]`. Print its output and nothing else: no summary, no advice, no rewording of a
question. A store with malformed open questions (inline options, not exactly three option lines) gets one
`warning: Q31, Q32: ...` line after the list, part of the output like the rest. Exit 1: print the line it gave (the
store is broken, fix the file named). Exit 2: neither the CLI nor the handoff skill next to this one is found; report it.

`--plan <n>` lists another plan's questions. In the store home (hal2 plan 0409: no plan file in the tree) the CLI
answers from the plan store; the script reads the same.

## Record a question

The script only reads. The farmer records its own questions with `farmer.py question add` (farmer skill). Any other session records a new question where `/q` looks: the plan's `questions.md` in the entry form
of the handoff skill (`python3 <handoff-skill>/scripts/questions.py --path` names it, `--json` gives the next number),
and without a plan the root `QUESTIONS.md` (gitignored, beside `HANDOFF.md`), the same entries; the tollman's field
`tollman-<repo>` always the root `QUESTIONS.md` (its CURRENT_PLAN names a train's cars). Ask the user unasked only
when the work cannot go on without the answer; otherwise record the question and continue.
