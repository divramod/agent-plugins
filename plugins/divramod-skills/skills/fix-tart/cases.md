# fix-tart cases

Newest first. One case per root cause; a recurrence adds a line under its case. The **signature** is what
`evidence.py show` prints that identifies the case; the doctor's (`scripts/signatures.py`) is named with its slug.
Times are UTC.

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
