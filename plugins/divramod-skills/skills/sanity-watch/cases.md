# sanity-watch cases

Newest first. There is one case per failure class and cause; a recurrence adds a line under its case's
**Occurrences**. The **signature** is what `scan.py scan --json` and the transcript show. **Fix plan** is one of:

- `none`;
- `running (<slot>, brief <path>)`;
- `landed <plan> <date>`;
- `n/a` (not fixable in hal2).

## 2026-10-01 · F6 false positive: the user interrupted the turn

- **Signature**: F6 with the session `sleeping`; the transcript's last turn ends in `[Request interrupted by user
  for tool use]` (a rejected question or tool call), `last_assistant` is "No response requested." after a session
  restart, and the plan's next step is still the template's `<step>`.
- **Cause**: the user stopped the agent themselves, before the plan was even written. The scan treats any ended
  turn inside a plan as early, without reading the interruption or noticing the plan has no real steps. A gap in
  sanity-watch's scan, not a hal2 bug.
- **Occurrences**:
  - 2026-10-01 23:41, hal2 slot 04, session 18f09c21, plan 0094 plugin-n8n 2 (0/2, template); the user rejected
    its timing question at 15:22; left alone (`count`).
- **Fix plan**: n/a (a fix plan never edits this skill). Proposal for the user: skip F6 when the last turn was
  interrupted by the user, or when the plan's next step is the placeholder `<step>`.
- **Would have caught it sooner**: nothing to catch.

## 2026-10-01 · F6 background subagent stopped without waking its parent

- **Signature**: F6 with the session `sleeping`, `last_assistant` saying a subagent is doing the next steps; the hook
  record's last event is `SubagentStop`, the session's `.tasks/` still lists that subagent, but the subagent's
  transcript ends in a `tool_use` with no result, has been silent for long, and no process of it runs.
- **Cause**: as far as the evidence shows, Claude Code's: the background subagent's Bash call (`rm -f` of snapshots
  + `swift test`) raised a permission request (chronicle `blocked-permission`), 8 s later `SubagentStop` fired, and
  the parent got no completion notification, so it was never re-invoked. hal2's part: its `.tasks/` record keeps the
  dead subagent, so the session looks like one that waits on live background work.
- **Occurrences**:
  - 2026-10-01 16:41, hal2 slot 01, session cdf89c43, plan 0096 step 9, subagent ab51caf0 dead since 15:48 (53 min,
    11 uncommitted files); resume prompt typed, but neither its newline nor one `--key enter` submitted it (state
    stayed `sleeping`); escalated by notification, the prompt is left in the input box.
- **Fix plan**: none (first occurrence, root cause outside hal2; due at the second one).
- **Would have caught it sooner**: a `SubagentStop` for a task that stays in `.tasks/` while the parent is idle, or
  a background subagent whose transcript is silent for > 10 min with an unanswered `tool_use`, flagged by the scan
  (a class of its own instead of F6, 15 min instead of 53).
- **Scan since skills plan 0016**: this is the class F14 "subagent dead under an idle parent": a resting session
  whose listed background subagents all have a transcript quiet for 20 min or more, whatever its plan.

## 2026-10-01 · F11 autoclear failed: ignored-soft-stop

- **Signature**: autoclear job record `state: failed`, `reason: ignored-soft-stop`, message "the turn after the
  typed hand-off request ended without a hand-off", `new_session: null`; the session is left `sleeping`.
- **Cause**: the agent's turn after hal2 typed the hand-off request ended without running /handoff, so the
  clear-and-continue job gave up. Root cause not analysed here: fix-autoclear's.
- **Occurrences**:
  - 2026-10-01 07:23, hal2 slot 02, session 88945508, plan 0089 roadmap B (12/13, last step needs the user's
    Touch ID); handed over by notification.
- **Fix plan**: n/a (F11 is fix-autoclear's: `/fix-autoclear 02`).
- **Would have caught it sooner**: the notification itself.

## 2026-09-30 · F9 permission prompt waiting for the user

- **Signature**: state `blocked-permission`, `waiting_minutes` past the threshold.
- **Cause**: a tool call needs the user's permission; by design only the user answers it.
- **Occurrences**:
  - 2026-09-30 19:41, hal2 slot 03, session 59c32fad, plan 0081 skills 6 new skill fixer, 48 min; escalated by
    notification.
  - 2026-10-01 03:41, hal2 slot 04, session 18f09c21, plan 0094 plugin-n8n 2, 59 min; escalated by notification.
  - 2026-10-01 06:11, hal2 slot 01, session dcc15173, plan 0084, 58 min; escalated by notification.
  - 2026-10-02 00:11, hal2 slot 09, session 10af9e2e, plan 0101 Hub stack e2e, 57 min (the plan skill's "Run now /
    another autogrill round" question, shown as `blocked-permission`); escalated by notification.
- **Fix plan**: n/a (dialogs are the user's).
- **Would have caught it sooner**: the notification itself.

## 2026-09-30 · F6 false positive: turn ended while waiting on its own background task

- **Signature**: F6 with the session `sleeping`, `last_assistant` saying it waits for a background command
  (e.g. `watch.py ... --wait`) whose completion notification will wake it; that process is still alive.
- **Cause**: the scan treats any ended turn inside a plan as early, without checking the session's live background
  tasks (hal2-agents' `.tasks/` records). Not a hal2 bug: a gap in sanity-watch's scan.
- **Scan since skills plan 0016**: closed: a resting session with a live background task (a shell, a monitor, a
  subagent whose transcript moved in the last 20 min; `background_tasks` of `hal2-cli-agents list --json`) is never
  reported.
- **Occurrences**:
  - 2026-09-30 18:41, hal2 slot 00, session a1530b9c, plan 0082 roadmap coordinator, waiting on plan 0074 in slot
    12; left alone (`count`).
  - 2026-09-30 19:11, hal2 slot 11, session 40ec9473, plan 0085 Mac upgrade benchmarks, waiting on its background
    `bench-landing` run (still running); left alone (`count`).
  - 2026-09-30 20:41, hal2 slot 00, session a1530b9c, plan 0082 again: its watch timed out and was restarted,
    slot 12 still waits for the user; left alone (`count`).
  - 2026-09-30 21:41, hal2 slot 00, session a1530b9c, plan 0082 again, still waiting on its background watch;
    left alone (`count`).
  - 2026-09-30 22:41, hal2 slot 00, session a1530b9c, plan 0082 again (watch restarted); left alone (`count`).
  - 2026-09-30 22:41, hal2 slot 11, session 40ec9473, plan 0085 step 7, waiting on its detached quiet-then-bench
    waiter (hours, overnight); left alone (`count`).
  - 2026-10-01 00:41, hal2 slot 00 (plan 0082, now on line B, waiting for plan 0089) and slot 11 (plan 0085, the
    quiet-Mac waiter still waiting); both left alone (`count`).
  - 2026-10-01 04:41, hal2 slot 00, new session ba3f7973, plan 0082 line B: waits for slot 02's plan, woken by
    its own 30-minute checks (a schedule, not a background task); left alone (`count`).
  - 2026-10-01 09:18, hal2 slot 00, session ba3f7973, plan 0082 line B again: its periodic check, still waiting
    for the user's enrollments in slot 02; left alone (`count`).
- **Fix plan**: n/a (a fix plan never edits this skill). Proposal for the user: skip F6 when the session has a
  running background task in its hook record's `.tasks/`.
- **Would have caught it sooner**: the scan reading the session's background tasks.

## 2026-09-30 · F1 connection lost mid-response, never resumed by hal2

- **Signature**:
  - chronicle `failed`, hook record event `StopFailure`;
  - the transcript's last entry is `isApiErrorMessage: true`, `error: "server_error"`, text `API Error: Connection
    lost mid-response. The response above may be incomplete.`;
  - nothing follows until a human types `continue`.
- **Cause**:
  - Claude Code does not retry a connection lost after a completed block, by design: resending could run tools
    twice.
  - hal2 sees the stop (`failed`), but nothing reacts: the autoclear sweep skips `failed` sessions
    (`hal2-agents` `sweep.rs`), and the hook drops StopFailure's error kind and message.
- **Occurrences**:
  - 2026-09-30 12:21, hal2 slot 01, session 91b9104c, plan 0075 step 6, resumed by the user at 12:22 (shot 8
    plugin-agents); seen by the watcher's round at 14:44 as `count`.
- **Fix plan**: landed 0080 2026-09-30 (fix agent in slot 10, brief
  ~/skills/sanity-watch/incidents/2026-09-30-f1-connection-lost-never-resumed.md): the stop's reason in the record,
  resume of F1–F3 by hal2-agents with a budget, billing never.
- **Would have caught it sooner**: a `reason` on the chronicle's `failed` line; a sweep log line "failed session
  seen, not handled".

## 2026-09-2x · F2 network down (ENOTFOUND)

- **Signature**: `server_error`, text `API Error: Can't reach the API server — check your internet or DNS (ENOTFOUND)`.
- **Cause**: the network was gone for longer than Claude Code's retries.
- **Occurrences**:
  - one in the 7 days before 2026-09-30 (found by the research scan; session not recorded).
