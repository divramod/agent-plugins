---
name: handoff
description: Write or refresh the handoff (the current plan's committed plans/<plan>/handoff.md; the root HANDOFF.md for a legacy plan or work without a plan) so a fresh session (after /clear or on another machine) can continue the work without re-asking anything — first it records every decision and answer from the conversation in its one durable home (plan, intent doc or ADR), then writes the handoff with the goal, a link to the plan (CURRENT_PLAN or a plan file) and its current step, a Decisions index of every user decision in force (date, quoted words, who relayed it, its home), what is done, the concrete next tasks with a done-when check, traps and open decisions, and the prompt to start the next session with — collects every question of the session (the agent's to the user, the user's not yet answered) with its answer in the plan's committed questions.md, so a clear loses none and the fresh session takes the open ones up first — and commits only those docs. With "continue" (or "resume") it does the reverse: reads the handoff and its plan, checks its decisions against plan, intent doc and handoff itself, reports commits and changes made since it was written, and carries on. Use when the user wants to hand off, wrap up before clearing the session, or pick up where the last session stopped. `/handoff clear` also clears the session and continues on its own (hal2), `/handoff c` continues, `/handoff h` shows help.
---

# handoff

`HANDOFF.md` (repo root) is one short file per repo (per worktree when working in one): the state a fresh session needs
and nothing else. It is session state, never committed: gitignored and untracked in every repo (the commit script
does both when a repo still tracks it), so parallel worktrees never conflict on it and a fresh worktree has none. It links to the intent doc, the plan, the ADRs and the code instead of copying them. It is
rewritten every time, so nothing may live only there: decisions go to a durable doc first, and its **Decisions**
section indexes every one of them, so a cleared session and the farmer's decision check find them in one place. The test for a good
handoff: a cleared session never has to ask the user something they already answered, nothing the user said
is lost, and no question, the user's or the agent's, stays without its answer. `S=<skill-dir>/scripts`.

**Two forms, by the current plan** (`python3 $S/where.py --json` says which: `file`, `form`, `plan`, `decisions`,
`questions`):

| | `record`: the current plan is in the record format (its `plan.md` has front matter) | `legacy`: a plan without front matter, work without a plan, a subservant's slot |
|---|---|---|
| The handoff | `plans/<plan>/handoff.md`, a record of the plan folder, **committed** with the plan: state only (Done, Next, Watch out, Start with), so no PID, pane id, session name or absolute home path | the root `HANDOFF.md`, gitignored, with every section below |
| The decisions | the plan's ledger `decisions.md` (one `D<n>` entry each); the handoff has no Decisions section | the home each decision has, indexed in the handoff's **Decisions** section |
| The questions | the plan's ledger `questions.md` | the plan's `questions.md`, `plans/questions.md` without a plan |
| The check | `python3 $S/decisions.py --check`: the plan-folder check (the plan skill's `plan.py check <folder>`) | `python3 $S/decisions.py --check`: the Decisions section |

The record format is hal2's decision record `record-formats`; the plan skill's "The plan folder holds four records"
has each file's form. Wherever this skill says `HANDOFF.md`, a record plan's session reads "the handoff"
(`where.py`'s `file`).

## Usage

| Call | Short | Does |
|---|---|---|
| `/handoff` | `/h` | [write](#write): record decisions, collect the session's questions, update `HANDOFF.md` (write it when missing), commit the docs |
| `/handoff clear` | `/handoff x` | [write](#write), then [clear this session and continue](#clear-and-continue) with `/handoff c` on its own |
| `/handoff continue`, `/handoff resume` | `/handoff c`, `/c` | [continue](#continue) in a fresh session |
| `/handoff help` | `/handoff h` | print this table and stop |

## Continue

**In a subservant's slot** (a parallel plan's helper session: `plans/LEAD` holds `<lead-slot> <plan> <step>`,
`decisions.py` prints a `lead:` line) `/handoff c` continues **that one step only**, as the plan skill's "Work as a
subservant" says: never the plan's next step, never `/mtm`, never an edit of `plan.md`; `CURRENT_PLAN` keeps naming
the lead's plan. When the step's report is pushed and the lead told, the work is done: say so and stop.

0. **Restore the coordinator's values first** (plan 0015's D10: after a clear the plan wins). Before anything else,
   and never after a `plan.py run --sync` (that would write the cleared session's values over the plan's):
   ```bash
   python3 $S/drift.py    # {action: ok|switch|sync, command, run, live, drift, why}
   ```
   It compares the current plan's `run: <model> <effort> <window>` with the live session (the plan skill's
   `session.py`) and decides:
   - `ok` (no plan, a legacy plan, a subservant's slot, no `run`, no difference, only the window differs): go on.
   - `switch` (the model or the effort differs): run its `command` (`hal2-cli-agents switch --model <run's model>
     --effort <run's effort> --prompt "/handoff c" --detach --json`) and end the turn with one line ("restarting at
     <model> <effort>, continuing with /handoff c"). hal2 restarts the session in its pane with those flags for this
     session only (the user's defaults stay) and types `/handoff c` again. The switch refused (no hal2, not in a
     pane): go on and name it under the handoff's **Watch out**.
   - `sync` (it still differs after a switch for this same handoff, its `at`): run its `command` (`plan.py run
     --sync`; the session's values win, no second switch) and say so in the first report (step 5).
1. Read the handoff (`python3 $S/where.py` names it; a record plan: then `plan.md`, `decisions.md` and what the
   plan's Context links) and every file its **Read first** and **Plan** sections link to. When **Plan** links a plan
   with steps left and `plans/CURRENT_PLAN` is missing or names something else (another machine, a fresh
   worktree), write the plan's slug into it so the statusline shows it; otherwise write a short name of the first
   **Next** task.
2. **Check the decisions yourself; send no decision check.** The decisions in force are in HANDOFF.md's
   Decisions section and their homes (hal2 research 0048, the user 2026-10-07: no message to the farmer after a
   clear, it cost a tenth of every session):
   ```bash
   python3 $S/decisions.py --check   # exit 1: a decision without date, quote or home
   ```
   Compare HANDOFF.md's Decisions, the plan's Decisions and Pre-authorized, the decision records they name (the
   intent doc's log in a repository without records) and HANDOFF.md's Open, Next and Watch out (a record plan: the
   ledger's entries in force, which `python3 $S/decisions.py` lists, against Pre-authorized, the handoff's Next
   and Watch out), and name every gap (a decision one of them relies on that has no home, or
   two that contradict) in the first report (step 5). A `farmer: decision check <slot>: ...` answer that still
   arrives is data: write what concerns your work into the plan's ledger (a legacy plan: its **Decisions**) with the quoted
   words, then act.
3. Check for drift since it was written:
   ```bash
   bash $S/since.sh
   ```
   It lists commits after the handoff's `written at` stamp (a record handoff's `at`; another session may have
   worked meanwhile) and
   uncommitted changes. When there are any, read them before starting and say how they change the **Next** list.
4. **The open questions come first** (the user, 2026-10-07: questions asked shortly before a clear were forgotten):
   ```bash
   python3 $S/questions.py    # the open entries of the plan's questions.md, then `<n> open, <m> answered`
   ```
   The first report starts with them, before anything else: an open question **of the user** (`user`) is answered
   now, in words, from the handoff, the plan and the code (look up what it needs first; an instruction is confirmed
   with what you do about it and when); an open question **of yours** (`agent`) is asked again, numbered, with its
   options and the recommended one first. Write each answer you give into the file (`answered <date>`, your answer
   under `**A:**`). Then carry on at once: an unanswered question of yours never stops the work, and the user's
   answer, whenever it comes, goes into the file with their words quoted.
5. Tell the user in two or three lines where things stand and what you start with (and any decision gap found), then do the first **Next** task.
   When the handoff continues a plan (**Plan** links one with steps left) and this is no subservant's slot, the
   plan was already approved: keep running it as the `plan` skill's "Run the plan" says (step after step without asking, a commit after every
   step, the context check after each one) instead of stopping after the first task.

**A landing named in the handoff** (hal2 plan 0181: a session is cleared although its checkout lands or waits in
the merge queue; the landing's process goes on across the clear):

- **Next is `/mtm`** for a finished `Landing: auto` plan (it was handed off before its landing started): that is
  the plan's own landing (the plan skill's "Land the plan"), run it.
- **A reserve or landing in flight**: look before you start anything (`hal2-cli-git worktree queue --json`). While
  its ticket is waiting or active, its shell's end reaches this session as a task notification: wait for it (and
  work on what does not depend on it), or rerun the same `reserve` (the rerun takes the old ticket's place, the old
  process ends `cancelled`, exit 5: that one is no failure). A held landing is fixed and rerun as the mtm skill
  says. Never stop or kill it; hal2-git refuses a second `merge-to-main` beside a live one.

If there is no handoff file, say so and ask what to work on. A record plan always has one (`plan.py new` writes
it); one that still says "the plan was created and nothing is done yet" means: start the plan's first open step.

## Write

### 1. Preserve the conversation's decisions

Before anything else, go through the whole conversation and list every answer, decision, preference and piece of
intent the user gave (choices from question prompts, "do X, not Y", naming, scope, what to drop, how they like to
work). **Also the decisions that reached you through peer and farmer messages**, not only the user's own words: a
relayed go (`farmer [<id>]: the user decided: "<the user's words>"`, recorded with the quoted words), the
merge-to-main boss's `land now`, a farmer's or peer's answer that settled a question, a `decision check` answer.
These are the ones a clear loses most often, above all a relayed decision the session only acted on (a stop, a wait,
"12 should finish first"): it is still a decision and gets a home like any other. Each fact has exactly **one home**; other docs link to it, never repeat
it:

- **The plan's ledger `decisions.md`** (a record plan): every decision of the plan's work, one entry each, appended
  and numbered on (`## D<n> · <date> · <user | farmer | lead | agent> · in-force`, `**D:**` the decision in one
  line, `**Words:**` the quoted words of whoever decided, `**Via:**` who relayed them, `**From:** Q<n>` when a
  question led to it, whose entry then gets `**Decision:** D<n>`). An entry is never deleted or reworded: a
  decision a later one replaced becomes `superseded` with `**By:** D<m>`, one that only held until something
  happened (a stop, a wait) `ended <date>` with the reason under `**Why:**`. A legacy plan: its **Decisions**
  section.
- **A decision record** (`.adr/<slug>.md`) for what outlives the plan: a decision is promoted when a session that
  never reads this plan would have to know it to do its own work right (the `adr` skill: a new record with
  `hal2-cli-records add`, or a dated `## Amendment` of the record it changes); the ledger entry becomes `promoted` and
  links it with `**Record:**`, and the record's `origin` names the plan. **Never write a row into a generated
  decision log** (an `INTENT.md` whose log stands between `<!-- generated: decision-log -->` markers, as hal2's:
  it is generated from the records, and a row written by hand fails the landing).
- **The root `GLOSSARY.md`** for a term the user defined (what a word means in this repository): one entry,
  `**Term**:`, one or two sentences, an optional `_Avoid_:` line; a term the user means the same way in every
  repository goes into `~/.claude/GLOSSARY.md`.
- **The intent doc** only in a repository without decision records: `INTENT.md` at the repo root, or whatever the
  repo uses for purpose and decisions (a decision log, a README section). Add missing entries to its decision log
  with the date; when a decision replaced an earlier one, mark the old entry superseded instead of deleting it. If
  the repo has no such doc and the conversation holds decisions, create `INTENT.md` (purpose, scope, decision log,
  working agreements) and link it from `AGENTS.md`.
- **Preferences about how the user works with agents** (not about this repo) go to the agent's memory instead,
  if it has one.

Fix entries that the conversation contradicts. Record a decision in its home with the user's words quoted
(`User: "<the user's words>"`): the handoff's index and the farmer's check find it by them. Only then write the handoff.

### 2. Collect the session's questions

A clear loses the question asked just before it (the user, 2026-10-07). So go through the whole conversation once
more and bring the questions file up to date: **every question of this session, in both directions, with its
answer**. The file is committed with the plan, so the user can read every question and its answer afterwards:

```bash
python3 $S/questions.py --path     # plans/<NNNN>-<slug>/questions.md of the current plan; plans/questions.md without one
python3 $S/questions.py --json     # its open entries and `next`, the number of the next entry
```

- **Your questions to the user** (question prompts and questions in plain text): the question with its options;
  answered ones with the user's words quoted (the decision itself still gets its home in step 1), the others `open`.
- **The user's questions and messages to you** that got no answer in words yet, above all the ones typed while you
  worked (a question you acted on without replying still counts as unanswered): the user's words quoted, `open`. One
  you answered in this session: `answered`, with your answer in a line or two.
- A question a peer or the farmer passed on from the user counts as the user's.
- An entry that is no longer needed: `dropped <date>` and why under `**A:**`. Never delete an entry.

One entry per question, appended, numbered on (create the file with the heading `# Questions and answers` when
missing; a record plan has it since `plan.py new`, and an answer that is a decision gets the line `**Decision:**
D<n>` below its `**A:**`, naming the ledger entry of step 1):

```markdown
## Q<n> · <YYYY-MM-DD> · <agent | user> · <open | answered <YYYY-MM-DD> | dropped <YYYY-MM-DD>>

**Q:** <the question; the user's own words quoted>
**A:** <the answer; the user's own words quoted when the user gave it>
```

An open entry has no `**A:**` line. Check it: `python3 $S/questions.py --check` prints `ok` or one problem per line.

### 3. Gather facts, don't recall them

- `git rev-parse --show-toplevel`, `git branch --show-current`, `git log --oneline -10`, `git status --short`, and
  `git log --oneline @{u}..HEAD` for unpushed commits (skip if there is no upstream).
- The existing handoff (`python3 $S/where.py`), if any: keep what is still true, drop what is done or stale.
- **The plan.** Look for one, in this order: a `CURRENT_PLAN` pointer file (`plans/CURRENT_PLAN`, whose
  content names the active plan); a plan linked from the existing handoff; a plan named in this conversation; plan
  files in the repo (`plans/`, `PLAN.md`, a spec or research doc with a numbered step list). `CURRENT_PLAN` is gitignored per-worktree state and may name a shot (`<shotfile>/<n>/<title-slug>`) or a task instead of a plan: then take the plan from the other sources. When `CURRENT_PLAN` points at a finished or missing plan, do not link it as current: list
  it under **Open** as stale, with a suggestion (update or delete it). A plan exists only if it is a file; a plan
  that lives only in this conversation gets written into the handoff's **Next** section instead. If several
  candidates exist and the conversation doesn't settle it, ask the user which one.
- **Plan status comes from the plan, not from memory**: for a `plans/<NNNN>-<slug>/plan.md` plan run
  `python3 <plan-skill-dir>/scripts/plan.py current` (the `plan` skill next to this one) and take title,
  `done/total` and the next step from its JSON. Make sure the step table itself is up to date first.
- Test and build state: state only what you ran in this session. Otherwise write "not run".

### 3b. Persist the coordinator's values

Before a clear the live session wins (plan 0015's D10): a record plan with a `run` key gets the session's model,
effort and window written into it, so `/handoff c` (Continue step 0) restores them after the clear:

```bash
python3 <plan-skill-dir>/scripts/plan.py run --sync    # {run, before, live, drift}; writes plan.md when they differ
```

Skip it for a legacy plan, work without a plan and a subservant's slot (`plans/LEAD`: plan.py refuses it there, the
plan is the lead's). When `before` and `run` differ, plan.md goes into step 5's commit.

### 4. Write the handoff

**A record plan** (`where.py`: form `record`): `python3 $S/where.py --stamp` writes a missing
`plans/<plan>/handoff.md` and sets its `updated`, `branch`, `at` and `status`; then edit only the front matter's
`description` (one sentence: where the plan stands now) and the body, which has exactly these sections (`Done` and
`Watch out` may be missing, no other is legal):

```markdown
# Handoff of plan <NNNN>

## Done
- <outcomes of this and recent sessions, with commit shas; not a diary>

## Next
1. <the current step's concrete tasks, with the files or commands they touch>

Done when: <a check the next session can run>

## Watch out
- <traps, fragile spots, things that must not be done; what waits for the user; a landing in flight>

## Start with

> /handoff c
```

It holds state only: the goal and the step table are the plan's, the decisions the ledger's, the questions
`questions.md`'s; link them (`[D4](decisions.md)`), never copy them. It is committed and read on other machines, so
it names no PID, pane id, session name or absolute home path (write `~/...` or a path below the repository; the
farmer is the session in the slot `farmer-<repo>`). The rules below about **Next** and what is in flight hold for
it too; the rest of this step is the legacy form.

**A legacy plan or no plan** (the root `HANDOFF.md`):

When `HANDOFF.md` exists and is about the same plan or task, **update it** (hal2 research 0048: a rewrite at a
full context is the most expensive part of a clear): edit only what changed since it was written, usually the
header line, **Done**, **Next**, new **Decisions** rows and what is no longer true; read it once and
use Edit, never write the whole file again. Otherwise (no file, another plan, more stale than right) write it whole.
Either way it never grows into a log: about 40–80 lines, with these sections; drop a section when it has
nothing to say:

```markdown
# Handoff

Updated <YYYY-MM-DD>, branch `<branch>`, written at `<short sha of HEAD when written>`.
Farmer: <session name> (<the farmer's repo>)

## Goal
<one or two sentences: what this line of work is for>

## Plan
[<plan title>](<relative path>): <done>/<total> done, next: step <n> <step>.
<one line on anything in the plan that changed or is known to be outdated>

## Decisions
- <YYYY-MM-DD> "<the user's words>" (<the user | via farmer <id>>) · home: <plan | INTENT.md | .adr/<file>.md>
- <YYYY-MM-DD> "<the user's words>" (via farmer <id>) · home: plan · ended <YYYY-MM-DD>: <why>

## Read first
- [AGENTS.md](AGENTS.md): <why>
- [INTENT.md](INTENT.md): purpose and every decision so far
- <other files the next session must read, each with a reason>

## Done
- <outcomes of this and recent sessions, with commit shas; not a diary>

## Next
1. <concrete task, with the files or commands it touches>
2. ...

Done when: <a check the next session can run>

## Watch out
- <traps, fragile spots, things that must not be done>

## Questions
[<n> open](<plans/<NNNN>-<slug>/questions.md>): answer the user's and ask yours again before anything else.
- Q<n> (<agent | user>): <the question in one line>

## Open
- <decisions waiting for the user; unpushed commits; uncommitted changes in other repos>

## Start the next session with
> <the exact prompt, e.g. "/handoff continue" or "Read HANDOFF.md and do step 3">
```

Rules:

- **Decisions** is the complete index of every user decision in force for this work, one line each (the
  `decisions.py --check` format): its date, the user's words quoted (a short answer such as "1" adds what it chose
  in brackets after the quote), who relayed it (`the user` or `via farmer <id>`, the instruction id of
  `farmer [<id>]: the user decided: "..."`) and its home from step 1 (`plan` for the current plan, `INTENT.md`, an
  ADR or another path), which holds the same quote. Relayed decisions are included; a decision that only held until
  something happened (a stop, a wait) stays with its end: `· ended <date>: <why>`. A decision a later one replaced
  leaves the list (its home marks it superseded). The plan's own autogrill decisions are not listed: they stay in the
  plan. Nothing to list: `- none`. The home stays the source; this list never holds the only copy.
- The `Farmer:` line only for a session that serves a farmer (a servant: its role or start prompt names the farmer's
  session, e.g. `farmer-a4`, and its repository); drop it otherwise. `/handoff c` asks that farmer for forgotten
  decisions.
- Links are relative to the repo root (e.g. `AGENTS.md`, `research/0001-analysis/research.md`) and must point at files
  that exist.
- **Next** is specific enough that a session without this conversation can start: name files, commands, and the
  first task.
- Decisions live in their one home (step 1); the handoff indexes them (**Decisions**), it never holds the only copy.
- **Next** for plan work is the current step's tasks only; the step list itself stays in the plan. A subservant's
  handoff (`plans/LEAD`) names its one step, its brief and its lead under **Plan**, and **Next** ends with the report.
- A parallel plan's lead lists what is in flight under **Next**: each running step, who (`subagent`, `slot NN`) and
  since when; after the clear it runs `plan.py current`, `ready --json` and `reports` before the loop goes on.
- **Questions** lists only the open entries of the questions file (step 2), one line each, and links the file;
  none open: drop the section. The file holds the full text and every answer.
- No secrets, no tool-call logs, no restating of the plan's content.

Then check the index; fix the handoff (or record the missing quote in the home) until it prints `ok`:

```bash
python3 $S/decisions.py --check    # exit 1: one problem per line (no section, no date, no quote, no home, home lacks the quote;
                                   # a record plan: every problem of the plan folder's four records)
```

### 5. Commit the decision docs, the questions and a plan's handoff, never the root handoff

```bash
bash $S/commit-handoff.sh "docs: record decisions" [plans/<plan>/plan.md plans/<plan>/decisions.md plans/<plan>/questions.md plans/<plan>/handoff.md .adr/<new>.md ...]
```

It commits exactly the docs you changed in steps 1, 2, 3b and 4 (the questions file too, when it changed; a record
plan's `handoff.md` is one of them, its `plan.md` when step 3b changed `run`, and a decision record goes with its regenerated index: the `adr` skill),
leaving everything else staged or unstaged as it was, and
prints the new commit. The root `HANDOFF.md` is never committed; its ignore line is anchored (`/HANDOFF.md`, an
unanchored one is rewritten in the same commit), so a plan's `handoff.md` is never ignored with it: when the repo does not ignore it yet, the script adds it to
the root `.gitignore`, and when the repo still tracks it, it untracks it (`git rm --cached`, the file stays), both
in the same commit. With no docs changed and `HANDOFF.md` already ignored, it commits nothing. It never pushes.
If a script exits 2 with a missing-tool error, run `bash $S/install-prerequisites.sh`.

### 6. Report

Tell the user the commit, which decisions you recorded and where (ledger entries, decision records, the intent
doc), the open questions (yours asked again,
numbered, so the user can answer before the clear), the plan it links (or that there is none),
and the prompt from **Start the next session with**, so they can `/clear` and paste it (with `/handoff clear`:
see below instead).

## Clear and continue

`/handoff clear` (and the `plan` skill's hand-off at its context threshold) writes and commits the handoff as above,
then lets hal2 clear this Claude Code session and type `/handoff c` into the fresh one:

1. Stop your background work first (TaskStop every background shell, subagent, workflow and monitor you started;
   the handoff names what must be rerun): their notifications would wake the fresh session. **Never a landing or a
   waiting reserve** (`hal2-cli-git worktree merge-to-main|reserve`, the merge queue policy: a started landing is
   never aborted): it goes on across the clear, the handoff's **Next** names it (the command, the slot, the ticket's
   state) and its end wakes the fresh session.
2. Start it and end your turn right after with one line ("clearing, continuing with /handoff c"). Take the command
   from `python3 $S/drift.py --clear`: with a plan's `run` it passes `--effort <run's effort>` (plan 0016's D8:
   hal2 types its `[autoclear] effort` after `/clear` otherwise), without one it is
   ```bash
   hal2-cli-agents clear-and-continue --detach --json    # pane from $TMUX_PANE or $HAL2_TERMINAL, session from $CLAUDE_CODE_SESSION_ID
   ```
   It waits for your turn to end, waits out a draft the user is typing (and the user's own turns), types `/clear`
   only into an empty prompt, confirms the new session through its hook record, then types `/handoff c`; the
   job shows on the agent in hal2's Agents pane, where it can be cancelled (`--cancel`).
3. It clears every Claude session, with or without a plan with steps left and with or without a merge-queue ticket
   (hal2 plan 0181; a session that is never idle gets `/clear` and the prompt as queued input). A finished plan
   that has landed has nothing to continue: do not start it there, its report stays on screen. It
   exits non-zero when it cannot start (autoclear disabled in agents.toml, not Claude Code, neither
   in tmux nor a hal2 terminal, no hal2; an older hal2 also `no-open-plan`): report its message and fall back to telling the user to `/clear` and paste the prompt.
   `already-running` is no failure: a job waits already (hal2's guard started it when it stopped the session at the
   threshold); just end the turn.
