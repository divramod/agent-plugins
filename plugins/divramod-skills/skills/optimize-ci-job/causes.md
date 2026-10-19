# optimize-ci-job causes

The learnings of plan 0365 (agents-test 9:20 to one parallel run, a local run 27 min to 172 s), one case per cause.
Newest first; a recurrence adds a line under its case. `M=<hal2 checkout>/code/python/scripts/ci-job/main.py`. The
**Symptom** is what `report`, `scan` or `spawns` prints (a smell's id is the one `scan` prints); the **Evidence** is
the command that proves it on the job at hand; a clue from `scan` is read before it is a finding. The rule for every
fix: no test dropped or weakened, no assertion changed (the fast-tests record and guide). **Seen**: plan 0365 unless
a line says otherwise.

## Method traps

### No per-test times

- **Symptom**: `report` prints `tests: no timed test lines`, or only `bats-stamp` rows of streamed blocks: the job's
  bats runs lack `--timing`, its unittest `--durations`; a parallel unit's buffered output is not timed at all.
- **Evidence**: `python3 $M rank <job>`: the test sources; the job's runner command in its gate job file.
- **Fix**: `bats --timing`, `python3 -m unittest --durations 10` in the job's runner, so the next run ranks its tests.
- **Rule**: a job that cannot be judged is a finding of its own; measure before cutting.
- **Seen**: plan 0386 step 4: c4-01-bash-test 117779832316 (45 units, none timed) and c2-01-agents-test
  117779832487 (186 tasks, only their own times).

### Single runs under load

- **Symptom**: an A/B whose sides differ by less than the spread, or `reliable: false` (a load over the CPU count).
- **Evidence**: `python3 $M ab --a "<before>" --b "<after>" --runs 2`: read `load` per run and `reliable`.
- **Fix**: repeat on a quiet machine; alternate A and B; never create load to test timing.
- **Rule**: a run under load 20-120 proves nothing; the unit only measures, it never loads the machine (D4).
- **Seen**: 0365, all timing work.

## Waste inside a test

### real-sleep

- **Symptom**: `scan` prints `real-sleep`: a `sleep N`, `time.sleep(`, `thread::sleep` over 0.1 s, or a literal
  assigned to a TIMEOUT / WAIT / DELAY / INTERVAL name in shell or Python; `report` shows silences (gaps) inside a
  test unit.
- **Evidence**: `python3 $M scan <folder> --json` (file:line); `python3 $M report <job>` for the gap in the unit.
- **Fix**: make the wait a constant (env var or argument) the test sets to 0; assert the production value once, in
  its own test. A Rust poll sleep in a loop is a clue: look at what it polls first.
- **Rule**: the wait is production behaviour, so a test of the value stays; only the other tests skip the wait.
- **Seen**: 0365; the repo scan has 238 clues, 151 in Rust tests (mostly poll loops).
- **Seen**: plan 0386 step 4: a poll option `--interval 1` on 33 calls of agents-test's `test_ci_stop.bats` (its
  slowest task, 19 s): a lingering run waits it per round; `--interval 0` where the max wait is not the subject.

### repo-per-test

- **Symptom**: `scan` prints `repo-per-test`: a `git init` / `git clone` or a farm built in a bats `setup()` or a
  Python `setUp`; `spawns` shows `git` in the thousands.
- **Evidence**: `python3 $M scan <folder>`; `python3 $M spawns --only git -- <the unit's test command>`.
- **Fix**: build the repo or farm once per file (bats `setup_file`, Python `setUpClass` or a module-level template)
  and copy it per test (`cp -a`), so each test still starts from a clean state.
- **Rule**: a test never shares a mutable repo with another; the copy keeps the isolation.
- **Seen**: 0365: the tollman suite started 11,805 git processes (437 s).

### interpreter-per-call

- **Symptom**: `scan` prints `interpreter-per-call`: `python3 <script>` or `subprocess.run([... "python3"` at
  3 places in a file, or at one place a file of 5 tests calls; `spawns` shows `python3` in the hundreds.
- **Evidence**: `python3 $M scan <folder>`; `python3 $M spawns --only python3 -- <test command>`.
- **Fix**: call `main()` in-process with the same argv, cwd, env and stdin; keep one real-process test per CLI so the
  entry point is still run.
- **Rule**: the in-process call must reproduce argv, cwd, env and stdin, or it tests something else.
- **Seen**: 0365: 464 python3 starts in one suite.

### ln-loop

- **Symptom**: `scan` prints `ln-loop`: `ln -s` (or `os.symlink`) inside a loop of a test helper, about 1000 `ln`
  per test to build a PATH.
