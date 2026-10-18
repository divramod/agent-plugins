---
name: lookout
description: The user's global lookout, the watches that check something on a schedule and tell when it has changed (an answer has come, a page has changed). A 5-minute timer runs `lookout.py tick`, which runs each due watch's check command as code; a quiet tick costs 0 tokens, only a new find of a watch with a `judge` starts one capped model run (`claude -p`, no tools), then the find is recorded, a daybook item is jotted through the daybook's own command and the user is notified (desktop, Telegram). Records live in `~/.config/hal2/lookout/<farm>.yaml`, one file per farm, in the daybook's watches format. Use when the user says /lookout, "lookout", "watch for", "tell me when", "check every 5 minutes" or "has the answer come". `/lookout start` installs the timer, `/lookout h` shows help.
---

# lookout

**Goal: tell the user the moment something they wait for happens, at 0 tokens while nothing does.** A farm adds a
watch (a record with a check command); one global timer ticks every 5 minutes, runs the checks that are due as plain
processes and wakes a model only for a new find that has a `judge` prompt ([design](../../../../../../../plans/0311-lookout/design.md),
decisions D1-D19 beside it). A quiet tick calls no `claude`.

**Deterministic first** ([deterministic-first](https://github.com/divramod/hal2/blob/main/.adr/deterministic-first.md)):
the tick, the checks, the dedupe, the find record, the daybook item and the notification are code; the judge is the only
judgment, and it runs with `--tools ""`, a per-run USD budget and a daily cap. `S=<skill-dir>/scripts`.

| Call | Does |
|---|---|
| `/lookout start` | `python3 $S/lookout.py start`: installs the timer `local.lookout.global` (launchd on macOS, a systemd user timer on Linux), `*/5 * * * *`; `--dry-run` prints the unit without installing. Windows has no timer yet (D8): it prints the `schtasks` line |
| `/lookout stop` | `python3 $S/lookout.py stop` removes the timer |
| `/lookout status` | `python3 $S/lookout.py status`: the timer, the last tick, "lookout not running since <time>" when the heartbeat is over 15 minutes old |
| `/lookout add <id> --farm DIR --title T --cron C --check CMD [...]` | adds a watch to the farm's file (`--farm` defaults to the current folder; validates the kebab id, the cron, that the check's program exists, `--budget` 0-0.50, `--timeout` 1-300, `--notify`; refuses a duplicate id and a file of another farm of the same name); optional keys `--judge`, `--budget`, `--model`, `--apply`, `--notify`, `--timeout`, `--every`, `--until`, `--prompt`, and `--by` (who; else `$LOOKOUT_BY`, else user@host) |
| `/lookout set <id> [--farm DIR] --<key> <value> ...` | changes keys of a watch (`title cron check active` and the optional ones; an empty value removes an optional key; `--farm` only when the id is in several farms); one change-log line |
| `/lookout end <id> [--farm DIR] [--reason R]` | ends a watch (`active: false`, kept as history) |
| `/lookout list [--farm DIR \| --all] [--json]` | the watches (default: this folder's farm), one line each: `farm/id`, active or ended, `state`, `last_run`, cron, title |
| `/lookout log [<id>] [--farm DIR] [--since] [--json]` | the change log `changes.jsonl` (who changed what, old -> new); run results are in `log.jsonl` |
| `/lookout finds [--farm DIR] [--since] [--json]` | the find record of a farm (default: this folder's) |
| `/lookout run <id> [--farm DIR] [--dry-run]` | runs one watch now, due or not, through the whole find path; with `--dry-run` only its check (`LOOKOUT_DRY_RUN=1`), judging and recording nothing |
| `/lookout tick [--dry-run]` | one round now; `--dry-run` prints the watches it would run and runs none; the timer types it (with `--repo <top>`, ignored) |
| `/lookout h`, `/lookout help` | print this table and stop |

A tick prints one line (`<time> quiet (<n> checked)`, or `found <n>` with the watches, alerts, pending finds and ended watches); a second tick while one runs prints `busy`.

## How a farm adds a watch

1. **A check**: any command that follows the contract: input env `LOOKOUT_FARM`, `LOOKOUT_WATCH`, `LOOKOUT_STATE`,
   `LOOKOUT_SINCE`, the record as JSON on stdin; exit `0` quiet, `10` found (JSON lines `{"id","summary","url"?,"data"?}`
   on stdout), `11` found and settled (the watch ends), `75` not checkable now (offline, auth, botcheck), anything else
   broken. The generic one is `checks/email.py` (over `hal2-cli-email`); a farm-only source is a script of the farm.
2. **A judge prompt** (optional): a file in the farm, `--judge @path`; it decides `act` or `ignore` and writes the
   find's title, the 200-character notification text and data. No `judge` means the event's own line is the find.
3. **Record it**: `/lookout add replies --farm ~/a/jobsearch --title "..." --cron "0 */3 * * *" --check '{python}
   {checks}/email.py --query "..."' --judge @code/yaml/watches/replies.md --notify telegram`. Only through the CLI, never
   by hand: one home for the record. Prompt-only daybook watches stay in the daybook; a watch moved here is ended there.
4. **Apply** (optional): `--apply "<farm command>"` runs per find with the find JSON on stdin (the farm's CRM entry, say);
   lookout itself never touches git or a farm file.

Alerts, once per cause until the next clean run: 3 broken runs in a row, or 75 for 6 hours, give one daybook item and
one notification; `auth` and `botcheck` alert at the first. A captcha is never solved.

## Notifications and the daybook

`desktop` (macOS `terminal-notifier` or `osascript`, Linux `notify-send`, Windows PowerShell toast) and `telegram`; the
record's `notify` (`default`, `none`, `desktop,telegram`) overrides settings.json. The daybook item is jotted only
through `daybook.py --farm <farm> jot` (D16), never by editing a day file. Settings and options: [README](README.md).
