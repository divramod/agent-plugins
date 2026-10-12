# fix-autoclear cases

Newest first. One case per root cause; a recurrence adds a line under its case. The **signature** is what
`evidence.py show` prints that identifies the case.

## 2026-10-10 · a `SubagentStop` record ended the turn early: `/clear` queued, `clear-unconfirmed` (hal2 wt 03)

- **Signature**: job `failed` `clear-unconfirmed` at 11:17; its log shows the turn taken as over although the session
  still worked (a `SubagentStop` hook record, state `done`, 0.3 s before the request, written over the main
  session's record); the typed `/clear` was queued by Claude Code (queued-input lines above the spinner), no `SessionStart`.
  Shot 19 (hal2 wt 02) had the same trigger; its failure, the narrow-pane read, is another cause and stays open.
- **Cause**: `state.rs` mapped Claude's `SubagentStop` to `done` on the main session's record.
- **Fix**: hal2 plan 0231 step 8, `0bea84fab`: no record for `SubagentStop`; `autoclear/stale.rs` `ends_turn()` also
  needs no running subagent on the screen (`scrape::claude_subagents`, the `◯` rows under `⏺ main`);
  `Refusal::Queued` (`scrape::claude_queued_shown`) when a clear is already queued. Tests `incident_03_tests::*`
  (fixture `claude-idle-subagents-running.txt`, inferred). Accepted: a dead turn whose screen lists a running
  background subagent waits until it ends.

## 2026-10-10 · a stale `working` record from before the request blocked the wait forever (hal2 wt 43)

- **Signature**: job `waiting` for good (or `failed` "the job never ended"); the screen reads idle while the session's
  record says `working` since a time before the request.
- **Cause**: the wait trusted the record; a record older than the request was never cross-checked with the screen.
- **Fix**: hal2 plan 0231 step 6, `ae2dc25c4`, `autoclear/stale.rs`: log `the record says working since <time>,
  before the request, but the screen reads idle: taking the turn as over`. Fixture
  `claude-idle-stale-record-subagent.txt`; tests `incident_43_tests::*`.

## 2026-10-10 · a mod's pane held the keyboard: `/clear` typed, the box stayed empty (skills wt 30, hal2 wt 43)

- **Signature**: job `failed` `typing-mismatch: typed "/clear", the box showed Some("")`, repeated each attempt until
  `attempts`; the idle screen shows the empty box and a mod's band (`s: subagents [-]`); Claude's TTY has no unread
  input; the host's input log (before plan 0231 there was none) would show the keys arriving.
- **Cause**: the side pane of the Claude Code mod `divramod-subagent-context` held the keyboard; one Escape gave it
  back (farmer, 10:32). The job typed into it; the sweep skipped skills wt 30 below the threshold (34.x% shown as 35%).
- **Fix**: hal2 plan 0231 steps 1-3: `545f85849` (Escape, `ensure_insert`, type again), `160ac8dfa` (sweep
  `wanted_again`), `b51a1d0cb` (host input log); tests `incident_30_tests::*`, `incident_30_sweep_tests::*`,
  `host::input_reaches_the_child_after_a_viewer_vanished_and_the_log_shows_it`. The mod is not changed (the user's repo).
- **Would have caught it sooner**: the host's input log (keys arrived) and a check of the TTY's unread bytes: both
  say "the input path works, the keyboard is held". Shot 19 (hal2 wt 02, `None`) is another cause: a ~22-column pane.

## 2026-10-07 · sessions the guard never covered: a queue ticket, no open plan, never idle (hal2 wt 02, 05, farmer)

- **Signature**: no failed job at all. A session far over the threshold (the farmer's slot at 55 %, a carrier at
  49 %) whose `guard.log` lines read `pass (a landing)` or `pass (no plan with steps left)`; or a job `waiting` with
  the message `waiting for the landing` for hours (global shot 12: a train's carrier with a waiting reserve); or a
  finished `Landing: auto` plan whose `/mtm` the guard locked out (shot 11); or a refusal `no-open-plan`; or a
  farmer whose every turn's end started the next, so the job never saw an idle box.
- **Cause**: by design until then (INTENT 2026-09-29: never a landing, never without a plan with steps left), and
  the job typed only into an idle session.
- **Fix**: hal2 plan 0181 (`815fccd9f` kinds and sessions without a plan, `9b5ef0d50` tickets, `3efc72bc3` the
  queued clear): every Claude session is stopped and cleared; tests `incident_11_tests.rs`, `incident_12_tests.rs`,
  `autoclear/queued_tests.rs`.
- **Recovered**: by hand (`/handoff clear`, the farmer's `/farmer handoff`).
- **Would have caught it sooner**: `evidence.py doctor` listing sessions over the threshold whose guard only passes.
- **Benign look-alike**: `pass (a landing's own command)` beside stops of the same session is the new rule (the
  reserve or merge-to-main of a checkout with a ticket); an idle session without a plan and without a marker over
  the threshold is left alone on purpose (its next tool is stopped); `landing: ... not waited for` in a job log.

## 2026-10-06 · a /clear from outside the job taken for the session ending (hal2 wt 35)

- **Signature**: job `failed` `session-ended` ("the session ended") within a second of the turn's end; its log has
  `record: SessionEnd, state ended` and no `/clear sent`; the pane's send log (`sent/<n>.jsonl`) holds a `manual`
  `/clear` typed while the session worked (Claude Code queues it for the turn's end); a new session's `SessionStart`,
  source `clear`, in the same pane and process right after the old one's `SessionEnd`; the new session idle at 0 %.
- **Cause**: `Job::wait_for_turn_end` failed `session-ended` on the old session's `SessionEnd` record, whatever
  ended it. A `/clear` the job did not type ends the old session the same way: the job gave up at the moment its
  clear was done and only the prompt was missing.
- **Occurrences**: 2026-10-06 hal2 wt 35, `t:tmuwu7x8sr5le`, session 4b96811b: the farmer's scratch script typed
  `/clear` with `hal2-cli-agents send` at 20:51:20 into a working session, the guard's soft stop came at 21:27:37,
  the queued `/clear` ran at 21:28:15 and the job failed 0.3 s later; hal2 wt 02 typed `/handoff c` by hand at 21:29.
- **Fix**: hal2 plan 0174 step 2, commit `c770fc75`: the job looks for the pane's new session for `clear_confirm`
  and adopts the clear (`autoclear/outside.rs`); tests `incident_35_tests::*` (the incident and every branch).
- **Would have caught it sooner**: never `/clear` a working session with `send` (it is queued, and whatever was
  to follow it is lost): clear a session only with `hal2-cli-agents clear-and-continue`.
- **Benign look-alike** (hal2 wt 02, 2026-10-06 17:55, `%171`, session 5f157c8c): the weekly usage limit ended the
  turn (`StopFailure`), the session's process ended (`SessionEnd`, then a tmux restart), no new session in the pane.
  `session-ended` was right and hal2 reports no such reason, but the doctor listed every failed job, so the farmer's
  autoclear duty delegated it. Since plan 0174 step 4 the doctor lists hal2's unreported reasons apart
  (`evidence.QUIET`, `quiet`; test_evidence.py `Quiet`); its message now reads `the session ended (reason ...), no new
  session in the pane`.

## 2026-10-06 · autoclear switched off by the user, taken for a give-up and cleared (hal2 wt 02)

- **Signature**: a marker `gave_up: true` with no `attempts` (or below `MAX_ATTEMPTS`) and `rearm_percent: 1000`,
  stage `cancelled`; the farmer's log has `autoclear:<session>` with `clear-and-continue ... --await-handoff`; the job
  asks for a hand-off far below the threshold ("at 22.0% (threshold 35%)") of an idle session waiting for the user.
- **Cause**: no autoclear bug. The user's "disable the autoclear in 02" was written by hand as guard markers
  (`gave_up`, rearm 1000), the only per-session off hal2 has (shot plugin-agents #31 asks for a real switch). The
  doctor's `gave_up or attempts >= 2` took them for the sweep's give-up, and the farmer's autoclear duty acted.
- **Occurrences**: 2026-10-06 hal2 wt 02, sessions da8d4b47 and 227f49f1, `%171`; job 171 at 10:10, cancelled by
  02 at 10:12 (global shot fix-autoclear #9).
- **Fix plan**: skills plan 0011: `evidence.autoclear_off` (a `gave_up` without the sweep's attempts, a rearm no
  context reaches, an agent's `autoclear_off: true`); the doctor lists those apart (`off`), the farmer's
  `duty:autoclear` never clears or delegates them. The hal2 side (a switch that outlives the session) is #31.
- **Would have caught it sooner**: the regression tests replaying 227f49f1's marker (test_evidence.py,
  farmer's test_duties.py).

## 2026-10-05 · the farmer's order left unsent in the box, taken for a draft (hal2 wt 12)

- **Signature**: job `waiting` 13 min, its log `a draft in the input box (367 chars): waiting until it is sent or
  emptied`; the box shows a `farmer [<id>]: ...` order that the pane's send log (`sent/<n>.jsonl`) holds as `manual`
  lines, typed but never submitted (no Enter took it in a session just restored after a reboot).
- **Cause**: senders typed, then pressed Enter in a separate call without checking the session took it; the job
  knew only its own hand-off request as hal2's text. The exact trigger (restore timing in a terminal host) was not
  reproduced (hal2 plan 0139 step 1).
- **Occurrences**: 2026-10-05 hal2 wt 12, `t:tmuuu8x9vi0ql`, 08:15–08:28, the user sent the text by hand.
- **Fix plan**: hal2 plan 0139: `send --submit` (verified Enter, the text removed when not taken, exit 4), the job
  empties text the send log says hal2 typed, a person's draft over 3 min raises an alert (sanity-watch F13).
- **Would have caught it sooner**: the alert (F13) at 3 min instead of nothing for 13.

## 2026-10-04 · a scrolled request, its leftover taken for a draft, a job waiting forever (hal2 wt 02)

- **Signature**: job `waiting` for hours, its log ending `a draft in the input box (<n> chars): waiting until it is
  sent or emptied`; the job before it `failed: typing-mismatch` with `the box showed Some("<the request's later
  rows>")` and `after emptying Some("<its first rows>")`; the screen's box holds `hal2 stopped this turn: ...` (hal2's
  own request); the pane is short (119x14); `sweep.log` repeats `skip (a job runs for the pane)` every round, so no
  `attempts` ever comes. Found by the farmer's autoclear duty as "02: attempts".
- **Cause**: three links. (1) Claude Code shows only the last rows of a prompt longer than a short pane's box: the
  4-row request read back as its last 3 rows, which the exact word comparison refused. (2) One C-u removes one row of
  a wrapped prompt, so the failed job left 3 rows of its request in the box. (3) The sweep's retry took that leftover
  for the user's draft and waited on it without a time limit. Also the turn before was hard-stopped reading the plan
  through `| cut -c1-200` (`cut` was no hand-off program).
- **Fix**: hal2 plan 0136 (`df123bd1`, `5d5a5c99`, `5df961ba`) fix(agents): `shows_typed` accepts a multi-row box
  showing the typed text's last words; `empty_box` presses C-u until the box reads empty; `own_leftover` (the
  request's opening or closing) is emptied, not waited on; `Timings::draft_wait` (60 min) fails a real draft
  `box-not-ready`; `cut`, `tr`, `nl` join `HANDOFF_PROGRAMS` — tests `incident_02_tests::*`,
  `guard::tests::after_the_soft_stop_text_filters_pass`.
- **Recovered**: the stuck job cancelled after the landing installed hal2-daemon (the job ran in the daemon); the
  sweep's next round started a fixed job.
- **Would have caught it sooner**: a time limit on every wait of a job (a job that waits forever hides itself from
  the sweep's attempt count); a fake box of limited rows in the job's tests.

## 2026-10-03 · a hand-off written just before the soft stop did not count (hal2 wt 07)

- **Signature**: job `failed` `ignored-soft-stop` (several jobs, the sweep's retries); the job log's `hand-off check:
  HANDOFF.md not written since <request>` before and after the typed request; the transcript shows `Write
  .../HANDOFF.md` seconds before the guard's denial (the hand-off's commit was the denied tool), then the model
  answering "the hand-off is already done" to each typed request; the worktree clean, HEAD older than HANDOFF.md.
- **Cause**: the job counted only a `HANDOFF.md` modified at or after the request; one written 3 s before the soft
  stop was the session's real hand-off, and the model (rightly) would not write it again.
- **Fix**: hal2 plan 0123 (`36941a5c`, `e41d6146`, `902c856f`) fix(agents): `handoff.rs` judges the facts (mtime,
  newest commit of real work, uncommitted work) as `written` / `current` / `missing (why)`; the typed request asks to
  write HANDOFF.md again even when it is current — tests `incident_07_tests::*`, `handoff::tests::*`.
- **Recovered**: by the sweep's next retry with the fixed binary installed (the window is measured from the original
  request, so a retry still accepts it), or by hand when the sweep had given up.
- **Would have caught it sooner**: the check's log line naming why a HANDOFF.md did not count (now: `not written since
  ... (<why>)`, `current (written ..., last work commit ...)`).
- **Recurrence, other symptom (same day, the rerun by hand)**: a job started on the idle session hung in `waiting`, its
  log ending `record: SubagentStop, state done, at ... (before the request)`: the job waited for a turn end after
  the request. Fix: hal2 `5ca18359` (plan 0123 step 7), two idle screens with an empty box count as the end — tests
  `incident_07_an_idle_session_*`.
- **Same reason, other cause**: 2026-09-30 (hal2 wt 00), the guard split a commit message. Check the transcript for a
  denied hand-off tool before blaming the check.

## 2026-09-30 · a history-browsing box hid the typed /clear (hal2 wt 02)

- **Signature**: job `failed` `typing-mismatch` or `clear-unconfirmed`; the job log's screen tail shows the input box
  with a `─── History 96/100 ───` top rule (the user or a key had put the box into history browsing), and the typed
  `/clear` never reads back; sometimes a `* Waiting for API response · will retry` line above the box.
- **Cause**: `scrape.rs` knew only the plain box's rule, so the history box read as no box, and a key lost once was
  never typed again; the API-retry line read as an unknown state instead of a turn still working.
- **Fix**: hal2 `26eb9991` fix(agents): autoclear reads a history-browsing box, retries lost keys, sees API retries as
  working — `InputBox.history`, the typed text typed again once, fixtures `claude-input-history.txt`,
  `claude-working-api-retry.txt`.
- **Recovered**: by hand, after the fix was installed.
- **Would have caught it sooner**: a report without a screenshot (now: hal2 reports failures as shots in the global
  `skill-fix-autoclear` shotfile, plan 0077; `fix-autoclear` before plan 0214) and an immediate retry (now: the
  first retry at the next 10 s check).
- **Benign look-alike**: `* Waiting for API response · will retry` alone is Claude still working (the API retries);
  the job waits, it is no failure.

## 2026-09-30 · the hand-off's own git commit was hard-stopped (hal2 wt 00)

- **Signature**: job `failed` `ignored-soft-stop`; marker stage `hard`, `denied_tool` `Bash`; the transcript shows
  `git add ... && git commit -qm "<multi-line message>"` denied twice with `stopped for the hand-off`, once before and
  once after the typed request.
- **Cause**: `guard::segments` split a Bash command at every newline, `;`, `|` and `&`, also inside quotes, so the
  commit message's lines (`hal2-hub-identity: Zitadel ...`) read as programs that are no hand-off tool.
- **Fix**: hal2 `e9b7e03a` fix(agents): the autoclear guard lets a multi-line git commit through — quote-aware
  splitting; test `after_the_soft_stop_the_handoff_runs` (the commit) and `another_tool_after_the_soft_stop_ends_the_turn`
  (a command after a quoted message is still checked).
- **Recovered**: the sweep's next tick (attempt 1, 4 minutes later) with the fixed binary installed.
- **Would have caught it sooner**: a guard log naming the segment that failed the hand-off check; a job that asks
  again at once instead of waiting for the sweep.
