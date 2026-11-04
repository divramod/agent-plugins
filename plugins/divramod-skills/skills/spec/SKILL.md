---
name: spec
description: Write a feature's spec before its steps, optional at every level — `/spec <title>` makes the numbered plan at once in state spec (`plans/<NNNN>-<slug>/plan.md` without steps beside `spec.md`), fills the spec in one pass by default (what the conversation settled goes in unasked, one round of Q-form questions across the whole feature, `## Not yet specified` for what is too vague yet, `/design create` for what needs a picture) and ends at the checkpoint: plan now (`/plan` fills the steps in the same plan), bring it in for later (`/mtm`) or another round (`/grill-plan`). `/spec <n> update` changes a spec any time later, also a planned one, whose plan is flagged for review, never rewritten. `/spec <n>` continues; also `approve`, `abandon`, `list`. A simple feature goes straight to `/plan new`. Use when the user says /spec, "write a spec", "spec this feature", "I want a spec first", "update the spec" or "describe the feature before planning". `/spec h` shows help.
---

# spec

`S=<skill-dir>/scripts`. A spec is a plan from its start (hal2's record `spec-loop`, plan 0502 D6-D8):
`plans/<NNNN>-<slug>/` holds `plan.md` in state `spec` (no steps, its Brief seeded from the spec), `spec.md`, the
plan's own ledgers and handoff, and the design skill's `design/` and `design.html`. The spec is the long description,
what and why, never how. `spec.py` is the deterministic part (number, slug, files, the `CURRENT_PLAN`
pointer, rounds, the checkpoint, the review flag); you ask, write the text and judge what needs designing.

| Call | Does |
|---|---|
| `/spec <title>` | a new spec-state plan, filled in one pass, then the checkpoint |
| `/spec [<n>]` | continue the spec `<n>` (number, folder name, slug part), else the one in `CURRENT_PLAN` |
| `/spec <n> round` | another round on a draft spec (the checkpoint's third option) |
| `/spec <n> update` | change a spec later, also an approved, brought-in or planned one |
| `/spec approve [<n>]`, `/spec abandon [<n>]` | approve a spec with no placeholder left; abandon an unplanned one |
| `/spec list` | every spec: state, round, design page, whether its plan's review is due |
| `/spec h` | print this table and stop |

`spec.py [--repo <dir>]` commands (most take `--json`; `<n>` defaults to `CURRENT_PLAN`): `new "<title>"
[--description <d>] [--seed <seedbag>#<n>] [--fetch]`, `show [<n>]`, `list`, `iterate [<n>]` (a round done: the
checkpoint JSON), `update [<n>] [--what "<what changed>"]`, `reviewed [<n>]`, `grilled [<n>] [--how <how>]`, `approve
[<n>]`, `abandon [<n>]`.

## Where it runs

In a field the user talks to: never in the yard, never in a foreman the farmer started (it never asks, so it runs no
`/spec`). The spec is optional at every level (D6): a simple feature (a rename, a flag, a fix, one obvious shape) gets
no spec; say so in one line and offer `/plan new`.

## 1. One pass (the default)

1. `python3 $S/spec.py new "<title>"` (at most four words: plan-names-are-short; `--fetch` first when other clones may
   have taken numbers; `--seed` for a seed it grows from). It numbers the plan (never a hand number), writes plan.md in
   state spec and spec.md, names the folder in `CURRENT_PLAN`. It refuses while `CURRENT_PLAN` names a started plan
   (`--here` only on the user's words) and a slug `plans/` already has: continue that one or pick another title.
   It also runs `hal2-cli-plans overlap` (plan 0593 D16; `overlap.json`, a Context line in plan.md, stderr; no CLI:
   "overlap unchecked"): **settle each hit** (build on it, wait for it, merge into it) as a ledger entry with a link
   before you fill the spec; a tie goes to the farmer.
2. Fill spec.md with what the conversation, code, INTENT.md, records, research and the CLIs' help already settle,
   without asking again (D8 idea 6). Ids: goals `G<n>` ("the system SHALL ...", must, should or could; non-goals),
   requirements `R<n>` (the binding records named, never re-asked), acceptance `A<n>` as Given-When-Then rows (happy,
   edge, failure). `description` in the front matter: one sentence, at most 200 characters.
3. Then one round across the whole feature (D8 idea 2): problem, users and goals, scope, requirements and
   constraints, acceptance; only what the user decides. Each question into the plan's ledger with `hal2-cli-plans
   questions add "<question>" --option <recommended> --option <b> --option <c>`, then asked as plain text after what
   you found, in the global Q form (`Q<n>`, three options, the recommended first). Answers go into spec.md and the
   ledger (`questions answer`); an unanswered one stays open and never stops the spec. What is too vague to ask yet goes
   under `## Not yet specified`. Nothing open: say the feature is small enough and recommend plan now.
4. Design: a screen a person sees, stored data, a flow or a call across a boundary runs the
   [design](../design/SKILL.md) skill's `/design create`; `## Design` links `design.html` with a line on what it shows,
   else "nothing to design" and why.
5. `python3 $S/spec.py iterate` ends the round and prints the checkpoint (below). Commit the round's files (files home;
   `docs(<NNNN>): spec round <n>`), one commit per round.

## 2. The checkpoint

Show `iterate`'s JSON as three options, its `recommended` first (plan now only when no placeholder, nothing under
`## Not yet specified` and no open question is left; else another round), and do what the user picks:

- **plan now**: `/plan` (the plan skill fills the steps into this same plan.md in place:
  [spec-in-place](../plan/references/spec-in-place.md); offer `/spec approve` first when the user wants it marked).
- **bring it in for later**: the user's `/mtm` hitches the field, the tollman's train lands it; planned later by
  `/plan new --spec <n>`.
- **another round**: `/grill-plan` on the spec (grill-me questions on spec.md, the plan's own ledger), then the spec
  text and changed designs updated in place (`/design update <feat>`), `spec.py iterate`, one commit, the checkpoint
  again.

## 3. Update later

`/spec <n> update` (D6, D8 idea 5), any time, also after it was approved, brought in or planned:

1. Ask what changed (one line is enough); record it as a decision in the plan's `decisions.md` naming the decision it
   replaces.
2. `python3 $S/spec.py update <n> --what "<what changed>"`: back to draft, a new round; a plan with steps gets
   `spec_review` in its plan.md (its Brief and steps are never rewritten here; `plan.py check` reports
   `plan-spec-review` until the plan's session reviewed them and ran `spec.py reviewed <n>`).
3. The round as in the one pass (spec text, questions, `/design update <feat>` for each changed design: a new version,
   the old one kept), `spec.py iterate`, one commit, the checkpoint. Tell a planned spec's foreman.

## Continue

`/spec <n>`: `python3 $S/spec.py show <n> --json` (sections, placeholders left, design page, state, round, review due);
work on what the user asks or what is left, by the steps above.

## Rules

- A spec round never writes product code. You never accept a design and never answer your own question: designs are
  accepted by the user on the design page only (`/design serve`), questions answered only by the user.
- plan.md is written only by `spec.py` and the plan skill (`/plan` fills it in place, never a second folder or copy).
  Never number a folder by hand.
- In a farm whose plans live in its plan store (`hal2-cli-plans home` says `store`, D9): every `spec.py` answer adds
  `dir`, the plan's copy outside the tree; write spec.md there and run `spec.py show` (or the next command) to apply
  it; other files of the plan through the plan skill's `plan.py edit`/`apply`; commit no plan file there.
- A spec that waits for another plan is declared when it is planned (`hal2-cli-plans depends add`, the plan skill's
  [dependencies](../plan/references/dependencies.md)); the spec text only says why.
- A spec passes the checkers as it is: `python3 <plan skill>/scripts/plan.py check plans/<folder>` and
  `hal2-cli-records check`.

Prerequisites: `scripts/check-prerequisites.sh` (python3, git); the plan skill beside this one (`plan_number.py`,
`names.py`, `envelope.py`, `spec_link.py`) comes with the plugin.
