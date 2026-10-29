---
name: fix-autoclear
description: Analyze and fix a failure of hal2's autoclear (the context guard, the clear-and-continue job and the sweep that hand off, /clear and continue a plan-running Claude session at the context threshold) — from the worktree it happened in (`/fix-autoclear 02`; screenshots optional, the pane's screen is captured read-only) or a shot hal2 reported in the global `skill-fix-autoclear` shotfile. Collects the evidence (job record and log, guard markers, the session's transcript tail, the sweep's log), matches it against known failure cases, finds the root cause in hal2's code, fixes it with a regression test replaying the incident, installs the fix, gets the stuck session going again and records the case so the skill learns. `/fix-autoclear doctor` looks for autoclear failures nobody reported; `/fix-autoclear selfcheck` checks this skill's insider knowledge against the code. Use when the user says /fix-autoclear, "autoclear did not work / is stuck / did not continue", or shows a pane stopped by `hal2 stopped this turn` / `stopped for the hand-off`. `/fix-autoclear h` shows help.
---

# fix-autoclear

The user names the agent (`02` or `hal2 wt 02`, a few words on what it did instead; screenshots optional), or hal2
reported the failure itself as a shot in the global shotfile `skill-fix-autoclear` (`<repo> wt <NN>: <reason>`, with the
command to run). Name agents by repository and worktree (`hal2 wt 02`), never by pane id. You find
why hal2's autoclear did not hand off, clear and continue, fix it in hal2 and make the case known to this skill.
`S=<skill-dir>/scripts`, `E="python3 $S/evidence.py"`. Ask questions by the global question
rule (background first; ~/.claude/CLAUDE.md), recommended option first.

| Call | Does |
|---|---|
| `/fix-autoclear <worktree> [<description>]` | analyze one incident (`02`, `main`; `--repo <name>` outside that repo) and fix it |
| `/fix-autoclear doctor [<hours>]` | list autoclear failures of the last hours (default 24) nobody reported, offer to analyze each |
| `/fix-autoclear selfcheck` | check the insider knowledge below against hal2's code; fix the drift |
| `/fix-autoclear h`, `/fix-autoclear help` | print this table and stop |

## 1. Collect the evidence

1. `$E show --worktree <NN> [--repo <name>] [--hours 3]` (or `--pane`, `--session` when the agent is gone) prints
   the settings and installed binary, the agent now, **its screen** (captured with `hal2-cli-agents capture`,
   read-only: never type into the pane), the pane's job record and job log, the guard markers of its sessions, each session's transcript
   tail (tools, hook denials, typed requests), the guard's decisions (`guard.log`), the sweep's rounds for the pane
   (`sweep.log`) and hal2-api's sweep lines. A missing tool exits 2: run
   `bash $S/install-prerequisites.sh`.
