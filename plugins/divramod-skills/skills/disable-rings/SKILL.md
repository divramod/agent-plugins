---
name: disable-rings
description: Mute the iPhone ring from the agent CLI, one switch every ring obeys (`hal2-cli-ring mode`). `/disable-rings` = off (no Find My call), `silent [--for 2h]` (the message without sound), `off --for 2h`, `on` the way back, `status`. Use when the user says /disable-rings, "disable rings", "sauna", "mute the iPhone ring", "rings back on". `/disable-rings h` shows help.
---

# disable-rings

**Goal: switch the iPhone ring off or silent in one call, and back, without the user touching a setting.** The switch is
`hal2-cli-ring mode` (plan 0606, D12); every `ring` reads it first, `--force` too. A stdlib script does it
(deterministic-first): run it and relay its one line; do not judge or reword. `S=<skill-dir>/scripts`.

| Call | Does |
|---|---|
| `/disable-rings` | same as `off`: `python3 $S/disable_rings.py off`, no Find My call until `on` |
| `/disable-rings off [--for 2h]` | no Find My call; with `--for` it ends by itself (30m, 2h, 1h30m, 1d; at most 30d) |
| `/disable-rings silent [--for 2h]` | the message on the iPhone without the alert sound |
| `/disable-rings on` | the way back: `ring`, with sound |
| `/disable-rings status` | the switch now and when it ends |
| `/disable-rings h`, `/disable-rings help` | print this table and stop |

Run `python3 $S/disable_rings.py <args>`; it prints one line (the mode, its end, how to go back). Exit 2: `hal2-cli-ring`
is not installed (say so, use no other tool); 1: the CLI refused; 64: bad call. The script passes `--from disable-rings`,
so the state file's `by` names this skill. Details: [README](README.md).
