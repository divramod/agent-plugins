---
name: grill
description: Interview the user relentlessly about a plan, design, decision or idea until every branch of its design tree is resolved and nothing is silently assumed — in rounds of questions, each round asking every question whose prerequisites are settled, each with a recommended answer; facts are looked up, never asked; every decision is recorded in its one home (plan, intent doc or ADR) so nothing is asked twice; an autogrill also sizes every step (Model, Effort, Window, Size; a step over 35% of its window is split); `/grill q` asks a single round for one step. Use when the user says grill (me) / stress-test / poke holes, or when /plan offers it before implementing a plan. `/grill h` shows help.
---

# grill

Adapted from Matt Pocock's `grill-me` / `grilling` skills
([mattpocock/skills](https://github.com/mattpocock/skills), MIT). Changes: questions follow the global question rule (background first; the
question tool only when each question and its options carry their own background),
the session is self-contained, and decisions are written down so a cleared session never re-asks them.

## Usage

| Call | Does |
|---|---|
| `/grill` | grill the current plan (`plans/CURRENT_PLAN`) |
| `/grill <subject>` | grill a plan file, an idea or a decision |
| `/grill auto [<subject>]`, `/grill a` | [auto](#auto): one round without questions, every branch decided by you |
| `/grill q [<subject>]`, `/grill quick` | [quick](#quick): one round on the top risks, for a single step |
| `/grill h`, `/grill help` | print this table and stop |

## Start

1. **Subject.** The argument, or else the current plan (`plans/CURRENT_PLAN` → `plans/<slug>/plan.md`; when it
   names a shot `<shotfile>/<n>[/<title-slug>]` instead, that shot in `shotfiles/<shotfile>.md`), or else ask what to grill.
2. **Already decided.** Read the subject plus the repo's decision records (`INTENT.md` or equivalent, the plan's
   ledger `decisions.md` or its **Decisions** section, `.adr/`). Anything answered there is settled: never ask it again; only reopen it when
   something new contradicts it, and say why.
3. **Research.** A branch whose answer depends on research nobody has done yet (how others do it, a format to
   choose, options to compare) is not decided blind, neither by the user nor by an autogrill: mark it
   "needs research", do the research first (subagents, findings into the plan's research doc) and grill it on the
   findings.
4. **Facts.** Read the code and docs the subject touches. Finding facts is your job: when a question needs a fact
   from the environment (files, tools, current behaviour), look it up or dispatch a subagent; never ask the user
   what you could find out. Don't block on it: only questions downstream of a running lookup wait.

## Rounds

Map the subject as a **design tree**: each decision branches into the decisions that hang off it. The **frontier**
is every open decision whose prerequisites are settled.

Each round asks the whole frontier and nothing else:

- One question-tool call per round (the tool takes up to 4 questions; a bigger frontier takes consecutive calls
  in the same round). Never ask as plain text.
- Each question: a short header, the question with the context needed to answer it, 2–4 concrete options with the
  consequence of each, **your recommended option first, labelled "(Recommended)"**. Use multi-select only when
  choices combine.
- A question that depends on another question still open in this round belongs to a later round.
- A round that changes a plan's steps also sizes the rows it changed, as [Auto](#auto) point 4 does.

After each round, recompute the frontier: answers settle branches and unblock new questions; an answer that changes
an earlier one reopens the affected branch next round, and you say so.

Keep the user steering: if answers are all "recommended" for a long stretch, ask whether a branch deserves more
thought or should be cut. When a question can't be settled by talking (how something should look or feel), say so
and suggest a throwaway prototype instead of guessing. If the tree grows huge, propose splitting the subject and
grilling the pieces.

## Quick

For one step of an already grilled plan (default subject: the plan's next step). Do the **Start** reading, then
ask a single round of at most 4 questions: the decisions most likely to make this step fail or be redone. Record
and finish as below, but don't mark the plan grilled. If the answers open deeper branches, say so and offer the
full grill.

## Auto

One autogrill round: the grill without the user. The plan skill runs one on every new plan before offering it
(and on a never-grilled plan before it runs); the user asks for more rounds with "another autogrill round".

1. Do the **Start** reading and map the design tree as in **Rounds**; a further round starts from what the
   previous rounds left open or opened (deeper branches first) and never re-decides a recorded decision.
2. Decide the whole frontier yourself, round after round, until it is empty: facts are looked up; choices follow
   the repo's rules for choosing between options (in hal2: the more professional, performant, battle-tested one)
   and its decision record. Ask nothing.
3. Record each decision in its one home as in **Record**, marked `(autogrill <n>)`, and adjust the plan's steps
   and done-when checks it changes.
4. **Size every step.** Give every open row of the plan's step table its Model, Effort, Window and Size by the plan
   skill's rubric, [Model, effort and window per step](../plan/SKILL.md#model-effort-and-window-per-step) (linked,
   never copied here). Size is the step's subagent's estimated peak context, its start (about 85k) included, so
   estimate it from the step's files and checks, not from the template. A row over 35% of its Window (70k of 200k,
   350k of 1m) is split along its files or checks into rows that fit, each with its own done-when and values;
   renumber only rows not yet done, never a done one, and fix the `Needs` of a parallel plan's later rows. A Size `?` (from
   `plan.py migrate`) or the template's default values get a real estimate. Then run `python3 <plan-skill-dir>/scripts/plan.py check`:
   rule `plan-steps-sized` must pass after the round.
5. Stamp the round: `python3 <plan-skill-dir>/scripts/plan.py grilled --auto` (`Grilled: <date> (autogrill ×n)`).
6. Report the round's decisions in a few lines; the caller (the plan skill's offer) asks what next. When a
   branch can only be settled by the user (taste, how something should look), decide it provisionally, say so,
   and recommend a manual grill.

A manual `/grill` after autogrill rounds takes their decisions as the recommended answers and may reopen any.

## Record

After every round, write each decision down in exactly **one home** so it survives `/clear`, and link from the
others instead of repeating it:

- the plan's ledger `decisions.md` for decisions that only matter to this plan, one entry each (the plan skill's
  "The plan folder holds four records": `## D<n> · <date> · <user | agent> · in-force`, `**D:**`, the user's quoted
  `**Words:**` or the autogrill's `**Why:**`; a legacy plan without front matter: one line in its **Decisions**
  section, `- <decision> (<date>)`); adjust its steps or done-when checks when a decision changes them;
- a decision record (`.adr/`, the `adr` skill) for what outlives this plan: a rule a session that never reads the
  plan must know; the ledger entry becomes `promoted` and links it. Never a row in a generated decision log
  (hal2's `INTENT.md`); a repository without decision records keeps such decisions in its intent doc.
- a term the user defines or sharpens (what a word means here): an entry of the repository's root `GLOSSARY.md`
  (`**Term**:`, one or two sentences, an optional `_Avoid_:` line), or of `~/.claude/GLOSSARY.md` when the user
  means it the same way in every repository.

A decision that adds, splits or changes a step row also sets that row's Model, Effort, Window and Size ([Auto](#auto)
point 4).

Mark superseded decisions instead of deleting them. Don't commit; the user or `/handoff` does.

## Finish

The session is done when the frontier is empty: every branch visited, nothing silently assumed. Then summarise the
decisions in a few lines and end the reply with a plain-text question whether you have reached a shared understanding. Do not
implement anything before the user confirms. When grilling a plan, mark it grilled:

```bash
python3 <plan-skill-dir>/scripts/plan.py grilled         # after autogrill rounds: `(autogrill ×n, grill)`
```

(`<plan-skill-dir>` is the `plan` skill next to this one.)
