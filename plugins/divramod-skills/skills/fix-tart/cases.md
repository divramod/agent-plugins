# fix-tart cases

Newest first. One case per root cause; a recurrence adds a line under its case. The **signature** is what
`evidence.py show` prints that identifies the case; the doctor's (`scripts/signatures.py`) is named with its slug.
Times are UTC.

## 2026-10-16 22:56 - 2026-10-17 00:06 · the watchdog tore down a clone that was running its job (land run 38984579934)

- **Signature**: a runner task log with `Running job: <job>` whose last write (`command: ...`, `$ tart delete`,
  `removing ...`) comes within seconds of the supervisor's `mac vm runner restarted (off, on), attempt N: ... no
  runner job under way after N s`: task 01a1472d took c4-01-bash-test at 00:06:35, the restart came at 00:06:38;
  the same at 22:56:57 (e3-04), 23:16:49 (c4-01-bash-test) and 23:39:32 (e3-04). Every restart of the night said
  `no runner job under way`: `vms list` gave busy false while the clone ran. Doctor: `watchdog-kill` (case 7).
  Case 6 (the 422 crash-loop) follows each kill, and GitHub fails the killed job 10 minutes after it began
  (lost communication; 117253195199 at 00:16:36).
- **Cause**: the watchdog judged the start by `vms list` alone (`busy`: the row's `job`, `running`: its state); a
  VM runner GitHub listed online and busy did not count, so a lagging `vms list` made it restart a runner in the
  middle of its job. Why `vms list` lagged is not proven: its snapshot is the last poll's rows (the subscription's
  poll is not awaited, `code/rust/libs/hal2-vm-node/src/streams.rs`), and `tart list`'s JSON is read with
  `unwrap_or_default` (`code/rust/libs/hal2-vm/src/tart.rs`), so a failed read lists no clone.
- **Fix**: hal2 plan 0349 (`fix(ci-supervisor): never restart a VM runner GitHub lists busy`): `VmSeen.working` (VM
  runners GitHub lists online and busy) makes the start ready; an online VM runner counts as a start under way
  (`wake_grace`, not `start_grace`).
- **Tests**: `hal2-ci-supervisor::it supervisor_vm_incident::a_vm_runner_github_lists_busy_is_never_restarted`
  (fails before the fix: off, on four times).
- **Would have caught it sooner**: the doctor's `watchdog-kill`; a restart whose task log already says `Running job`.
- **Left**: a start that GitHub does not list yet and `vms list` misses can still be restarted after `start_grace`;
  make `vms list` answer from a fresh poll.

## 2026-10-16 22:56 - 2026-10-17 00:16 · GitHub held the VM's fixed runner busy with a dead job: every start failed (land run 38984579934)

- **Signature**: job c4-01-bash-test (117253195199) in `[03] checkout` with no runner; GitHub lists
  `arm64_loc_..._vm_a` offline and busy; `tart list` shows no VM running; the daemon log says `vm: runner
  hal2/ci-runner-macos instance 1 starts`, then `its job failed (exit None)`, every 30-120 s; each task log has only
  `registering arm64_loc_..._vm_a on divramod/hal2` and `gh: Bad request - Runner ..._vm_a is currently running a
  job and cannot be deleted. (HTTP 422)` (49 such task logs, the first at 22:56:09, the doctor found it from there). Doctor: `held-runner` (case 6); after the fix
  `stand-in` (a task log with `still holds a job on GitHub`).
- **Cause**: the clone died mid-job; GitHub kept the fixed-name runner busy with that job. Each round's
  `drop_leftover` tried to remove it first (GitHub refuses a name twice), got the 422 and failed the round before
  `register`, so the runner crash-looped on backoff and no VM job could start until GitHub gave the dead job up.
- **Fix**: hal2 plan 0349 (`fix(vm): a fixed runner name GitHub still holds registers a
  stand-in`): `drop_leftover` reports a runner held by a job (422 "running a job") instead of failing, and the round
  registers `<fixed>_<job id's last 8>` with the same labels; the held one is retried every round, and the fixed
  name returns once GitHub lets it go. Force-cancelling the stale job was rejected: it cancels the whole run (here
  a landing).
