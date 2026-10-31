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

Tells every live session by code, collects who paused, quiets the machine (`quiet.py apply --runner --yes`: builds
and tests frozen, simulators, Ollama, timer LaunchAgents, Docker, the CI runner), stops the CI VMs and holds
hal2-daemon so it cannot start them again, turns the workqueue's quiet mode on (`hal2-cli-workqueue quiet on`, recorded with its undo; a quiet the user set
before stays; a missing CLI is reported, never fatal), then rescans until the CPU is quiet. Kept: this session, its checkout and
the user's apps (Teams, Zoom, Chrome, terminals). A landing is never aborted: its processes are frozen in place and
it is adopted again on continue.

Relay the last lines: the seconds to quiet, the sessions that gave no answer (they wait for approval in their own
terminal), and what still runs. Exit 4 means the CPU was not quiet in time: say what still runs.

## done

Undoes the stop in reverse (the workqueue's quiet mode off first, so full CPU is back by default; the machine next, hal2-daemon last, then the sessions get "continue"). Sessions that were
held before the interrupt (an earlier stop-all-agent-work or pause) stay as they were; an earlier stop stays in
force. Exit 1 with one line when no interrupt is active. Relay its lines: who got the message, who is gone or failed.

Related: [stop-all-agent-work](../stop-all-agent-work/SKILL.md) (asks a safety question, works by hand),
[continue-all-agent-work](../continue-all-agent-work/SKILL.md) (also undoes an interrupt's record).
