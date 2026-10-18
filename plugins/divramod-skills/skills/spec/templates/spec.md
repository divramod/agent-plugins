---
type: Spec
schema: 1
id: {id}
title: {quoted_title}
description: {description}
status: draft
created: {date}
---

# Spec {number}: {title}

<!-- The long description before a plan (hal2 plan 0364, D8 and D9): what and why, never how. Written by the spec
skill (`spec.py new`) and filled with the user; `/plan new --spec {id}` plans it later and its Brief summarises this
file. Every `<...>` is a placeholder: `spec.py approve` refuses while one is left. -->

## Problem

<what hurts today, for whom, and why now>

## Users and goals

- Users: <who uses it, in which situation>
- G1 (must): <a goal, as "the system SHALL ...">
- Non-goal: <what it deliberately does not try>

## Scope

- In: <what the feature covers>
- Out: <what it leaves out, and where that goes>

## Requirements

- R1: <the system SHALL ...>
- Constraints: <stack, platforms, budgets and guardrails it must keep>

## Acceptance criteria

| ID | Given | When | Then |
|---|---|---|---|
| A1 | <a state> | <an action> | <the observable result> |

## Open questions

- none

## Design

<what needs designing: `/design create` writes design.html beside this file; or "nothing to design" for a simple feat>
