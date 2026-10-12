---
type: Research
schema: 1
id: {id}
title: {title}
description: {description}  # one sentence, at most 200 characters
question: >-
  {question}
status: planned  # planned | researching | verifying | done | decided | abandoned | superseded
answer: >-
  <one sentence: the answer, bottom line up front>
confidence: low  # high | moderate | low
kind: {kind}  # decision | investigation | survey | incident | architecture
created: {date}
updated: {date}
revisit: {revisit}  # when to re-check the answer
author: {author}
origin: {origin}  # shotfiles/<feature>.md#<n>, a plan, or user request
plan: {plan}  # plans/<NNNN>-research-<topic>/plan.md, when a plan ran it
follow_up: []
decision:  # INTENT.md row or ADR the outcome went to; empty while undecided
supersedes: []
superseded_by: []
related: []
tags: []
sources: 0
claims: {{total: 0, verified: 0, disputed: 0}}
---

# Research {number}: {title}

## Answer

<2-5 sentences: the answer and the **bold recommendation**. Everything from here to Decision fits on one screen.>

## Key findings

1. <finding> (confidence: high|moderate|low, <reason>) [E1][S1]

## Recommendation

<what to do, and the conditions under which it holds>

## Decision

<what the human decided, with date and link (INTENT.md, ADR, plan), or "open">

---

## Question and scope

<the question, why it is asked now, goals, non-goals, constraints; the tenets options are judged by>

## Method

<sub-questions, perspectives, where was searched and when; counts: found N, read N, cited N; verification pass>

## Background

<optional: where the repo stands today (code references), prior research>

## Findings

### <sub-question 1>

<claims, each factual sentence cited [S#]; judgments marked as such>

## Options

<optional: one subsection per option: what it is, who uses it, pros, cons, risks>

## Comparison

<optional: criteria × options matrix with today as the baseline>

## Assumptions and what would change our mind

<optional: key assumptions; 2-4 observable signposts that would change the answer (checked at `revisit`)>

## Risks

<optional: premortem: "a year later this failed because ..."; the counter-perspective reviewer's best points>

## Open questions

- <unresolved question> — <how it could be answered>

## Next steps

<optional: follow-up plans, shots, experiments>

## Evidence

<optional: | ID | Claim | Sources | Type | Verified | Confidence |>

## Sources

- [S1] <title> — <author/publisher>, <published date>. <URL> (accessed {date})

## Log

- {date}: created.
