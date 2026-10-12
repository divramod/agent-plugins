---
type: Plan
schema: 1
id: {id}
title: {quoted_title}
description: {description}
status: open
landing: {landing}
run: opus medium 1m
created: {date}
---

# Plan {number}: {title}

## Goal

{goal}

## Context

- <links to the intent doc, decision records, research or code this plan builds on>
- The ledgers: [decisions.md](decisions.md), [questions.md](questions.md); the state: [handoff.md](handoff.md).

## Steps

Each step is detailed in `steps/<n>.md`, written when it becomes next (`plan.py status <n> next`); keep one line
per step here. Short and concise: this file at most 150 lines, a cell at most 200 characters, links over repeats. The plan lands once, after all its steps
(`landing: auto`: the plan skill runs `/mtm` then); steps checked only after the landing come last, their done-when
starting "after the landing: ...". Each step runs in one subagent: `Model` (haiku, sonnet, opus, fable), `Effort`
and `Window` (200k, 1m; 1m for the 5.x models) are its own, `Size` its estimated peak context, at most 35% of Window
(`plan.py check`); `run` above is the coordinator's model, effort and window, the session that never does a step.

| # | Step | Done when | Model | Effort | Window | Size | Status |
|---|---|---|---|---|---|---|---|
| 1 | <step> | <a check anyone can run> | opus | medium | 1m | 150k | next |
| 2 | Write the UATs: `uat.md` beside this file (`plan.py uat`), only the checks a human must do on the default branch after the landing | `plan.py current` shows `uat` with its checks | sonnet | medium | 1m | 100k | |

## Pre-authorized

User-only decisions (money, production deploys, accounts and secrets, paid resources, product choices), asked and
answered before implementation; each is an entry of [decisions.md](decisions.md) with the user's words, named here
by its number. The run acts on them without asking again.

- <none: the plan needs no user-only decision>

## Notes

- <what concerns the whole plan; a step's notes go into its `steps/<n>.md`>
