---
name: fix-tart
description: Analyze and fix a failure of hal2's Mac VM runner (the Tart VM `hal2/ci-runner-macos` that hal2-daemon starts per GitHub job and the CI supervisor wakes and parks) — a VM job that waits for good, a start that hangs before `tart run`, a registration that fails with `HTTP 401`, a park between a lane's jobs, a Mac that slept mid-job. Collects the evidence (the VM's `vms list` row, `tart list`, the runner task logs, the daemon log's hal2_vm_node and hal2_ci_supervisor lines, the supervisor journal, pmset's sleeps, the queued GitHub jobs), matches it against known cases, finds the root cause in hal2's code, fixes it with a regression test replaying the incident, gets the stuck job going again (after asking) and records the case so the skill learns. `/fix-tart doctor` looks for VM incidents of the last hours nobody reported; `/fix-tart selfcheck` checks this skill's insider knowledge against the code. Use when the user says /fix-tart, "the Mac VM job waits / is stuck / never started", "mac-vm-a queued forever", "the VM runner does not come up" or "tart hangs". `/fix-tart h` shows help.
---

# fix-tart

The user names the incident (a few words, a run id, a job name; screenshots optional), or a doctor round found it.
You find why the Mac VM runner did not take its job, fix it in hal2 and make the case known to this skill.
`S=<skill-dir>/scripts`, `E="python3 $S/evidence.py"`. Ask questions by the global question rule (background
first; ~/.claude/CLAUDE.md), recommended option first. Never start or stop a VM, tart or the daemon yourself,
except the off/on of section 5 after the user's yes; read-only commands are fine.

| Call | Does |
|---|---|
| `/fix-tart [<description>]` | analyze one incident (`--hours N` for an older one) and fix it |
| `/fix-tart doctor [<hours>]` | list the known cases of the last hours (default 2) nobody reported, offer to analyze each |
| `/fix-tart selfcheck` | check the insider knowledge below against hal2's code; fix the drift |
| `/fix-tart h`, `/fix-tart help` | print this table and stop |

## 1. Collect the evidence

1. `$E show [--hours 2]` prints the VM's `hal2-daemon vms list --json` row (`state`, `runner_enabled`, `job`,
   `problem`), `tart list`, the last runner task logs (start from the UUIDv7 task id, last write from the mtime),
   the daemon log's hal2_vm, hal2_vm_node and hal2_ci_supervisor lines of the window (and how many gh 401/404 lines
   the whole log has), the supervisor journal, pmset's sleeps and wakes (UTC), the unfinished GitHub jobs wanting the
   VM's labels (skipped with a note when gh fails: that itself points to case 1) and the doctor's findings. A missing
   hal2-daemon exits 2: run `bash $S/install-prerequisites.sh`.
2. Build the **timeline** in UTC (the daemon log and journal are UTC, pmset prints local time, the task logs have no
   times: start and last write): job queued → wake (`mac vm runner on (wake)`) → task log `registering` → `slot`
   → `clone` → `copy in` → `$ tart run` → `booted in` → runner.sh `Listening for Jobs` → `Running job` → `command:`
   → `delete:` → `removing` → park. The failure is the first step that did not follow within its bound.
