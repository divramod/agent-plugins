---
name: continue
description: Carry on after a clear, a pause or a stop, for every role — a script finds the role, its handoff, a pause record, whether to /mfm and what changed since (hal2-cli-plans since); the model judges only that, rewrites the plan before any code, then continues. `/continue all`: the farmer's paused foremen. Use when the user says /continue, /c, "continue", "resume", "unpause" or "go on".
---

# continue

One command for every session (plan 0592's D3, the user's words: "i just want to have one continue, which also takes
the handoff always into consideration"). The code part is one script; the model only judges what changed and carries
on. `C="python3 <skill-dir>/scripts/continue.py"`, `H=<handoff-skill-dir>/scripts` (the `handoff` skill next to this
one's category), `P="python3 <pause-skill-dir>/scripts/pause.py"`.

| Call | Does |
|---|---|
| `/continue`, `/c` | [continue](#1-gather) this session: role, handoff, pause record, restock, the check, the role's way |
| `/continue <text>` | the same; the user's text overrides the handoff's **Next** where they conflict |
| `/continue all` | the farmer only: [continue every paused and unfinished foreman](#continue-all), oldest first |
| `/continue h`, `/continue help` | print this table and stop |

No path skips the check (D16), and an empty check costs one CLI call: then carry on at once, no judgment.

## 1. Gather

```bash
$C --fetch          # --json for every field; prints role, handoff, pause, mfm, check, then
```

One call says who this session is (`role`: hal2's rule, `[fallback]` when the installed `hal2-cli-agents` has no
`role` yet), which handoff to read (the one resolver, D13: `roles/<role>/handoff.md` for the farmer, tollman,
steward, mayor, lord and pope; `plans/<plan>/handoff.md` for a foreman's plan; the root `HANDOFF.md` for a servant
and work without a plan; an old place is read as a fallback and named), whether a pause record exists, whether to
restock and what the consistency check found. A role `none` (a train's carrier field, a folder outside git): say so
and stop.

## 2. Load the role

Run the `then` line's command first (`/foreman duties`, `/servant duties`, `/farmer duties`, `/tollman duties`,
`/steward duties`, `/mayor duties`, ...): a clear wipes the role. A foreman's field also restores the coordinator's
values before anything else: `python3 $H/drift.py` (`switch`: run its `command` with `--prompt "/continue"`, end the
turn with one line; `sync`: run it and say so; `ok`: go on), as the handoff skill's Continue step 0 says.

## 3. Read the handoff and the questions

Read the handoff `$C` named (`handoff:`), and in a plan's field `plan.md`, `decisions.md` and what they link. The
farmer's and the tollman's act list reads their handoff as item 0 (its `## DO FIRST` first): leave it to step 7.
No handoff: say so; a foreman starts the plan's first open step, others ask what to work on.

The open questions come first: `python3 $H/questions.py` (a plan's field or the yard). An open question of the user
is answered now, in words; yours stay recorded (`/q`) and never stop the work.

## 4. Take in a pause record

`pause:` names a record (the `pause` skill wrote it): resume every piece it names, then `$P finish`.

- **Background shells**: `$P thaw` SIGCONTs the frozen processes still alive (`thawed`/`gone` per process); a
  `gone` task and one paused as *stopped* runs again from its recorded command (`run_in_background`), unless the
  record or step 6 says its result is no longer needed.
- **Subagents**: same session: `SendMessage` to the recorded name ("You were paused. Continue your task where you
  stopped."); a new session: launch it again with its type, isolation, task and progress ("already done: ...;
  continue with: ...").
- **Workflows**: same session `resumeFromRunId`; a new one reruns the script, or asks when it is expensive.
- **Monitors, cron jobs, a `/loop`**: re-arm from the recorded command, cron, prompt and timeout.
- A different branch than the record's: stop, say what differs, ask. Respect its **Watch out**.

## 5. Restock

`mfm: run /mfm` (the field is behind `origin/main` and neither hitched, landing nor paused): run `/mfm` now, before
the check reads the plan. `skip` says why (a hitched field stays on its head, a landing owns its checkout).

## 6. The consistency check

By `check:` (`hal2-cli-plans since`: other plans' later decisions and answers, changed records, the farmer log's
decisions, plans landed on the same files, overlapping open plans, each with the open steps it bears on):

- `empty`: nothing changed since the plan last moved. No judgment; go on.
- `none`: no plan (farmer, tollman, steward, upper roles): the handoff's decisions in force are the check.
- `unavailable` (an older CLI): check by hand as the handoff skill's Continue steps 2 and 3 say:
  `python3 $H/decisions.py --check`, `bash $H/since.sh`, and read what they list.
- `judge`: give every **strong** item (it names this plan, a shared file, a record's `applies_to`) a verdict per
  open step it touches: `valid`, `superseded` (by its link: the step is no longer to be done) or `changed` (the step
  still is, differently). Scan the **weak** ones (shared units or words only; `$C --json` lists them) and judge only
  those that plainly bear on a step. Every verdict before any code.

Write the verdicts (a foreman; nothing to write when every one is `valid`):

```bash
$C rewrite --verdicts - <<'EOF'
{"entries": [{"id": "e1", "text": "<the decision this plan takes over>", "why": "<why>",
              "link": "[<plan> D<n>](../<plan>/decisions.md)", "supersedes": ["D<own>"]}],
 "steps": [{"step": "3", "verdict": "superseded", "by": "e1", "note": "<one line>"},
           {"step": "4", "verdict": "changed", "by": "e1", "row": "<new Step cell>", "done_when": "<new cell>"}]}
EOF
```

It appends the plan's own ledger entry naming the outside decision with its link, marks a replaced own entry
`superseded` with `By:`, sets a superseded row's Status to `done: superseded by D<n>`, writes a changed row's cells
and a dated line under each step file's `## Notes`; refused verdicts change nothing. A schema 2 plan: `plan.py
status <ref> ...` per step instead. In the store home take the edit folder back (`python3 $H/where.py --apply`),
else commit the plan's files alone: `docs(<NNNN>): continue check: <what changed>`. A servant never writes the
plan: it sends its verdicts to its foreman (the field in `plans/LEAD`) and goes on with its step unless one
supersedes it. Say the verdicts in one line each in the first report.

Then mark the check passed (`/continue all` waits for it): `$C checked`.

## 7. Carry on the role's way

Tell the user in two or three lines where things stand (resumed pieces, restock, the check's verdicts) and start:

| way | Role | Continue with |
|---|---|---|
| `plan` | foreman | the handoff's first **Next**, then the plan as the plan skill's "Run the plan" says (step after step, a commit per step); a masterplan or a landing named in the handoff: the handoff skill's [Continue](../handoff/SKILL.md#continue) branches for them |
| `lead-step` | servant | the one step or sub-plan `plans/LEAD` names, as the plan skill's "Work as a servant" says; never the plan's next step, never `plan.md`, never a landing |
| `wake` | farmer | the farmer skill's [Act](../../roles/farmer/SKILL.md#act): `farmer.py wake`, item 0 its handoff |
| `act` | tollman | the tollman skill's [Act](../../roles/tollman/SKILL.md#act): `tollman.py act`, item 0 its handoff |
| `daybook` | steward | `/daybook`, then the handoff's **Next** |
| `handoff` | mayor, lord, pope, a foreman without a plan | the handoff's **Next** |

`/continue <text>`: the user's text wins over **Next** where they conflict.

## Continue all

`/continue all`, the farmer's command (D18): the user's command is the go for every listed field, also a paused
one (only the farmer resumes, never a program on its own).

```bash
$C all              # field, plan, done/total, paused or no session, next; oldest first
```

One at a time, oldest first, so each check sees the adaptations of the plans resumed before it:

1. A paused field: `hal2-cli-git worktree resume <NN>`.
2. `hal2-cli-git worktree run <NN> --detach --prompt "/continue"` (the foreman restores its own model and effort).
3. Wait for its check, in the background:
   `until $C checked --repo <path> --after <start UTC> 2>/dev/null; do sleep 30; done` (`run_in_background`),
   then the next. A field whose check has not passed in 30 minutes: look at its screen, say why, go on.
4. The work then runs within the farmer's load limits; report the list with what each field's check changed.
