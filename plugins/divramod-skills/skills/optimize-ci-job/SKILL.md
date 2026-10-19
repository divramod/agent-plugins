---
name: optimize-ci-job
description: Take one CI job deep to cut its runtime and CPU load — runs hal2's `ci-job` unit (`code/python/scripts/ci-job/main.py`), whose scripts measure and the skill only judges: fetches the job's log (GitHub GET, cached), splits its wall time into setup / units / tests / tail and its silences, ranks the units (a parallel job is as long as its longest) and the slowest tests, scans the test files for known slow patterns (real sleeps, a repo per test, a python3 per call, a leaked child, a per-run Docker COPY, ssh without multiplexing, a suite rerun, one big bats file), counts the process starts of a command (`spawns`) and times two commands against each other under a noted load (`ab`); then matches the findings with `causes.md` (the learnings of plan 0365) and ranks the fixes by runtime saved, then CPU saved, as shots or one brief to the farmer. Read-only: never edits a workflow, never reruns, cancels or dispatches, never drops or weakens a test. Use when the user says /optimize-ci-job, "optimize this CI job", "why is <job> slow", "cut the CPU load of a job" or "deep look into a CI job". `/optimize-ci-job h` shows help.
---

# optimize-ci-job

Thin by the record [deterministic-first](../../../../../../../.adr/deterministic-first.md): the unit measures as code;
you judge. `M=<hal2 checkout>/code/python/scripts/ci-job/main.py`: the current repository when it is hal2, else
`~/a/hal2`. Read-only, so any worktree's copy will do. ci-analyzer is the whole-CI view (which job is the bottleneck);
this skill is the one-job view (why that job is slow). Decisions: plan 0386 D1-D6.

| Call | Does |
|---|---|
| `/optimize-ci-job <job id>` | `python3 $M report <job id> --json`, then judge (below) |
| `/optimize-ci-job <run id> <name>` | `python3 $M fetch --run <run id> --name <name>` gives the job id, then as above (the exact name wins; several matches name them) |
| `/optimize-ci-job scan <folder...>` | `python3 $M scan <folder...> --json`, then judge the smells |
| `/optimize-ci-job spawns -- <cmd>` | `python3 $M spawns -- <cmd>`: process starts per binary, total, wall |
| `/optimize-ci-job ab --a "<cmd>" --b "<cmd>"` | `python3 $M ab --a ... --b ...`: A B A B, medians, load before each run |
| `/optimize-ci-job h` | print this table and stop (`python3 $M h` shows the unit's own help) |

A log file path works where a job id does (`split`, `rank`, `report`); `--offline` reads the cache only, `--state`,
`--repo` as in the unit's README. A missing `gh` or a failed call: report the message and stop. Without a job: ask
for one in one line, or take the newest run's jobs of the workflow the user names (`gh api` GET only).

## Method

Run the steps in this order; each is a call of the unit, you read its output and never recompute it.

1. **Split the wall time.** `report <job>`: setup (runner, hook, checkout, cache, image, install), the test part, the
   tail after the last test line, the silences over 10 s (`--gap`). A large setup or tail or a gap in the middle is
   waste before any test is looked at.
2. **Rank.** The units (`gate: unit <x>: passed <t>`) and the slowest tests (bats `--timing`, unittest
   `--durations`, nextest). A parallel job is as long as its longest unit (the floor): speed up that one, the others
   do not move the wall time, unless `report`'s bound line says otherwise: bound by the workers (cut work anywhere)
   or by the slots or the start order (start the longest first). Tests that print no times (bats without `--timing`, unittest without `--durations`)
   are a finding of their own: the next run cannot be judged without them.
3. **Scan** the test files of the top units: `scan <their folders>`. A finding is a clue, not a verdict: read the
   lines before a fix is proposed (a Rust poll sleep in a loop is not always waste). A line holding `ci-job: ignore`
   is a decision already taken.
4. **Count spawns, not CPU.** `spawns -- <the unit's test command>` when the scan or the profile points at process
   starts (git, python3, bash, ssh, ln): plan 0365's tollman suite started 11,805 git processes (437 s).
5. **A/B** a fix on the same machine: `ab --a "<before>" --b "<after>"`, each at least twice. Single runs under
   load 20-120 mean nothing: when the result says `reliable: false`, say so and repeat on a quiet machine, never
   create load to make it quiet or to test timing (the user's rule).

## Judge

Match each measured clue with a case of [causes.md](causes.md) (symptom, evidence command, fix, rule). Then rank the
fixes by runtime saved on the job's wall time (the floor first), then CPU saved. For each give:

- the evidence: job id, seconds, `file:line` of the scan finding or the unit and test, the command that shows it;
- the cause in one line (the case's name) and the fix in one line;
- the saving as an estimate marked so, or the A/B's numbers when measured;
- what the unit could not see (a job with no per-test times, a log cut by GitHub, the machine's load).

Mark a clue as not worth it when `causes.md` says so (a per-folder green marker inside a job, GNU parallel or `bats
--jobs` that the Linux image lacks). New causes found while judging are added to `causes.md` (newest first, a
recurrence adds a line under its case).

## Rules

- **No test dropped or weakened, no assertion changed**: a speed-up changes how a test arranges or runs, never what
  it checks (the fast-tests record and guide, landing with plan 0365; cited by name until they are on the default
  branch, D5). Product-code changes found by profiling are reviewed for behaviour.
- **Propose only** (D6): one shot per fix (`/create-shot`, the CI shotfile, else a new one named `ci`) or, for
  several related ones, one brief to the farmer (SendMessage to `farmer-<repo>`, the newest from ListAgents). A fix in
  code only when the user asks for it in a field, by the rule above, with the product-code changes reviewed.
- **Read-only against GitHub** (D2): GET only. Never dispatch, rerun or cancel a run (ci-check runs are the
  tollman's call); never edit a workflow or the CI graph (field 01's, plan 0349): propose it to the farmer.
- Follow [ci-minimal-by-design](../../../../../../../.adr/ci-minimal-by-design.md) (a job runs only what it needs) and
  [performance-first](../../../../../../../.adr/performance-first.md) (a measured latency, not a guess).

End with the table of fixes (rank, job, evidence, cause, fix, saving) and the shots or brief made.