3. `$E doctor --hours 24` shows whether the same thing happened before.
4. `$E waits [--runs 5] [--check]` prints how long each VM job of the last land runs waited for its runner (GitHub's
   start minus the later of its creation and the end of the VM job before it in the run; `--check` exits 1 when one
   waited 15 s or more, plan 0391 step 11's bound).

## 2. Match known cases first

Read [cases.md](cases.md): each case has a **signature** (task log lines, daemon lines, the `vms list` state, pmset
entries). A matching signature points to the cause and the code; check it still applies (the fix may have
regressed, or it is a new variant). No match: a new case.

## 3. Find the root cause

Work in a hal2 worktree (never the main checkout; `/mfm` first). The code is listed under **Insider knowledge**.
Distinguish:

- **hal2 bug** (the runner loop, the job's phases, the supervisor's wake/park/watchdog decision): fix the code;
- **environment** (gh's token from the keychain, gpg's pinentry, the Mac's sleep, an old installed `hal2-daemon`):
  make hal2 independent of it (a token file, a bound with a cached value, a power assertion), never a manual step
  that has to be repeated;
- **GitHub** (a job whose labels the VM lacks, a runner GitHub still lists): fix the config or the label check.

## 4. Fix and verify

1. Regression test **from the incident**: `$E capture --out <scratch>/incident` saves every source as files (its
   README.md names each). A supervisor decision is replayed on tokio's paused clock with the fakes of
   `code/rust/libs/hal2-ci-supervisor/tests/it/fakes.rs` (`FakeGithub`, `FakeVm`; the incidents so far in
   `code/rust/libs/hal2-ci-supervisor/tests/it/supervisor_vm_incident.rs`); a job phase with hal2-vm's fake tart
   (`code/rust/libs/hal2-vm/src/testing.rs`, the crate's `testing` feature). Name the incident (date, run id) in
   a comment. It fails before the fix.
2. Fix, then from `code/rust/`: `cargo fmt --all`, `cargo nextest run -p <crate>`, `cargo clippy -p <crate>
   --all-targets` for each changed crate (hal2-vm, hal2-vm-node, hal2-ci-supervisor, hal2-daemon).
3. Commit in the worktree (`fix(<NNNN>|<step>): ...` in a plan, else `fix(vm): ...` or `fix(ci-supervisor): ...`, saying the incident and the cause). Landing
   is the user's (`/mtm`); the installed `hal2-daemon` runs the fix only after the landing's install.

## 5. Get the stuck job going

Ask first (it tears down a running clone): `hal2-daemon vms runner hal2/ci-runner-macos off`, then `hal2-daemon
vms runner hal2/ci-runner-macos on` (the off/on that recovered the 2026-10-16 incident; `on` while on is a no-op,
only off then on starts a fresh supervise loop). The supervisor's watchdog does this on its own (see below): check
the daemon log for `mac vm runner restarted` first, and do not race it. Then watch the newest task log until
`Listening for Jobs` and the job's `Running job`.

## 6. Learn

1. Append the case to [cases.md](cases.md) (newest first): date and UTC times, run id, **signature**, cause, fix
   commit, the regression test's name, and what would have caught it sooner.
2. **Update this skill** whenever the analysis showed something it did not know: the insider knowledge (a file, a
   log line, a bound, a config key), a step that was missing, or the scripts (a new signature in
   `scripts/signatures.py` with its test in `scripts/test_evidence.py`; a new source in `scripts/sources.py`).
   Keep the `<!-- strings -->` and `<!-- keys -->` blocks to literal text of hal2's code. Run `$E selfcheck`: it
   must print `ok`. Change the skill with the case in a hal2 worktree and land it with the worktree's `/mtm`.
3. A failure **class** that keeps coming back gets a hal2 plan that removes the class, not another patch.

## 7. Report

The timeline in a few lines (UTC), the root cause, the fix (commit, test), the job's state now, the case added and
what changed in this skill.

## Insider knowledge

As of hal2 plan 0349 (steps 34, 40, 42) and plan 0391 step 11. Keep this true: `$E selfcheck`.

**The VM runner's flow** (hal2-daemon, one node). `hal2-daemon vms runner <vm> on` saves the switch and starts
`supervise` per instance (`code/rust/libs/hal2-vm-node/src/runner.rs`; instance 1+ waits until the instances below
have jobs, `code/rust/libs/hal2-vm-node/src/lazy.rs`; leftover clones are adopted or retired by
`code/rust/libs/hal2-vm-node/src/orphans.rs`). Each round runs one job, `run_runner_job`
(`code/rust/libs/hal2-vm/src/runner.rs`): `drop_leftover` (a runner of that name GitHub still lists; one GitHub
refuses to remove because it still runs a dead clone's job, `HTTP 422`, stays, and the round registers a stand-in
`<name>_<job id's last 8>` with the same labels: `<name> still holds a job on GitHub: registering ... instead`), `register`
(`gh api .../generate-jitconfig`, task log `registering <name> on divramod/hal2`), then `run_job`
(`code/rust/libs/hal2-vm/src/job.rs`), each phase timed in the task log as `<phase>: <s>s`: `slot`, `clone`
(`$ tart clone <image> <clone>`, `code/rust/libs/hal2-vm/src/tart.rs`), `copy in`, `boot`
(`code/rust/libs/hal2-vm/src/host.rs`: the definition's env with every `${SECRET:NAME}` resolved through
hal2-secrets, `code/rust/libs/hal2-vm/src/env.rs`; `$ tart run --no-graphics <clone>`; waiting for the guest agent
up to `boot_timeout`, 300 s; `booted in <n>s`), host ports (`forwarding ...`), `command` (runner.sh detached in the
guest: `$ /bin/bash /Volumes/My Shared Files/definition/runner.sh`, the runner's own lines with UTC times
`Listening for Jobs`, `Running job: <lane>/<job>`), `delete` (`$ tart delete <clone>`), and the registration's
removal (`removing <name> from divramod/hal2`). Then the clone serves its run (plan 0391 step 11,
`code/rust/libs/hal2-vm/src/runner_session.rs`, `runner_queue.rs`, `job_again.rs`): a just-in-time runner takes one
job and GitHub hands a runner any queued job its labels fit, of any run, so the clone gets a new registration
(`run <id>'s next VM job waits: registering <name> again in this clone`, written into a new env file `env.<n>` the
restarted command sources, never the `env` the guest read: case 10; `job.json`'s `again`) only while GitHub lists that run's next VM job queued and no other run's, looked for 12 s; else `the clone
goes: <why>` and the next round clones afresh; a runner registered again without a job after 30 s: `<name> got no job
within 30s: stopped`; after a daemon restart such a runner is retired while idle, never followed. A clone per run's
back-to-back VM jobs (`mode = "ephemeral"` in `utils/vms/ci-runner-macos/vm.toml`, the guest script
`utils/vms/ci-runner-macos/runner.sh`, which runs again in its clone). After a failed round
`Backoff`: 30 s, doubling to 10 min. Task logs: `~/.local/state/hal2/tasks/<uuid7>.log`.

**The gh token.** Every gh call of the daemon (registration, `busy`, the supervisor's looks) used gh's keychain
token; a slow or locked keychain made gh call GitHub anonymously: `gh: Requires authentication (HTTP 401)` on
runners, `gh: Not Found (HTTP 404)` on the private repository's jobs. Since step 42 the daemon passes `GH_TOKEN`
from hal2-secrets' global `HAL2_DAEMON_GH_TOKEN_SEC` (plan 0349 D126; set once: `gh auth token | hal2-cli-secrets set
HAL2_DAEMON_GH_TOKEN_SEC --layer global`; no plain token file), else a `gh auth token` read once and kept in memory.

**The secrets.** The boot resolves `${SECRET:...}` through hal2-secrets and gpg. Since plan 0391 step 11 a
definition's `[env]` is resolved once per daemon and kept (`code/rust/libs/hal2-vm/src/env_kept.rs`; one look for all
its names, `env_secrets.rs`, `secrets.toml` read again when it changes): a boot says `env: kept from <n>s ago` and
waits for nothing; the files (each chain layer's `.secrets/`, `.gitsecret/` without gpg's `random_seed`,
`secrets.toml`) are stamped every 10 s and at each boot, a change is resolved again in the background (`resolved again
in the background`), a removed secret leaves the cache; the first resolution starts when the runner goes on; a boot
with nothing kept waits within 60 s, cancellable (`the secrets did not resolve within 60s ...: it goes on in the
background`). The 60 s waits of 2026-10-18/19 (case 8) were hal2-secrets listing every layer of 51 worktrees once per
name, nine names per boot, on a Mac at load 39-86, not gpg's passphrase (gpg answered in 0.5 s).

**The CI supervisor's mac_vm check** (hal2-daemon's role, `code/rust/apps/hal2-daemon/src/ci_supervisor.rs`;
`check_mac_vm` in `code/rust/libs/hal2-ci-supervisor/src/checks/mac_vm.rs`, every `[checks.mac_vm] interval` s): it reads
`vms list` (`code/rust/libs/hal2-ci-supervisor/src/system/vm.rs`), the unfinished runs' jobs and the runners
(gh api), and `VmBook` decides (`code/rust/libs/hal2-ci-supervisor/src/decide/vm.rs`): a job whose every label is
one of `mac_vm.labels` wants the VM → runner on (`mac vm runner on (wake), N jobs waiting`); on, jobs waiting, no
VM runner ready (online on GitHub and a VM running) → the watchdog below; no job for `park_after` s (`hold_for_run` while an unfinished run
had a VM job) → off (`mac vm runner off (park), 0 jobs waiting`), parked only when a fresh look right before the
park shows no job of any run for the VM. **The watchdog** (step 42, `VmBook` in
`code/rust/libs/hal2-ci-supervisor/src/decide/vm.rs`, acted on by `checks/mac_vm.rs`): a queued VM job without a VM job or clone starting
within `start_grace` (30 s), or a start not online on GitHub within `wake_grace` (300 s), is torn down and started
again (off, on; `mac vm runner restarted`; a VM runner GitHub lists online and busy is ready and never torn down, an
online one is a start under way: case 7), at most `max_restarts` (3) per stuck stretch, then said once as a
warning (`mac vm: start still not online`) and tried again after `restart_pause` (1800 s); a VM job that ended
since the last look ends a stretch (`VmSeen::last_done`, plan 0391 step 11: the restart 13 s into a new start). **Keep-awake** (step 42): while a VM job is queued, running, or its run
holds the VM, the supervisor holds `caffeinate -i -s -w <daemon pid>` (macOS), logged `ci supervisor: mac kept
awake` / `ci supervisor: mac may sleep again`. Labels unfinished jobs want beyond the VM's are said once (`mac vm:
jobs wait for labels the VM's config (mac_vm.labels) lacks: ...`). Every wake and park decision also goes to the
journal `<state root>/ci-supervisor/power.log` (`~/.local/state/hal2/ci-supervisor/power.log`, `<UTC> <line>`;
`code/rust/libs/hal2-ci-supervisor/src/journal.rs`), the events' wording in
`code/rust/libs/hal2-ci-supervisor/src/events.rs`.

**Config**: `~/.config/hal2/ci-supervisor.toml`, `[mac_vm]` (`code/rust/libs/hal2-ci-supervisor/src/config.rs`;
defaults: vm `hal2/ci-runner-macos`, labels self-hosted, macOS, ARM64, hal2, mac-vm-a, park_after 60, hold_for_run
1800, wake_grace 300, start_grace 30, max_restarts 3, restart_pause 1800; the check's interval 30):
<!-- keys -->
`vm`, `labels`, `park_after`, `hold_for_run`, `wake_grace`, `start_grace`, `max_restarts`, `restart_pause`
<!-- /keys -->

**Commands**: `hal2-daemon vms list --json` (the VM's `state`: `stopped`, `running`, ...; `runner_enabled`; `job`:
the clone's id), `hal2-daemon vms runner <vm> on|off`, `tart list`, `pmset -g log | grep -E ' (Sleep|Wake) '`,
`$E waits` (the VM jobs' waits on GitHub).

**Log strings** the evidence and the doctor read (selfcheck greps hal2's Rust sources for each):
<!-- strings -->
`registering `, `booted in `, `copy in`, `removing `, `generate-jitconfig`, `ci-supervisor/power.log`,
`mac vm runner `, `off (park)`, `on (wake)`, `(mac_vm.labels) lacks`, `mac vm runner restarted`,
`mac vm: start still not online`, `mac kept awake`, `mac may sleep again`, `HAL2_DAEMON_GH_TOKEN_SEC`,
`still holds a job on GitHub`, `the secrets did not resolve within`, `env: kept from`, `again in this clone`,
`the clone goes`, `got no job within`
<!-- /strings -->

**Traps**: `vms runner ... on` while it is on does nothing (a dead start stays dead until off, on); `vms list`
says `stopped` with the runner on both between jobs and in a dead start (the task log tells them apart); the daemon
log is UTC, `pmset -g log` local time; the 401 lines come from every gh caller of the daemon (node exporter too),
not only the VM's; an old installed `hal2-daemon` runs the old code (check its build time against the fix).