- **Tests**: `hal2-vm::it runner::a_fixed_name_github_still_holds_with_a_dead_job_registers_a_stand_in` (fails
  before the fix with the incident's 422); unit tests `a_leftover_of_a_fixed_name_is_removed_before_it_registers_again`,
  `a_stand_in_name_keeps_the_fixed_one_and_64_characters`. The fake gh now refuses a duplicate name (409) and
  speaks GitHub's 422 wording.
- **Unstick**: the job held by the dead runner never runs; rerun the failed job after its run ends. The installed
  `hal2-daemon` has the fix only after the landing's install.
- **Would have caught it sooner**: the doctor's `held-runner`; the supervisor's watchdog restarts could not help
  (each restart hits the same 422). The clone did not die by itself: the watchdog's restart killed it (case 7).

## 2026-10-16 05:55-06:05 · gh unauthenticated: the registration failed with HTTP 401 (land run 38856671199)

- **Signature**: task log 01a14347: `registering arm64_loc_..._vm_a on divramod/hal2` then `/opt/homebrew/bin/gh
  exited with code 1: gh: Requires authentication (HTTP 401)`; the daemon log has the same 401 (and `gh: Not Found
  (HTTP 404)` on the jobs list) about 100 times a day, by day and night, in hal2_vm_node::lazy, hal2_ci_supervisor
  and hal2_node_exporter. Doctor: `gh-auth` (any `HTTP 401`, `Requires authentication` or `Not Found (HTTP 404)`
  line of the window, or a task log with one).
- **Cause**: gh reads its token from the macOS keychain with a short timeout; when the read is slow or the keychain
  is locked, gh calls GitHub anonymously: 401 on runners, 404 on a private repository's jobs.
- **Fix**: hal2 plan 0349 step 42: the daemon's gh calls get `GH_TOKEN` from `~/.config/hal2/gh-token` (mode 0600,
  written once by the user: `gh auth token > ~/.config/hal2/gh-token && chmod 600 ~/.config/hal2/gh-token`), else a
  `gh auth token` read once and kept in memory (hal2_core's GitHub token).
- **Tests**: step 42's token tests in hal2_core and the daemon's gh callers.
- **Would have caught it sooner**: a doctor round; the supervisor's `could not look: ... HTTP 401` warnings were in
  the log all night.

## 2026-10-16 05:56-06:03 · a start hung before `tart run`, and `on` started nothing (same incident)

- **Signature**: the retry, task 01a14348 (started 05:56:28): `clone: 1.5s`, `copy in: 0.0s`, `$ tart run
  --no-graphics <clone>`, then `boot: 402.4s` with no `booted in`, ended by the off at 06:02:55 (`$ tart delete`,
  `removing ...`). Meanwhile `vms list` showed `stopped` with `runner_enabled: true`; a further `vms runner ... on`
  started nothing; only off then on recovered it. Doctor: `slow-boot` (a task log with `boot: N s` > 300 and no
  `booted in`); `dead-start` (a task log whose last line is `copy in: ...` or `$ tart run ...`, older than 5 min,
  the VM not running); `watchdog-restart` (`mac vm runner restarted`: the watchdog acted) and `watchdog-gave-up`
  (`mac vm: start still not online`).
- **Cause**: the boot resolves the definition's `${SECRET:...}` env through hal2-secrets and gpg, whose passphrase
  pinentry-mac keeps in the keychain: at night it waits. Nothing bounded the wait, and nothing noticed a queued VM
  job whose start never came online; `on` while on is a no-op.
- **Fix**: hal2 plan 0349 step 42: secrets resolved within 60 s, the last good resolution kept in memory and reused;
  the supervisor's watchdog: a queued VM job without a VM job or clone starting within `start_grace` (30 s), or a
  start not online on GitHub within `wake_grace` (300 s), is torn down and started again (off, on), at most
  `max_restarts` (3) per stuck stretch, then said once as a warning.
- **Tests**: step 42's watchdog incident tests (hal2-ci-supervisor, paused clock, `FakeVm`), the secrets bound in
  hal2-vm (fake tart, a secrets source that never answers).
- **Recovered**: by hand, `hal2-daemon vms runner hal2/ci-runner-macos off`, then `... on`.

## 2026-10-16 ~02:00 · the Mac slept and the VM's jobs died

- **Signature**: pmset `Sleep` (idle sleep after 1 min) while VM jobs were queued between runner jobs, no
  caffeinate assertion of the daemon; the jobs 02-mac-vm-a/02-tmux-test-mac (`c4-02-tmux-test-mac` since plan 0349
  D101) ended after "gate green", 01-bash-test was cancelled without a log. Doctor: `slept` (a pmset `Sleep` between a runner task log's start
  and its last write; approximate: a sleep between two runner jobs of one lane is not seen).
- **Cause**: nothing held a power assertion while the VM had work.
- **Fix**: hal2 plan 0349 step 42: the CI supervisor holds `caffeinate -i -s -w <daemon pid>` (macOS module) while a
  VM job is queued, running, or its run holds the VM; daemon log `ci supervisor: mac kept awake` / `ci supervisor:
  mac may sleep again`.
- **Tests**: step 42's keep-awake tests (hal2-ci-supervisor, a fake power port).

## 2026-10-16 05:55-06:04 · the VM parked or booted between a lane's jobs

- **Signature**: 05:55 bash-test done, tmux-test-mac waited until 06:04; a supervisor line `mac vm runner off
  (park)` followed within 10 minutes by `mac vm runner on (wake)`. Doctor: `park-wake` (daemon log and journal,
  one finding per pair).
- **Cause**: the dead start of the case above, plus a park that did not count every run's queued jobs.
- **Fix**: hal2 plan 0349 step 42: parked only when a fresh look right before the park shows no job of any run for
  the VM.
- **Tests**: step 42's park tests in hal2-ci-supervisor.

## 2026-10-15 · the lane parked between its chained jobs; job 03 waited 25 min (plan 0349 step 34, run 38794764310)

- **Signature**: lane 04-mac-vm-a (`e3-mac-vm-a` since D101) parked between its jobs 02 and 03 (`needs`-chained:
  GitHub lists 03 only once it is queued); after a daemon restart the runner stayed off and job 03 waited 25 minutes. Doctor: `labels` (`mac
  vm: jobs wait for labels the VM's config (mac_vm.labels) lacks`) for the label half.
- **Cause**: a short idle between two of one run's VM jobs counted as the end; `mac_vm.labels` lacked `mac-vm-a`,
  so the jobs did not count as the VM's.
- **Fix**: `hold_for_run` (an unfinished run that had a VM job holds the VM up to 30 min) and the label check
  (`mac_vm.labels` must carry mac-vm-a).
- **Tests**: `code/rust/libs/hal2-ci-supervisor/tests/it/supervisor_vm_incident.rs`.
