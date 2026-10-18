---
name: user-acceptance-tests
description: Walk a plan's user acceptance tests (UATs) with the user, one check per message, and record each verdict — a thin layer on `hal2-cli-plans uat list|set`, whose queued verdicts already track which checks are confirmed (no second tracker). `/uat` walks the open checks of the plan in `plans/CURRENT_PLAN`, `/uat <plan>` those of a plan (number or slug), `/uat <plan> <uat>` shows one check and takes its verdict, `/uat do [<plan>] <uat>` also runs the check's command for the user first, `/uat list [<plan>]` lists confirmed against open checks. Plain text, one check per message with its steps, the `Open:` link or `Run:` command and the expected result; the user answers pass, fail, skip or blocked with an optional note; a fail offers the shot. Use when the user says /uat, "walk the UATs", "the acceptance tests of plan 0364", "which UATs are open" or "run UAT U3". `/uat h` shows help.
---

# user-acceptance-tests (alias uat)

`S=<skill-dir>/scripts`. A plan's `uat.md` holds the checks only a human can do after the landing; `hal2-cli-plans uat` holds
their verdicts (decision D11 of hal2 plan 0364). `uat.py` is the deterministic part: it resolves the plan, reads the CLI's
JSON and prints the checks; you only walk them with the user. Never write a verdict file or a second list yourself.

| Call | Does |
|---|---|
| `/user-acceptance-tests` (`/uat`) | walk the open checks of the plan named in `plans/CURRENT_PLAN` |
| `/user-acceptance-tests <plan>` | the same for a plan (`364`, `0364`, a slug part) |
| `/user-acceptance-tests <plan> <uat>` | show one check (`U2`, `2`, `0041/U1`) and take its verdict |
| `/user-acceptance-tests do [<plan>] <uat>` | the same, but first run the check's `Run:` command and show its output |
| `/user-acceptance-tests list [<plan>]` | confirmed against open, failed, blocked and skipped checks, no walk |
| `/user-acceptance-tests h` | print this table and stop |

## List

`python3 $S/uat.py list [<plan>]` and print it as it is. Confirmed means `pass`; open means `untested`, `retest` (a pass
whose check text changed since) or never run. `fail`, `blocked` and `skip` are listed apart and are not walked again unless
the user names them, so a walk always ends.

## Walk

1. `python3 $S/uat.py open [<plan>]`: the plan, its `Before you start` line and the open checks in order. Exit 1 with
   "no open check" or "has no uat.md": say so in one line and stop. Say in one line how many are open and start.
2. One check per message, plain text, never the question dialog (the user answers by voice or in one word): the check's
   id and title, then **Open** (a `hal9k://` link) or **Run** (a command), the **Before** line when there is one, the **Steps**
   numbered, the **Expected** result. For a command the user runs, follow `commands-for-the-user-tested-and-copied`. Then:
   `pass, fail, skip or blocked? (add a note after it)`.
3. The user answers. Record it at once: `python3 $S/uat.py set <plan> <check> <verdict> [--note "<their words>"]`. A
   `pass` needs no note; give a `fail`, `blocked` or `skip` the user's words as the note.
4. A `fail` is different: before recording it, ask in one line whether to file it as a shot too (`--shot` files it in the
   plan's feature shotfile); then record once, `uat.py set ... fail --note "<words>" [--shot]`.
5. Next check. When none is left, run `uat.py list` and print it with one line: how many confirmed, which failed.

If the user says something else mid-walk (a question, "stop"), answer it first (the global rule), then offer to go on with
the same check. "Back" or "again": show the check again; its verdict can be set again (the latest counts).

## One check

`/uat <plan> <uat>`: `python3 $S/uat.py show [<plan>] <uat>`, the check as in the walk, the verdict as in steps 3 and 4,
then stop (no walk on). `/uat do ...`: before showing it, run the check's `Run:` command yourself in the plan's
checkout when it only reads or checks something (a status, a test, a build); a command that changes the machine, a
server or an account is shown and copied for the user instead. Show the command and what it printed, then ask for the
verdict. A check with only `Open:` has no command: `do` then equals the plain call.

## Rules

- The plan is the argument, else `plans/CURRENT_PLAN`; when that names no plan folder (a shot, a task), ask which plan.
- Never decide a verdict for the user; a command's success is evidence to show, not the verdict.
- A check carried from an earlier plan is `<NNNN>/U<n>`; set it with that id.
- `uat.py ... --json` gives the raw rows; `--repo <dir>` another checkout; `$HAL2_CLI_PLANS` names the CLI binary.

Prerequisites: `scripts/check-prerequisites.sh` (python3, git, `hal2-cli-plans`); without `hal2-cli-plans` say it is not
installed and stop, never another tracker (the CLI map).
