---
type: Plan
schema: 2
id: {id}
title: {quoted_title}
description: {description}
status: open
landing: {landing}
run: opus medium 1m
created: {date}
schedule: serial
---

# Plan {number}: {title}

## Goal

{goal}

## Brief

- In: <what this plan delivers>
- Out: <what it leaves alone>
- Must: <each requirement one line, the user's words quoted>
- Proof: <the command or the UAT checks that show the whole works>

## Context

- Seed: <seedbag>#<n>
- <links to the intent doc, decision records, research or code this plan builds on>
- The ledgers: [decisions.md](decisions.md), [questions.md](questions.md); the state: [handoff.md](handoff.md).

## Overview

Generated from the sub-plans and their step files (`plan.py overview --write`); never edit the block by hand: a step's
status is set in its file. Each sub-plan is one deliverable in `subplans/NN-<slug>/`, its steps in `steps/step-NN.md`
(ref `NN.NN`), `99-uat` the user's checks after the landing. Each step runs in one subagent at its `model`, `effort`
and `window`, `size` its estimated peak context, at most 35% of window; `run` above is the coordinator's. The plan
lands once, after all its work steps (`landing: auto`: the plan skill runs `/mtm` then).

<!-- generated: overview -->
<!-- /generated -->

## Pre-authorized

User-only decisions (money, production deploys, accounts and secrets, paid resources, product choices), asked and
answered before implementation; each is an entry of [decisions.md](decisions.md) with the user's words, named here
by its number. The run acts on them without asking again.

- <none: the plan needs no user-only decision>

## Notes

- <what concerns the whole plan; a sub-plan's notes go into its `subplan.md`, a step's into its step file>
