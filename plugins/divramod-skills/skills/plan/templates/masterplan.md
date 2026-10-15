---
type: Plan
schema: 1
id: {id}
title: {quoted_title}
description: {description}
status: open
landing: manual
crop: {crop}
run: opus medium 1m
created: {date}
---

# Plan {number}: {title}

## Goal

{goal}

## Brief

- In: <the plans this masterplan holds, each rounded off and brought in alone>
- Out: <what it leaves alone>
- Must: <each requirement one line, the user's words quoted>
- Proof: <what shows the whole works after the last plan is brought in>

## Context

- Seed: <seedbag>#<n>
- <links to the intent doc, decision records, research or code this masterplan builds on>
- The ledgers: [decisions.md](decisions.md), [questions.md](questions.md); the state: [handoff.md](handoff.md).

## Steps

A masterplan: every row is a plan of its own with its folder, foreman and bring in; no row is a step. `plan.py new
--parent {id} "<title>"` writes a plan and its row here. Needs are the rows that must be brought in first; Touches
the units a plan changes (two rows sharing one never run at once). A row is `draft` until its plan is grilled again
against the default branch, then `next`, `running`, `blocked <why>` or `done`; ids are never renumbered. This file
at most 150 lines, a cell at most 200 characters.

| # | Step | Needs | Touches | Who | Done when | Status |
|---|---|---|---|---|---|---|

## Pre-authorized

User-only decisions (money, production deploys, accounts and secrets, paid resources, product choices), asked and
answered before any plan runs; each is an entry of [decisions.md](decisions.md) with the user's words, named here
by its number. The plans act on them without asking again.

- <none: the masterplan needs no user-only decision>

## Notes

- <who runs which plan where and what may run at once; a plan's notes go into that plan>
