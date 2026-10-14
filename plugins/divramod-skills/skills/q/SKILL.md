---
name: q
description: List the questions of the session's store on demand, printed by a script in the Q form (`Q<n>: ...` with the options a) b) c) as written, an answered one followed by its answer) — `/q` the open ones, `/q a` the answered ones, `/q l` all (the open first). The store is the current plan's `plans/<plan>/questions.md`, else the checkout's gitignored root `QUESTIONS.md`. No model call, read-only, for every session in every repository (farmer, foreman, servant). A session lists its open questions only when the user asks with /q or when it cannot continue; otherwise it continues and records them. Use when the user says /q, "what questions are open", "show the open questions" or "list the questions". `/q h` shows help.
---

# q

`S=<skill-dir>/scripts`. Read-only, no model work: a script reads the store and prints it.

| Call | Does |
|---|---|
| `/q` | the open questions |
| `/q a` or `/q answered` | the answered questions, each with its answer |
| `/q l` or `/q list` | all questions: the open first, then the answered and dropped |
| `... --repo <dir>` | another checkout; `--json` the same as data, `--path` only the store's path |
| `/q` in the farmer's worktree `farmer-<repo>` | the farmer's joined list instead (`farmer.py questions`): its own questions, the log's open asks and every worktree's store, each under its worktree |
| `/q h` | print this table and stop |

## Run

`python3 $S/q.py [a|l] [--repo <dir>]`. Print its output and nothing else: no summary, no advice, no rewording of a
question. Exit 1: print the line it gave (the store is broken, fix the file named). Exit 2: the handoff skill is
missing next to this one; report it.

## Record a question

The script only reads. The farmer records its own questions with `farmer.py question add` (farmer skill). Any other session records a new question where `/q` looks: the plan's `questions.md` in the entry form
of the handoff skill (`python3 <handoff-skill>/scripts/questions.py --path` names it, `--json` gives the next number),
and without a plan the root `QUESTIONS.md` (gitignored, beside `HANDOFF.md`), the same entries. Ask the user unasked only
when the work cannot go on without the answer; otherwise record the question and continue.
