---
name: spec
description: Write a feature's spec before its plan — `/spec <title>` asks the user one round of questions (problem, users and goals, scope, requirements and constraints, acceptance), takes the next plan number and writes `plans/<NNNN>-<slug>/spec.md` (Problem, Users and goals, Scope, Requirements, Acceptance criteria in Given-When-Then, Open questions, Design), names the folder in `plans/CURRENT_PLAN` and runs `/design create` when anything needs designing. The folder has no `plan.md`, so it can be committed and landed for later; `/plan new --spec <n>` plans it then. `/spec <n>` continues a spec, `/spec approve [<n>]` approves it, `/spec list` lists the specs. Use when the user says /spec, "write a spec", "spec this feature", "I want a spec first" or "describe the feature before planning". `/spec h` shows help.
---

# spec

`S=<skill-dir>/scripts`. A spec is a plan folder before its plan: `plans/<NNNN>-<slug>/spec.md`, beside it the design
skill's `design/` and `design.html`, no `plan.md` (decisions D8 and D9 of hal2 plan 0364). It is the long description,
what and why, never how; the plan written from it later summarises it in its Brief. `spec.py` is the deterministic
part (number, slug, file, `plans/CURRENT_PLAN`, the approval); you ask, write the text and judge what needs designing.

| Call | Does |
|---|---|
| `/spec <title>` | ask one round of questions, write a new spec folder, design what needs it |
| `/spec [<n>]` | continue the spec `<n>` (number, folder name, slug part), else the one in `plans/CURRENT_PLAN` |
| `/spec approve [<n>]` | approve a spec whose every section is written (`spec.py approve`) |
| `/spec list` | every spec folder: status, design page, whether a plan.md exists |
| `/spec h` | print this table and stop |

`spec.py` commands (each takes `--repo <dir>`): `new "<title>" [--description <d>] [--fetch] [--json]`,
`show [<n>] [--json]`, `list [--json]`, `approve [<n>] [--json]`.

## 1. Ask

A simple feat (a rename, a flag, a fix, one obvious shape) needs no spec: say so in one line and offer `/plan new`
instead (D10: "for simple feats, there is no spec needed"). Otherwise ask one round, plain text after what you found,
every question in the Q form with the recommended answer first. Look facts up (code, INTENT.md, records, research,
the installed CLIs' help), never ask them; ask only what the user decides:

- **Problem**: what hurts today, for whom, why now.
- **Users and goals**: who uses it in which situation; the goals as "the system SHALL ...", each must, should or
  could; what it deliberately does not try (non-goals).
- **Scope**: what is in, what is out and where that goes.
- **Requirements and constraints**: what it must do; the stack, platforms, budgets and guardrails it keeps (the
  repository's records bind it: name them, never re-ask them).
- **Acceptance**: what a person sees when it works, as Given-When-Then.

An unanswered question never stops the spec: it goes into the spec's `## Open questions` and you go on.

## 2. Write

1. `python3 $S/spec.py new "<title>"` (at most four words: plan-names-are-short; `--fetch` first when other clones
   may have taken numbers). It takes the next number with the plan skill's `plan_number.py` (never a hand number),
   writes `spec.md` from `templates/spec.md` and names the folder in `plans/CURRENT_PLAN`. It refuses a long title
   and a slug a folder of `plans/` already has: then continue that one or pick another title.
2. Fill every section of `spec.md` from the answers; replace every `<...>` placeholder. Ids: goals `G<n>`,
   requirements `R<n>`, acceptance criteria `A<n>` (one table row each: ID, Given, When, Then; happy, edge and failure
   rows), so the plan's done-whens and the design's scenarios can cite them. Set `description` in the front matter
   to one sentence of the feature (at most 200 characters).

## 3. Design

Decide whether anything needs designing: a screen a person sees, stored data, a flow, a call across a boundary. Then
run the [design](../design/SKILL.md) skill's create (`/design create`): it reads this `spec.md`, splits it into feats
and writes `design.html` beside it. In `## Design` link the page (`[design.html](design.html)`) and say in a line
what it shows. Nothing to design: write "nothing to design" and why, in one line.

## 4. Approve and keep

1. `python3 $S/spec.py show` and tell the user in a few lines: the folder, the goals, the open questions, the design
   page (`/design serve` to review it). Ask whether to approve it.
2. On the user's yes: `python3 $S/spec.py approve` (refused while a placeholder is left: fill it first).
3. The folder can be committed and landed without a plan, "saved/merged to main for later": on the user's word with
   `/gp` (commit and push) or the repository's landing. Later `/plan new --spec <n>` (the plan skill) writes
   `plan.md` into the same folder, seeds its Brief from the spec and the accepted designs.

## Continue

`/spec <n>`: `python3 $S/spec.py show <n> --json`: its sections, the placeholders left, its design page, whether a
`plan.md` exists. Work on what the user asks or what is left, by the steps above. A spec with a `plan.md` is planned:
change it only on the user's word and tell the plan's foreman. An approved spec that changes is approved again
(`spec.py approve`) once the user agrees to the change.

## Rules

- Never write `plan.md` here: that is the plan skill's `new --spec`. Never number a folder by hand.
- A spec folder passes the checkers as it is: `python3 <plan skill>/scripts/plan.py check plans/<folder>` (its records
  only) and `hal2-cli-records check`; its number counts as taken for every plan and spec (`plan_number.py list`).
- While `plans/CURRENT_PLAN` names a spec folder, the plan skill's `current` says it names no plan: expected until
  `plan.md` exists.

Prerequisites: `scripts/check-prerequisites.sh` (python3, git); the plan skill beside this one (`plan_number.py`,
`names.py`, `envelope.py`) comes with the plugin.
