---
name: important-interrupt
description: Quiet the whole Mac in ONE script call, no question asked, for an important call or any moment the user needs 100% compute — every live session is told by code, builds and tests are frozen, the CI runner and CI VMs stopped, the time to quiet measured; `/important-interrupt done` undoes it all. Use when the user says /important-interrupt, "I have a call", "I need 100% compute", "stop everything now", or, for done, "important interrupt is over". `/important-interrupt h` shows help.
---

# important-interrupt

`S=<skill-dir>/scripts`, `I="python3 $S/interrupt.py"`. One script call does everything; the model only runs it and
relays its last lines. Never SendMessage yourself (the script tells the sessions), never ask a question (no safety
question: the user is waiting for a quiet machine).

| Call | Runs |
|---|---|
| `/important-interrupt` | `$I stop` |
| `/important-interrupt done` (alias `continue`) | `$I done` |
| `/important-interrupt stats` | `$I stats` (`--json`, `--last N`) |
| `/important-interrupt --dry-run` (also `done --dry-run`) | the same, prints every action, changes nothing |
| `/important-interrupt h` | print this table and stop |

`stop` takes `--idle`, `--timeout`, `--reply-wait`, `--note`; its defaults are right, pass them only on the user's word.

## stop

Tells every live session by code, then quiets the machine in six sources, each measured (seconds taken, CPU idle
after) and recorded with its undo. Kept: this session, its checkout and the user's apps (Teams, Zoom, Chrome,
terminals). A landing is never aborted: its processes are frozen in place and adopted again on `done`.

| # | Source | stop | undo in `done` |
|---|---|---|---|
| 1 | sessions of every farm (also other farms' farmers, `farmer-*`) | told by code, who paused is collected | "continue" to those it paused; earlier-held ones stay |
| 2 | hal2-daemon | its pollers held (`hal2-cli-machine quiet hold pollers`: no CI wake, no runner clone, no git status; a hold set before stays), without the CLI SIGSTOP (so it starts no CI VM) | pollers released (or SIGCONT), last |
| 3 | CI VMs | `tart stop` (clones kept) | none needed (the daemon starts them) |
| 4 | workqueue holders | `hal2-cli-workqueue freeze all`, SIGSTOP of the `freeze serve` pids, quiet on | CONT, `thaw all`, quiet off (first); a quiet the user set before stays |
| 5 | host runners of every repo (`~/.local/share/hal2/host-runner/divramod-<repo>-*`) | `hal2-cli-ci runner stop --repo divramod/<repo> --all`, no `--force` | `runner start`, only the runners this stop stopped |
| 6 | build/quiet pass (`quiet.py`: builds and tests frozen, simulators, Ollama, timer LaunchAgents, Docker) | one scan, every action under a timeout, then rescans until the CPU is quiet | quiet.py's undo, before the daemon |

- Busy runner (D8): never forced; it is refused, reported and retried by the rescans, its job's builds are frozen
  meanwhile; it does not block "quiet" and is named at the end. Unreadable `runner status` (D10): every runner is
  stopped by its folders, `done` starts them all, with a printed warning.
- Missing tool (tart, hal2-cli-ci, hal2-cli-workqueue, nettop, tmutil): reported, never fatal. Every probe runs
  under a timeout (a timeout is printed, not fatal).
- Measure: each step prints `-- <step>: <n> in <s>s`; `stats` shows the log's rows, median and max to quiet.
- Leftover report (report only, nothing is stopped): CPU top, network top, Docker VM, Time Machine, Spotlight, Chrome.

Relay the last lines: the seconds to quiet, the sessions that gave no answer (they wait for approval in their own
terminal), what still runs (leftovers, a busy runner). Exit 4 means the CPU was not quiet in time: say what still runs.

## done

Undoes the stop in reverse (the workqueue first, so full CPU is back by default; the machine next, hal2-daemon's
pollers (or hal2-daemon) last, then the sessions get "continue"). An earlier stop stays in force. Exit 1 with one line when no interrupt is
active. Relay its lines: who got the message, who is gone or failed.

Related: [stop-all-agent-work](../stop-all-agent-work/SKILL.md) (asks a safety question, works by hand),
[continue-all-agent-work](../continue-all-agent-work/SKILL.md) (also undoes an interrupt's record).