- **Fix plan**: none. Fold it into F1's fix: resume once the API answers again.
- **Would have caught it sooner**: the same as F1.

## 2026-09-2x · F3 Mac slept mid-response

- **Signature**: `server_error`, text `API Error: Your computer went to sleep mid-response. The response above may be
  incomplete.`
- **Cause**: the Mac slept while an agent was working.
- **Occurrences**:
  - one in the 7 days before 2026-09-30 (research scan).
  - 2026-10-02 00:57, hal2 slot 00, session 698c1ff5, plan 0091 roadmap D; the session went on by itself 53 ms
    later (`count`). The Mac had idle-slept at 00:21 on AC with agents working and kept cycling through maintenance
    sleep (15 min) and DarkWakes (2 min).
  - 2026-10-02 01:32, hal2 slot 00, session a1061dc1, plan 0091 roadmap D; went on by itself (`count`); the Mac
    still cycles through maintenance sleep.
  - 2026-10-02 04:16, hal2 slot 00, session 6595dae5, plan 0091 roadmap D; resumed by hal2-agents' own resume
    (plan 0080, attempt 1/2) at 04:18, working again by 04:19; the watcher sent nothing (`count`).
- **Fix plan**: running (slot 13, pane t:tmuq5kc2mrfy2, brief
  ~/skills/sanity-watch/incidents/2026-10-02-f3-mac-slept-mid-response.md). Research 0015's idea 3: a power
  assertion while agents work, and a sweep on wake.
- **Would have caught it sooner**: a wake notification in hal2 that runs the sweep at once.

## 2026-09-2x · F5 credit balance too low

- **Signature**: `billing_error`, text `Credit balance is too low`.
- **Cause**: the account ran out of credit. This is not a hal2 bug.
- **Occurrences**:
  - two in the 7 days before 2026-09-30 (research scan).
- **Fix plan**: n/a. The watcher escalates by notification and never resumes.
- **Would have caught it sooner**: the notification itself.