- **Evidence**: `python3 $M scan <folder>`; `python3 $M spawns --only ln -- <test command>`.
- **Fix**: one `ln -s` with all files (`ln -s a b c dir/`), or one linked folder built once per file.
- **Rule**: build a test's PATH once; do not rebuild it per test.
- **Seen**: 0365.
- **Seen**: plan 0386 step 4: agents-test's `test_ci_stop.bats:123` `path_without_gh` started 963 `ln` in one test
  (`spawns --only ln`, on macOS; Linux's /usr/bin has more); `test_check_landing_cli.bats:62` the same twice.

### leaked-child

- **Symptom**: `scan` prints `leaked-child`: a fake helper (heredoc, string, fake-named script) running `sleep N`
  (over 1 s) without `exec` or closed fds; the test's end waits N seconds for bats' output pipe (18.7 s with
  `sleep 30`); `report` shows a gap at the end of a unit.
- **Evidence**: `python3 $M scan <folder>`; a unit whose tests pass but whose wall time ends N seconds later.
- **Fix**: `exec sleep` in the fake, or close its fds (`>/dev/null 2>&1 </dev/null`) so the child cannot hold the
  pipe.
- **Rule**: a fake that outlives its test must not hold the runner's pipe.
- **Seen**: 0365: a fake helper's `sleep 30`, 18.7 s.
- **Seen**: plan 0386 step 4: c2-03-bash-test-docker 117779832452, `shared/test.bats:16` the fake credential helper's
  `sleep "${HELPER_SLEEP:-0}"` (30 in test 27): 19 s of silence after the run's last test, 17% of the job; `report`
  hints such a gap `leaked-child`.

### suite-rerun

- **Symptom**: `scan` prints `suite-rerun`: a test that runs `bats` on a folder, `unittest discover`, `pytest` or
  `cargo test`; one test takes as long as a whole suite (130 s).
- **Evidence**: `python3 $M scan <folder>`; the longest test in `python3 $M rank <job>`.
- **Fix**: test the runner on a tiny fixture suite; shard the real suite so its modules run in parallel.
- **Rule**: never rerun the suite inside a test; the suite is run by the job.
- **Seen**: 0365: 130 s.

## Waste around the tests

### docker-copy-per-run

- **Symptom**: `scan` prints `docker-copy-per-run`: a Dockerfile `COPY` / `ADD` of a key, token, `authorized_keys`
  or other per-run file; the image build never hits its layer cache (`report` setup kind `image` rebuilt each run).
- **Evidence**: `python3 $M scan <folder-with-the-Dockerfile>`; `python3 $M split <job>` setup steps of kind `image`.
- **Fix**: mount the per-run file at `docker run` (`-v`, `--mount`, a BuildKit secret) so the image is the same
  every run and its cache hits.
- **Rule**: an image holds nothing that changes per run.
- **Seen**: 0365 for a Docker test image with a per-run SSH key; the repo scan finds one such COPY
  (publish-download's test Dockerfile, `COPY authorized_keys`).

### ssh-no-multiplex

- **Symptom**: `scan` prints `ssh-no-multiplex`: `ssh` in scripts or helpers without `ControlMaster` /
  `ControlPersist` (2 calls, or one in a loop); one handshake per call; `spawns --only ssh` counts them.
- **Evidence**: `python3 $M scan <folder>`; `python3 $M spawns --only ssh -- <command>`.
- **Fix**: `-o ControlMaster=auto -o ControlPath=<dir>/%C -o ControlPersist=60` (a short socket path: the path
  length of a unix socket is limited).
- **Rule**: reuse one connection per host and run; close it when the script ends.
- **Seen**: 0365; the repo scan has 14 such files.
- **Seen**: plan 0386 step 4: rsync over ssh counts too (`-e "${ssh[*]}"`, each rsync a handshake):
  `publish-download/main.sh`, whose 23 tests in bash-test-docker take 1m18s, 3.4 s each; the test can pass
  ControlMaster options through `HAL2_DOWNLOADS_SSH`, the product unchanged.

### serial-bats

- **Symptom**: `scan` prints `serial-bats`: one `.bats` file over 150 tests, run by one serial bats process; in
  `rank` it is the longest unit (the floor) of a parallel job.
- **Evidence**: `python3 $M scan <folder>`; `python3 $M rank <job>` marks the floor.
- **Fix**: split the file by topic so the runner runs the files in parallel, biggest first.
- **Rule**: the wall time of a parallel job is its longest unit; split that one, not the others.
- **Seen**: 0365: `gate/test.bats`, 219 tests, 4:52 (the repo scan: 216 tests).

## Structure of a job

### Bound by the workers

- **Symptom**: `report` prints `bound by the workers`: a runner's work per worker (`Ys of work` / `W workers`) is
  longer than its longest task; the floor does not set the wall.
- **Evidence**: `python3 $M report <job>`: the bound line and the slowest tasks (`rank`'s sections, timed `own`).
- **Fix**: cut work anywhere, biggest tasks first: every W seconds of work saved is one second of wall; then CPU
  (spawns, sleeps) matters as much as the long pole.
- **Rule**: on a work-bound job rank fixes by CPU saved, not by the longest task.
- **Seen**: plan 0386 step 4: c2-01-agents-test 117779832487, 186 tasks in 40 s on 8 workers (317 s of work, longest
  task 19 s).

### Start order of parallel units

- **Symptom**: `report` prints `bound by the slots or the start order`: the test part is over 1.1x its longest unit;
  units start in name order, so a long one that starts late ends the job.
- **Evidence**: `python3 $M report <job>`: the bound line (units, work, how many at once); the last block printed
  (its `1..N`) is the unit that ended the test part.
- **Fix**: start the units longest first (the last run's unit times, else their test counts); print the slot count
  and each unit's start so the next run shows the schedule.
- **Rule**: biggest first (see Serial files); the floor is then max(longest unit, work / slots).
- **Seen**: plan 0386 step 4: c4-01-bash-test 117779832316, 45 units, 48m52s of work on the VM's 8 CPUs (at least
  6m06s), test part 7m27s; the 266-test `gate` unit (3m39s) started 4m15s in and ended it.

### Serial files inside one job

- **Symptom**: `report` shows the test part as one long sequence of folders or files (`-- <dir>: <runner>` sections
  one after the other) on a machine with idle CPUs.
- **Evidence**: `python3 $M rank <job>`: the sections' times add up to the test part; the CPU count in the runner's
  setup step.
- **Fix**: one process per test file on the CPUs, biggest first, the whole output per task, a slowest-N report
  (the pattern of `code/python/scripts/agents-test/runner.py`).
- **Rule**: the order is biggest first so the long pole starts at once.
- **Seen**: 0365: agents-test 9:20 to one parallel run.

### The long pole

- **Symptom**: one unit is most of the test part (`rank` marks it as the floor): gate/test.bats 219 tests, 4:52.
- **Evidence**: `python3 $M rank <job>`: the floor and its share; speeding up any other unit does not move the wall.
- **Fix**: split that unit by file or topic (see serial-bats), then re-rank: the next longest is the new floor.
- **Rule**: stop when the floor is within the setup's size; the next gain is in setup.
- **Seen**: 0365.

### Changed-only selection inside a job

- **Symptom**: a job runs every test although the change touches one folder.
- **Evidence**: `python3 $M rank <job>`: units that cannot depend on the change; the diff's folders.
- **Fix**: static cross-references (`deps.py`), transitive; everything runs on a shared or unknown file.
- **Rule**: on any doubt run everything; a missed test is worse than a slow job.
- **Seen**: 0365.

### Per-job setup

- **Symptom**: `split` shows setup of kind `install` or `image` as a large share (rustup 23 s, brew bats in the Mac
  VM on each run) or a silence in a setup step; a job that needs nothing still pays its hook (a job "not needed"
  spent 10 s in the job-start hook).
- **Evidence**: `python3 $M split <job>`: setup per step and kind, the gaps in it.
- **Fix**: bake the tool into the runner image, or skip the step when the job does not need it.
- **Rule**: a job installs only what it uses (ci-minimal-by-design); the image's cache must hit (see
  docker-copy-per-run).
- **Seen**: 0365: rustup 23 s; c4-01-bash-test setup 47 s of 4m11s, 40 s of it installs (plan 0386 step 1).
- **Seen**: plan 0386 step 4: c4-01-bash-test 117779832316, `gate tools` 4m07s of 12m15s for a job that compiles no
  Rust (its bats fake cargo): rustup's toolchain download 2m24s (the VM's PATH has the host's proxies, no
  toolchain), Homebrew's auto-update about 30 s, protobuf + abseil 40 s, `brew cleanup` 5 s, bats-core (not in the
  VM's Brewfile) 3 s. Install per job (a header of the gate job file), bake the Brewfile and bats-core into the
  image, `HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_CLEANUP=1` in `need`.

### Product-side wins from profiling

- **Symptom**: `spawns` counts many `git` calls from product code, not from the test arrangement.
- **Evidence**: `python3 $M spawns --only git -- <the CLI's command>`; the git subcommand in the shims' log.
- **Fix**: cache the git common dir, toplevel and origin per process; one `worktree list --porcelain` instead of one
  per worktree.
- **Rule**: product-code changes are reviewed for behaviour; the tests do not change.
- **Seen**: 0365.

## Not worth it

- **Per-folder green markers inside a job**: the risk of a stale green (a marker that missed a changed dependency)
  outweighs the minutes; green markers belong to the whole job (ci-analyzer check 14 finds the ones that missed).
- **GNU parallel or `bats --jobs`**: not on the Linux image; run one process per test file instead (see Serial files).
