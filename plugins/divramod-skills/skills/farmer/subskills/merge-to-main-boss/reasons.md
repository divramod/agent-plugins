# Why a merge to main does not happen

The boss's case library. There is one case per cause, newest first. A recurrence adds a line under its case's
**Occurrences**. **Remedy** is what the boss does now. **Lasting fix** is the change in hal2 or a skill that stops
it for good: `none`, `shot <shotfile>/<n>`, `plan <NNNN>` or `landed <plan> <date>`.

The first eight cases come from the survey of 2026-10-03 07:30. Nothing had landed on hal2 main since 16:31 the day
before, while 5 landings were ready and waiting.

## Landings through CI (hal2 plan 0131)

Where the default branch has `.github/workflows/land.yml`, a landing is a candidate on `land/<slot>` that
GitHub Actions tests on hal2's own runners and fast-forwards on green ([mtm's CI page](../../../mtm/references/ci.md)).
Nothing holds the queue on red and nothing runs on the Mac, so the local cases change:

- **Gone**: R1 (a red candidate releases the queue at once; its session fixes and lands again), R2 and R3 (the
  gates run on fixed-resource runners, not under the Mac's load), R4 (`merge-to-main --max-wait` keeps its place),
  R10 and R11 locally (a job's `timeout-minutes` ends it on GitHub), R12 (`ship.yml` installs after the landing).
- **Stay**: R6, R7, R8, R9 (a real failure is now a red job: its session reads `gh run view --log-failed` and
  reproduces it with `gate/main.sh <job>`).
- **New**, the C cases below. A red job's cause in the runner, its image or the workflow is the ci duty's (one fix
  for every slot, through a servant), never the slot's.

## C8 · A delivery cannot read the new main's job map

- **Signature**: `ship / deliver` red at its first command after a green merge: `hal2-cli-git: .github/hal2-changes.toml:
  TOML parse error ... unknown field`; nothing is installed on the Mac (binaries older than the merge).
- **Occurrences**:
  - 2026-10-06 19:21 · 05's M2 (run 37499420063, main 14749e4b): the landing added `package_keys`; the Mac's
    hal2-cli-git 0.5.3 did not know it. T1 (35) would have hit it again with M1's `frozen`.
- **Cause**: deliver asks the *installed* `hal2-cli-git changes` what to install; a landing that adds a key to the
  map needs the new hal2-cli-git to read the file that tells deliver to install the new hal2-cli-git.
- **Remedy**: the lander installs hal2-cli-git once from the new main (`cargo install --path
  code/rust/apps/hal2-cli-git --locked`), then reruns only the red job (GitHub refuses a job rerun while the run is
  in progress: wait for its other ship jobs). It keeps the queue's successor waiting until the run has ended.
- **Lasting fix**: landing with T1 (86f3534d, plan 0158): deliver installs this main's hal2-cli-git first and asks
  it again; the gate's `choose_cli` twin on 05 (100e689c, plan 0152).

## C7 · The runner's job cleanup kills the shared sccache server

- **Signature**: a Rust-compiling job red after seconds with `sccache: error: failed to execute compile ... Failed to
  read response header / Connection reset by peer (os error 104)` or `server looks like it shut down unexpectedly`,
  at the second another job on another runner instance ended ("Cleaning up orphan processes / Terminate orphan
  process: pid (...) (sccache)").
- **Occurrences**:
  - 2026-10-06 19:43 · T1 (35), run 37505425769: `linux / protobuf` (hal2-ci-runner) died 20 ms after `bash-lint`
    (hal2-ci-runner-b) ended. First run on M2's image (third instance; bash-lint now builds hal2-cli-git).
- **Cause**: the one sccache server is spawned by whichever job compiles first, carries that job's
  `RUNNER_TRACKING_ID` and is killed by that runner instance's orphan cleanup when the job ends, while other
  instances compile through it.
- **Remedy**: no code change in the slot: rerun only the red job(s) when the run has ended (`gh run rerun <id>
  --failed`). Until the fix lands every wake of the runner has the race again.
- **Lasting fix**: plan 0152's next landing (05): the server as its own systemd unit before the runner instances,
  the wrapper unsets `RUNNER_TRACKING_ID` and retries a failed `sccache: error` compile with plain rustc.

## C6 · A candidate is pushed while another land run still ships

- **Signature**: two `land` runs at once on GitHub: one past `merge` with `ship / ...` jobs running or queued, a newer
  one of another slot started; the older landing released the queue at its merge.
- **Occurrences**:
  - 2026-10-06 13:0x · 30's run #69 pushed while 04's run #68 (37444838079, attempt 2) shipped: deliver running,
    publish queued. The user: the 4th or 5th time today.
- **Cause**: hal2-git `ci/gh.rs` `runs_in_progress()` lists land runs with `status=in_progress` only; a run whose
  ship job waits for a runner has status `queued` (also `waiting`, `pending`, `requested`), so `ci/ship.rs`
  `shipping()` saw no shipping run: the landing released the queue and the next one pushed.
- **Remedy**: stop the newer landing (`hal2-cli-git worktree stop <slot>`), cancel its run, "land now" once the older
  run is completed. Check by hand: `gh run list --workflow land.yml --limit 10 --json databaseId,headBranch,status
  --jq '.[] | select(.status != "completed")'` (empty: go).
- **Lasting fix**: landed: hal2 plan 0150 (cf97733d, on main with 9fda0676 #23; installed by that run's deliver
  2026-10-06 15:10, `hal2-cli-git` asks every non-completed status); mtm skill documents the check (skills plan
  0013, skills/30-1).

## C5 · The Linux runner's CI volume is full

- **Signature**: several Linux jobs of one run red with "No space left on device"; `/mnt/ci` at 100%, the Cargo
  targets (`target`, `target-b`) tens of GB.
- **Occurrences**:
  - 2026-10-06 11:5x · 04's cleanup train, run 37444838079: bundle-linux, rust-test, hub-e2e, web-e2e. The job-start
    hook's trim was a no-op: `/usr/local/lib/hal2-ci/rust-target-trim/main.py` is missing from the runner's base
    image (it predates the trim).
- **Remedy**: run the repo's `code/python/scripts/rust-target-trim` on the runner as `ci` with the hook's settings
  (20 GB, 70%) while no Linux job runs, then relaunch the landing (04 did, volume 54%).
- **Lasting fix**: landed: hal2 plan 0150 (9fda0676 #23, 20cddf34 #24, 0127104f #25; 2026-10-06 15:3x): ci-disk on
  the volume (`/mnt/ci/lib/current`, synced by every push's `changes`), loud job-start hooks, `hal2-ci-disk.timer`,
  a pre-flight in the heavy jobs, the image key compared with main's (stale → rebuild). Live check: image 440285575
  (key be59ef88ccbd, built from the Mac: the old installed builder still failed once, user data over 32 KiB),
  `/mnt/ci` 53%. Shot hal2 ci #2. The image WAS rebuilt at 05:51 (run 37420645579) but by the previously installed
  image builder, which did not pack the trim yet (one-image lag, fixed by 0150 step 5).

## C4 · A green candidate is not fast-forwarded

- **Signature**: the `land` run is green but its `merge` job is skipped; the default branch stays; the lander takes
  it for "main moved" and retests.
- **Occurrences**:
  - 2026-10-05 06:07Z · probe 3 (`land/12-probe`): `if:` without a status function, so the implicit `success()`
    skipped `merge` because the skipped stack and macOS lanes sat before the gate.
- **Remedy**: the workflow's fix lands first; the waiting candidates retest by themselves.
- **Lasting fix**: landed with plan 0131 (`merge` checks `needs.<job>.result` with `!cancelled()`).

## C3 · A tool on the runner differs from the Macs'

- **Signature**: a lint job red on the runner only, the same command clean on the Mac ("workspace-hack is stale").
- **Occurrences**:
  - 2026-10-05 05:44Z · probe 2: cargo-hakari 0.9.39 on the runner, 0.9.37 on the Macs.
- **Remedy**: pin the tool's version in the gate script and the runner's image (one value), rebuild the image.
- **Lasting fix**: landed with plan 0131 (`HAKARI_VERSION` in `gate/jobs-linux.sh`).

## C2 · The runner's image lacks a tool or component

- **Signature**: a job red at once with "not installed" / "command not found" (rustfmt, python, a browser).
- **Occurrences**:
  - 2026-10-05 · probe 1: no rustfmt/clippy (rustup's minimal profile on the volume).
  - 2026-10-05 05:17Z · `re-actors/alls-green` needs `python` (`python-is-python3` added to the cloud-init).
- **Remedy**: the gate script installs what is missing when it can; the image's cloud-init gets it for good.
- **Lasting fix**: landed with plan 0131 (image rebuilt by main's `runner-image` job when its inputs change).

## C1 · Jobs wait for a parked runner

- **Signature**: a `land` run's jobs queued for minutes, the Linux runner offline (parked), no wake in the
  receiver's log.
- **Occurrences**:
  - 2026-10-05 · hal9k was deployed from a branch without `hal2-ci-wake`; the farmer's 5-min fallback woke it.
  - 2026-10-05 ~06:00Z · after the redeploy Caddy kept its old Caddyfile (GitHub's webhook got 502).
- **Remedy**: the ci duty's wake fallback (`ci-wake/main.sh`); check `hal9k-hal2-ci-wake-1` and Caddy's route.
- **Lasting fix**: hal9k's deploy restarts what changed even after a failed deploy (plan 0131, `36f33b2d`).

## R12 · A delivery step fails because a script was committed without +x

- **Signature**: an install or deliver task exits 126 after the merge into main; the old binary stays installed and
  the queue stays held.
- **Occurrences**:
  - 2026-10-04 hal2 wt 19 (plan 0124): package-macos/main.sh and build-linux/main.sh, both from plan 0108.
- **Remedy**: the holder runs `chmod +x` on the script, commits and reruns /mtm to land the fix and deliver again.
- **Lasting fix**: none yet. A gate checking that `code/*/scripts/*/main.*` is executable would catch it; file a
  shot on a second occurrence.

## R11 · A landing task hangs past its timeout

- **Signature**: a task's log stops (xcodebuild "failed with exit code 0 but produced no further output", then
  nothing) and it runs past its `.hal/hooks.toml` timeout; the landing ends only when something kills it.
- **Cause**: hal2-hooks' timeout does not kill a hung task (child processes or no output); unverified.
- **Occurrences**:
  - 2026-10-03 12:37 · wt 15 · libs.Hal2Kit.test-unit (iOS part), timeout 45m, killed by the shell limit at ~2 h
- **Remedy**: tell the holder to stop the landing (`hal2-cli-git worktree stop`) and rerun detached.
- **Lasting fix**: shot skill-mtm/7.

## R10 · The Docker engine stops starting containers mid-landing

- **Signature**: a `test-e2e` task sits at `Container ... Starting` with no output for minutes;
  `hal2-cli-docker-compose doctor --json` says `stuck` ("a container of <image> did not start within 20s"), while
  `docker ps` still answers and running containers stay up.
- **Cause**: Docker Desktop's engine wedges under load (research in docs/docker.md); the gate's `doctor --repair`
  ran before the task, so the landing does not notice until the task's timeout (15m).
- **Occurrences**:
  - 2026-10-03 11:09 · wt 15 (train B) · libs.hal2-n8n.test-e2e, n8n-postgres "Starting" since 10:59
  - 2026-10-03 11:24 · wt 15 rerun · n8n-n8n "Starting" since 11:14 (the gate's probe had passed); farmer ran `doctor --repair` → ready
- **Remedy**: tell the holder it is the engine, not its code; let the task time out (or stop it), then rerun at
  once: the gates' `doctor --repair` restarts the engine. Never disable the test for it.
- **Lasting fix**: shot plugin-docker-compose/4 (a test-e2e probes the engine when no container starts and repairs
  once or fails fast). Waits for a free servant slot.

## R1 · A failed landing holds the queue while its agent sleeps

- **Signature**: `scan.py` finding `held-idle`. The queue head is `held`, reason `failed`, with no live landing
  process, and its agent is `sleeping` or `done`.
- **Cause**: the plan's landing rule says "notify and stop with the queue held" after repeated failures. Overnight
  nobody answers the notification, so the queue stays dead for hours. In this case wt 12 stopped at 02:40 after 7
  attempts and the queue stood still until 07:45.
- **Occurrences**:
  - 2026-10-03, hal2 wt 12 (plan 0114), 5 h dead. The failure was a load-sensitive timing test that was also red
    on main alone.
- **Remedy**: wake the holder by SendMessage. A test that fails on main too, or only under load, gets disabled
  (R2) and the holder reruns its landing. If the holder does not move within one round: `hal2-cli-git worktree
  release <slot>` frees the queue, and the holder requeues after its fix.
- **Lasting fix**: none. The idea is that the plan skill's landing rule asks the boss before it stops, not the
  sleeping user.

## R2 · Timing and latency-budget tests fail under load

- **Signature**: `flaky-candidate`. The message contains budget, watchdog, `< limit`, "busy machine", Elapsed or a
  timeout, the load per core is ≥ 2, and the test passes alone.
- **Known tests (hal2)**:
  - Hal2Kit: ConversationStressTests.everyPlaceAtOnceStaysResponsive (53 ms vs 50 ms; fails 2/3 on main at load
    5), ConversationAccessibilityTests.theGridReadWhileItGrowsIsCheap and theGridOfSixRealSizeAgentsIsCheap,
    WebHostTests.servesThePageAndRoundTripsMessagesAndCalls (10 s page load at load 160–190), iOS WebCanvasTests.
  - Rust: hal2-daemon budgets the_daemon_answers_within_its_budgets, git_budgets, hal2-hub-authz
    a_decision_takes_under_a_millisecond.
  - UI tests: AgentsNodesUITests waitForNode, GitNodesUITests.
- **Occurrences**:
  - 2026-10-01/02/03 in wt 01, 08, 09, 12, 13 and 14, many times.
  - 2026-10-04 wt 19: WebHostTests.servesThePage… (iOS), load 115, passed on retry; wt 01: WebHostTests.downloadsLandInATemporaryFileForTheHost (iOS), load ~117, disabled.
- **Remedy**: the user's rule of 2026-10-03 is to disable it rather than retry. Mark it
  `.disabled("flaky under landing load <date>, merge-to-main-boss")` in Swift, or `#[ignore = "..."]` in Rust, in
  the branch that is landing (or directly in main), add an entry to the ledger `~/skills/merge-to-main-boss/<repo>/flaky.md`,
  and file one shot to make it load-proof and enable it again.
- **Lasting fix**: none. The idea is budgets scaled by load (the `testing::budgets` median idea, extended to
  Swift).

## R3 · The machine is overloaded while a landing runs

- **Signature**: `load-high`, with load 75–500 on 10 cores during a landing.
- **Cause**: other worktrees build, run `build.sh check`, run Docker cross-builds or resume benchmarks beside the
  landing's gates. That causes R2.
- **Occurrences**:
  - 2026-10-02 16:41 (wt 08, caused by wt 00's build and wt 10's Linux Docker build).
  - 2026-10-02 23:39–01:02 (wt 12, after the benchmark resume).
- **Remedy**: tell the busy slots to pause heavy work (the `pause` skill) until the landing ends, then let them
  continue.
- **Lasting fix**: none. The idea is a landing lock that every build script honours.

## R4 · Waiters lose their place: `reserve --max-wait 100m` outlives the shell's 2 h limit

- **Signature**: the same slot is re-enqueued with a new seq, and its agent reports "reserve killed by the 2 h
  limit".
- **Cause**: while the queue is held, `reserve --max-wait 100m` sometimes did not exit at 100 min. The harness
  killed it at 2 h and the ticket was gone. 60-minute slices exit on time. This may be a hal2-cli-git bug: the
  time limit is not checked while the held head is being settled or taken over.
- **Occurrences**:
  - 2026-10-03 wt 01, 02 (twice), 09, 10 and 15.
  - 2026-10-03 ~12:40 · wt 12's reserve lost its ticket; wt 01's merge-to-main waited 1h48m and was killed; wt 15's whole landing killed at ~2 h (queue held `interrupted`).
  - 2026-10-04 ~01:30 · wt 01 and 10 (re-enqueued as seq 413/414): `reserve` returned "reserved" (queue_position 11) yet 01 dropped out and 21 got the turn; a new symptom of the same family. The boss's `front` at 00:42 may have been the trigger. Restored with `front 10 01`.
  - 2026-10-04 01:25–03:54 · wt 06: reserve said reserved; after merge-from-main + push, merge-to-main --keep-reserved waited "8 landing(s) ahead" until the 2 h limit. Fix delegated to a servant (slot 21).
- **Likely trigger**: the boss's own `front` reorder restarts a waiter's running --max-wait slice (wt 01 saw it twice). Move a slot at most once per slice; prefer 25m slices.
- **Remedy**: tell waiters to use `--max-wait 25m` slices and to run landings detached (nohup); move carriers forward with `front` sparingly.
- **Lasting fix**: shot skill-mtm/6.

## R5 · Docker images are gone in the middle of a landing

- **Signature**: test-e2e fails while downloading images, or with a proxy timeout.
- **Cause**: another session ran `docker system prune -a`.
- **Occurrences**:
  - 2026-10-02 16:38, wt 08.
- **Remedy**: re-pull the images before rerunning. Ask sessions never to prune while a landing is active.
- **Lasting fix**: none.

## R6 · Finished work waits for the user, not the queue

- **Signature**: `work-not-queued`. The plan is at its last steps and the agent asked the user something.
- **Causes**:
  - UI tests need a free or unlocked Mac (wt 04, 05, 06, 14).
  - A product decision is open (wt 00: GitHub access for the launchd daemon; wt 07: the research decision).
  - An ordering rule ("04 waits for 0091 step 10").
  - The user said "stop merging" earlier (wt 08 waits for the user's own /mtm).
- **Remedy**: one batched push notification, or one question block when the user is present, with every open
  decision listed together. The boss never decides product questions. With the user's general "merge fast" rule
  it may tell a plan to land without UI tests that only failed for unrelated reasons, and run those tests after
  the landing.
- **Lasting fix**: none.

## R7 · Work without any agent session

- **Signature**: `work-without-agent`. A worktree has commits not on main and no agent.
- **Occurrences**:
  - 2026-10-03: wt 11 (plan 0085, 13 commits) and wt 13 (plan 0102, 7 commits; its last landing failed
    2026-10-02 03:54).
- **Remedy**: start a session in the slot (`hal2-cli-git worktree run <NN> --agent claude --detach --prompt
  "/handoff c"`), or ask the user when the plan looks abandoned.

## R8 · A system-wide stop paused a landing

- **Signature**: the landing's agent says it was paused by stop-all-agent-work, and the queue was released.
- **Remedy**: after continue-all-agent-work, landings that were aborted start again first.

## R9 · Real failures

These are not flaky:

- the linker's `__eh_frame section too large`;
- merge conflicts;
- a delivery's `hal2-macos install` exit 65;
- a usage error in a new app's test-unit.

The holder fixes these. The boss may fix them directly in main when several landings share the failure (see SKILL.md).