2. Read the screen (and screenshots when the user gave some): the pane's last lines (the hook denial, `hal2
   stopped this turn ...`, `Interrupted`, the input box, a dialog), the statusline (context %, plan).
3. `$E doctor --hours 6` shows whether other panes failed the same way. A session with autoclear off (the user
   switched it off) is no failure: the doctor lists it apart (`off`) and the farmer's `duty:autoclear` never touches it
   (`evidence.autoclear_off`: a marker `gave_up` without the sweep's `MAX_ATTEMPTS` attempts, a `rearm_percent` no
   context reaches (>= 100), or an agent's `autoclear_off: true` once hal2's per-session switch exists, shot
   plugin-agents #31). Never "fix" or clear-and-continue such a session. A job that failed for a reason hal2 itself
   does not report (`evidence.QUIET`: the session or its agent ended on its own, the request never became a job) is
   no failure either: the doctor lists it apart (`quiet`, "ended on their own") and the farmer's duty never sees it.
   Look at one only when the user says its session should have gone on.
4. Build the **timeline**: soft stop → what the model did → hard stop? → job phases → sweep ticks → where it
   stopped. The failure is the first step that did not do what the insider knowledge below says it does.

## 2. Match known cases first

Read [cases.md](cases.md): each case has a **signature** (the job's `reason`, log lines, the marker's stage,
what the transcript shows). A matching signature points to the cause and the code; check it still applies
(the fix may have regressed, or it is a new variant). No match: a new case.

## 3. Find the root cause

Work in a hal2 worktree (not the main checkout; `/mfm` first). The code is in `code/rust/libs/hal2-agents/src/`,
see **Insider knowledge**. Reproduce the decision with the module's tests: every decision runs against an `Env`
trait with a fake in the tests (`guard::guard`, `autoclear::run`, `sweep::sweep`), so a failing test from the real
inputs (the Bash command, the screen text, the records) is the proof. Distinguish:

- **hal2 bug** (the guard's classification, the job's screen reading, the sweep's decision): fix the code;
- **model behaviour** (the session ignored the stop, did the wrong thing): fix the stop's wording
  (`guard::soft_reason`, `HANDOFF_TOOLS`, `autoclear`'s typed request) or the handoff/plan skills' instructions;
- **environment** (old binary installed, hooks missing, tmux, the screen layout changed after a Claude Code update):
  fix the setup (`hal2-cli-agents install-hooks claude`, `cargo install`) and teach the scraper the new layout.

## 4. Fix and verify

1. Regression test **from the incident**: `$E capture --worktree <NN> --out <scratch>/incident` saves the screen,
   agent, job record and log, markers, transcript tails, guard and sweep lines as files (its README.md says which is
   which). Turn them into test inputs: `screen.txt` (trimmed to the lines that matter) into
   `code/rust/libs/hal2-agents/src/fixtures/screens/<case>.txt` for a scrape test, the record, log or command into
   the test's input, with a comment naming the agent (`hal2 wt 02`) and date. It fails before the fix. Capture
   while the pane still shows the incident; afterwards only the files remain.
2. Fix, then `cargo fmt --all`, `cargo nextest run -p hal2-agents`, `cargo clippy -p hal2-agents --all-targets`
   (from `code/rust/`).
3. `cargo install --path apps/hal2-cli-agents` so the hooks and jobs run the fix now (hal2-api's sweep runs its
   own copy: `cargo install --path apps/hal2-api && hal2-api install` when the sweep changed).
4. Commit in the worktree (one commit, `fix(<NNNN>|<step>): ...` in a plan, else `fix(agents): ...`, saying the incident and the cause). Landing is the user's
   (`/mtm`).

## 5. Get the stuck session going

Ask first (it types into the user's pane): rerun the job for the pane with `hal2-cli-agents clear-and-continue
--pane %<n> --session <id> --await-handoff --detach` (it asks for the hand-off again when none was written, clears
and continues), or leave it to the next sweep tick (every `sweep_minutes`, it retries up to 3 attempts per
session), or the user continues by hand. Then watch the job log until `continued`.

**A paused field is never resumed** (hal2 plan 0458): `hal2-cli-git worktree paused` lists the paused fields. The
doctor may list one of their failures, but never rerun a job, send or continue in it; tell the farmer in one line
instead. Only the farmer resumes a field (`worktree resume <NN>`, on the user's go).

## 6. Learn

1. Append the case to [cases.md](cases.md) (newest first): date, worktree, **signature**, root cause, fix commit,
   the regression test's name, and what would have caught it sooner.
2. **Update this skill** whenever the analysis showed something it did not know or got wrong: the insider
   knowledge (new file, state, reason, flag, threshold), a step that was missing, or `evidence.py` (what it should
   have collected: add it, with its test). Keep the `<!-- names -->` block to real names. Run `$E selfcheck`: it
   must print `ok`. Change the skill with the case in a hal2 worktree and land it with the worktree's `/mtm`, never a commit on a main checkout.
3. A failure **class** that keeps coming back (a second case with the same cause area) gets a hal2 shot or plan
   that removes the class, not another patch: say so in the report.

## 7. Report

The timeline in a few lines, the root cause, the fix (commit, test), what was installed, the session's state now,
the case added and what changed in this skill.

## Insider knowledge

As of hal2 plan 0057 (the job), research 0010, plan 0066 (guard and sweep), plan 0077 (reports, early retries) and
plan 0174 (a clear from outside, the effort level) and plan 0181 (every Claude session: kinds, tickets, the queued
clear). Keep this true: `$E selfcheck`.

**Three parts, one flow.**

1. **The guard** (`code/rust/libs/hal2-agents/src/guard.rs`), inside Claude's `PreToolUse` hook
   (`hal2-cli-agents hook claude PreToolUse`): a main session (no `agent_id`) at or above `[autoclear] percent`
   gets a **soft stop**, with or without a plan with steps left and with or without a merge-queue ticket (plan
   0181; `plan_guard.rs`'s open plan only goes to the log): the tool is denied once with "run /handoff now" (the
   command of the session's kind, `code/rust/libs/hal2-agents/src/autoclear/kind.rs`: the plain kind `/handoff`,
   `HANDOFF.md` or the current plan's own `plans/<plan>/handoff.md` (hal2 plan 0206: the one written last),
   `/handoff c`; the role's worktree `farmer-<repo>` `/farmer handoff`, `roles/farmer/handoff.md`,
   `/farmer act`; agents.toml's `[[autoclear.kinds]]` overrides), the marker
   `<state>/agents/autoclear/<session>.guard` is written (stage `soft`) and the job is started detached with
   `--await-handoff`. After it, **hand-off tools pass** (`handoff_tool`: Read/Grep/Glob, the handoff skill,
   Write/Edit of `HANDOFF.md`, `INTENT.md`, `plans/` (a plan's `handoff.md` and its ledgers), `.adr/`, TaskStop, Bash whose every segment starts with a
   `HANDOFF_PROGRAMS` entry — git, cat, ls, grep, sed, cut, tr, hal2-cli-agents, ...; never awk — or runs a `HANDOFF_SCRIPTS`
   script; a kind adds its own skill, its file's folder and its skill's scripts:
   `code/rust/libs/hal2-agents/src/guard/tools.rs`). Anything else is a **hard stop**: denied with `continue:
   false`, the turn ends (stage `hard`). **A landing's own commands**
   (`code/rust/libs/hal2-agents/src/guard/landing.rs`): `hal2-cli-git worktree queue|release|stop` always pass;
   `hal2-cli-git worktree reserve|merge-to-main` and `Skill` mtm pass only while the checkout holds a ticket (the log's `pass (a
   landing's own command)`), without one they would start a landing and are stopped like any tool; every other tool
   of a checkout with a ticket is stopped, and both stop texts end with `This checkout holds a merge-queue ticket
   (<state>, pid <n>): ...` (the hand-off names it, never stops it). Still passing: a subagent's tool, a session in
   neither tmux nor a hal2 terminal, a marker with `gave_up`, a cancelled marker below its rearm percent,
   `[autoclear] enabled = false`. A cancelled job re-arms the guard `REARM_POINTS` (5) higher.
2. **The job** (`autoclear.rs`, `hal2-cli-agents clear-and-continue`, one per pane, lock `<n>.lock`): record
   `<state>/agents/autoclear/<n>.json`, log `<n>.log` (pane `%<n>`, or `<id>` for a terminal host `t:<id>`).
   Phases: `interrupting` (sweep's `--interrupt`: Escape) → `waiting` (turn over: a `Stop` record, or the screen
   reading `hook stopped continuation`/`Interrupted` twice; a session idle before the request: idle twice; box
   empty; a merge-queue ticket is only logged, `landing: the checkout has a ticket in the merge queue (...): not
   waited for`; a user's draft is waited out `Timings::draft_wait` (60 min), then `box-not-ready`, and past
   `Timings::draft_alert` (3 min) raises one alert per draft: the record's `waiting_on`/`waiting_since`, a chronicle
   line with `note: continue-blocked: ...`, a notification (`draft_alert.rs`, plan 0139; `evidence.py doctor` lists
   it as `blocked`); hal2's own request left in the box (begins `hal2 stopped this turn:` or ends `hal2 then clears
   the session and continues.`), or text the pane's send log says hal2 typed (`submit::logged`: any source, 24 h),
   is no draft: emptied, C-u until empty, one row per press) → `requesting` (with
   `--await-handoff`: no hand-off (`handoff.rs`: `HANDOFF.md` or the current plan's `handoff.md` written since the request, or current: written at most
   `CURRENT_WINDOW` (10 min) before it, not before the newest commit of real work, nothing uncommitted outside
   `HANDOFF_PATHS`; the log's `hand-off check:` line says which and why) → types the hand-off request (read back
   by words; a multi-row box showing only the request's last rows, a short pane scrolling it, counts as typed; a
   failed read-back empties the box), waits for that turn;
   a second turn without a hand-off fails `ignored-soft-stop`) → `clearing` (`i` in vim mode, `/clear` typed and
   read back, Enter; confirmed by a `SessionStart` record, source `clear`) → `continuing` (the effort level, see
   below; then the kind's prompt, `DEFAULT_PROMPT` `/handoff c`, typed, read back, sent) → `continued`. The job
   needs no open plan (the refusal no-open-plan is gone since plan 0181; `--without-plan` does nothing).
   **Typing goes through the shared guard** (`code/rust/libs/hal2-agents/src/prompt_guard.rs` + `prompt_guard/typing.rs`,
   plan 0231 step 7; replaces the job's own `autoclear/keyboard.rs`): `PromptGuard::prepare()` (marker, INSERT),
   `type_text()`, `insert()`, `empty()`, `prompt_guard::turn()`; refusals `Refusal {Pane, Gone, NoBox, Draft,
   NotInsert, KeyboardHeld, NotShown, Queued}`. It greps the screen for the mod's marker `[pane has the keyboard`
   (`scrape::keyboard_held`; the title line of the mod pane, 0.5.0) and, after a turn's end, presses one Escape;
   mid-turn it refuses `KeyboardHeld`. A typed text reading back as nothing after an ended turn gets one Escape,
   `ensure_insert` and a second try (log `nothing showed: the prompt may not have the keyboard ...`). Never on the
   busy path (Escape interrupts a working turn). `libs/hal2-agents/src/guarded.rs` (step 9) puts every other path
   through it (the CLI send and send-command verbs, node agents.send, shooter and hal2-tell): a refusal is exit 10 (3 before hal2 plan
   0318) `not sent: <reason>`, a draft in the box `not-empty`. Raw on purpose: `--key`, node `keys`/`answer`. Trap: never press `q`
   (it lands in the prompt); only Escape. A `SubagentStop` writes no record (step 8), `stale.rs` decides a stale record.
   **The busy path** (`code/rust/libs/hal2-agents/src/autoclear/busy.rs`, `queued.rs` and `queued_clear.rs` beside
   it, the queue read by `code/rust/libs/hal2-agents/src/scrape/queued.rs`; plan 0181): a session that is never
   idle (a farmer under a stream of messages). While the job waits for the turn's end it looks every 5 s; once it
   has wanted the same thing for `Timings::busy_wait` (60 s) and the session works with an empty box (a draft or a
   dialog restarts the clock), it types into the running turn: with the hand-off written `/clear` and behind it
   the prompt, which Claude Code lists as queued input above the spinner (lines starting `❯`/`›`, the box reading
   `Press up to edit queued messages`) and runs at the turn's end; after a cut-off turn the hand-off request. The
   new session's start is adopted like a clear from outside. No `/effort` on this path (logged).
   `Timings::queued_wait` (10 min) bounds it: `queue-unconfirmed` (Enter did not send, the lines do not show
   queued in order, or the clear did not run in time); queued input is never taken back.
   **A clear from outside** (`code/rust/libs/hal2-agents/src/autoclear/outside.rs`, plan 0174): when the old
   session's `SessionEnd` record comes while the job waits (a `/clear` someone else typed, or one Claude Code had
   queued), the job looks `Timings::clear_confirm` (30 s) for the pane's new session (`SessionStart`, source
   `clear`, since that end). Found: the log says `cleared from outside (this job typed no /clear): new session
   <id>`, the record gets `new_session`, and the job waits `Timings::outside_prompt_wait` (20 s) for whoever cleared
   to send their own prompt: the new session past `SessionStart` ends the job `cancelled` with `resolved: cleared and
   continued from outside`, a draft in its box `cancelled` with `... left to its writer`, a checkout without an open
   plan went on like any other since plan 0181; otherwise the job goes on with `continuing`
   (no hand-off before the clear is only logged). Not found, a `SessionStart` with source `resume`, or the agent's
   process gone: `session-ended`, message `the session ended (reason <SessionEnd's reason>), no new session in the
   pane`.
   **The effort level** (`code/rust/libs/hal2-agents/src/autoclear/effort.rs`, the screen read by
   `code/rust/libs/hal2-agents/src/scrape/effort.rs`): with `[autoclear] effort` set, after the clear (the job's own
   or one from outside) and before the prompt the job reads the level from the screen (the box's corner `◐ medium ·
   /effort`, else the banner's `with medium effort`) and types `/effort <level>` only when it differs; a dialog
   `Change effort level?` is answered with Enter while it stands on `Yes, switch`, else closed with Escape. Best
   effort: `effort: not set to <level> (<why>): the prompt goes out anyway`, never a fail reason; every step is an
   `effort: ...` line in the job log. `/effort` also rewrites the user's default in `~/.claude/settings.json` (a trap: a plan's session whose effort differs from it
   drifts after a clear). Where the level comes from: a clear that `/handoff clear` starts passes `--effort` from the plan's
   `run` key (`drift.py --clear`, plan 0016 D8); a clear hal2's guard starts itself still types `[autoclear] effort`
   until hal2's change (plan 0015's hal2-changes.md) lands.
3. **The sweep** (`sweep.rs`, run by hal2-api every `sweep_minutes`, log `~/Library/Logs/hal2-api.log`, lines
   `hal2_api::sweep`): takes a session that runs a plan with steps left or has a guard marker (plan or not); an
   idle session without both is left alone (`no plan with steps left`), a merge-queue ticket skips nothing (also
   not the resume). S1 a turn ended above the threshold without a running job → starts the job; S13 a soft stop
   older than `grace_minutes` still working without a hand-off → the job with `--interrupt`. After `MAX_ATTEMPTS`
   (3) jobs for a session it gives up (`attempts` job record, marker `gave_up`: the guard then lets everything pass).
   `wanted_again`: a session whose last job failed (not quiet, not `attempts`, not cancelled) is retried also below the
   threshold (34.x% shows as 35%), counting against `MAX_ATTEMPTS`, after `RETRY_BACKOFF`; log `start (retrying a
   failed job below the threshold, context ..., attempt n)`.
4. **Reports and early retries** (`report.rs`, hal2-api's `apps/hal2-api/src/sweep.rs`): every 10 s (`CHECK`)
   hal2-api looks for job records failed in the last 24 h and not yet in `autoclear/reported.json`. Each runs a
   sweep round early: the first retry at once, the next 1 and 5 minutes after the previous failure
   (`RETRY_BACKOFF`; the sweep skips with `backing off after a failure` until then). All but `agent-gone`,
   `session-ended`, `already-running`, `invalid-request` (`evidence.QUIET`) go into the global shotfile
   `skill-fix-autoclear`, one shot per session (`<repo> wt <NN>: <reason>`, the job's facts, `/fix-autoclear <NN>`); later
   failures of the session are appended while the shot is open. `sweep.log` gets a `failure ...: reported in skill-fix-autoclear shot <n>` line.

**Names** (job states and fail reasons, as the records write them):
<!-- names -->
states `waiting`, `requesting`, `interrupting`, `clearing`, `continuing`, `continued`, `failed`, `cancelled`;
reasons `ignored-soft-stop` (the session did not hand off after the typed request: often the guard denied the
hand-off's own tool, or the model answered "already done" for a hand-off the check did not accept), `typing-mismatch` (the box did not read back what was typed: screen scraping, vim mode),
`clear-unconfirmed`, `prompt-unconfirmed` (no `SessionStart`/prompt seen in time), `box-not-ready`,
`not-insert-mode`, `not-interrupted`, `queue-unconfirmed` (the busy path's queued `/clear` or prompt), `agent-gone`, `session-ended`, `already-running`, `invalid-request`,
`job-gone` (the job's process died), `attempts` (the sweep gave up), `tmux`, `io`
<!-- /names -->

**Settings**: `~/.config/hal2/agents.toml` `[autoclear] enabled, percent (35), sweep_minutes (5), grace_minutes
(15), effort (unset: nothing typed; `low`, `medium`, `high`, `xhigh`, `max`)`; `hal2-cli-agents settings` prints
them. The statusline's percent and the guard's come from the same transcript (`context.rs`).

**Logs** (all in `<state>/agents/autoclear/`, each moved to `<name>.1` past 2 MB): `<n>.log` the job (phases, its
request's flags, every change of the session's hook record, each hand-off and plan check, the screen's tail when it
reads nothing known); `guard.log` a line per guard decision within 5 points of the threshold or with a marker
(`<time> <pane> <session> <tool> <command>: <verdict> (<why>), context <p>, marker <stage>`, after the soft stop
`; not a hand-off: <the command that failed the check>`); `sweep.log` per round, every Claude agent's context,
state, plan and `skip (<why>)` or what it started, plus a line per reported failure; `reported.json` the reported
failures and each session's shot number.

**The host's input log** (`code/rust/libs/hal2-pty/src/hostlog.rs`, plan 0231): a terminal host (`t:<id>`) writes its
input path into `<state>/agents/<id>.log` beside the host (`grep 'hal2-pty host' <id>.log`): `client <n> hello role=...`,
`input role=<role> bytes=<count>` (never the bytes), `end: detached|connection gone|refused`, `pty write failed: ...`,
`input thread ended`. Keys that show there but not in the box: the keyboard is held (see the traps).

**Other files**: the agents' hook records `<state>/agents/<session>.json` (state, last event), the send log
`<state>/agents/sent/<n>.jsonl` (what hal2 typed, source `autoclear`), transcripts
`~/.claude/projects/<cwd with / as ->/<session>.jsonl`. The scraper that reads Claude's screen: `scrape.rs`
(`claude_screen`, the input box).

**Traps**: a Claude Code mod's pane or band (`s: subagents [-]` under an empty box) holding the keyboard: keys reach the host
and Claude's TTY (0 unread bytes) but never the box; one Escape gives it back (the shared guard does since plan 0231); an old `~/.cargo/bin/hal2-cli-agents` (the hooks run it: check its build time against the fix); a
Claude Code update that changes the screen (box, `-- INSERT --`, the history box's `─── History n/m ───` rule, the
stop lines); an old `hal2-api` (the reports and early retries run in it: `hal2-api install` after installing);
`* Waiting for API response · will retry` is Claude still working, not a failure; a short pane (hal2 never sizes it:
`tmux display -p -t %<n> '#{pane_width}x#{pane_height}'`) shows a long prompt's last rows only; a job that waits
forever keeps the sweep from counting attempts (every round: `skip (a job runs for the pane)`).
