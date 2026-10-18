# lookout

Global watches for every farm: a 5-minute timer runs each due watch's check command, a quiet run costs 0 tokens, a new
find is judged once (capped), recorded, jotted into the daybook and pushed to the user. Usage: [SKILL.md](SKILL.md).
Design and decisions: [plan 0311](../../../../../../../plans/0311-lookout/design.md) (`design.md`, `decisions.md`).
Stdlib Python only; tests: `python3 -m unittest` in `scripts/`.

## Module map (`scripts/`)

| File | What |
|---|---|
| `lookout.py` | the CLI table `COMMANDS`: `start\|stop\|status` (timer on the farmer's `timer.py`) plus those of `lookout_cmds.py` |
| `lookout_cmds.py` | the handlers of `add\|set\|end\|list\|log\|finds\|run\|tick` (a refusal prints `lookout.py: <why>`, exit 2) |
| `store.py` | the farm files `<farm>.yaml` through the daybook's `watchfile.py`, the `Lock`, validation, `add\|set_keys\|end`, `update_run_keys`, `changes.jsonl` |
| `lookout_tick.py` | the tick: `tick.lock`, `heartbeat`, due check, `runner.run_watch`, retries, the find path, alerts, ends a settled watch |
| `lookout_frame.py` | puts the farmer's and the daybook's `scripts/` on the import path |
| `paths.py` | config and state roots (XDG, `LOOKOUT_DIR`, `LOOKOUT_STATE_DIR`), `log.jsonl`, `settings.json` |
| `runner.py` | the check contract: argv, env, cwd, timeout, exit codes, dedupe; `run_watch` |
| `proc.py` | one bounded process run, the process group killed on timeout |
| `watchstate.py` | a watch's `state.json`: `delivered` (30 days), `pending`, failure counters, alerts |
| `judge.py` | the `claude -p --tools ""` run, env scrub, 32 kB cut, per-run budget, daily cap, log line |
| `find.py` | find record, `apply`, daybook item, notify; each step marked so a retry never doubles one |
| `notify.py` | one `send(...)` over the `desktop` and `telegram` backends; never raises |
| `checks/email.py` | the generic e-mail check over `hal2-cli-email messages search` |
| `check-prerequisites.sh`, `install-prerequisites.sh` | python3; optional claude, a desktop notifier, hal2-cli-secrets; then `checks/`'s pair (hal2-cli-email, optional) |
| `fakes.py`, `test_*.py` | fake checks, fake `claude`, the tests |

## The check contract in short

cwd is the watch's `farm`; stdin the record as JSON; env `LOOKOUT_FARM`, `LOOKOUT_WATCH`, `LOOKOUT_STATE` (the only
place a check writes), `LOOKOUT_SINCE`, `LOOKOUT_DRY_RUN=1` on a dry run. The command is one `shlex`-split line, `{python}`
and `{checks}` expanded, never a shell. Exit 0 quiet, 10 found, 11 found and settled, 75 not checkable, else broken
(stdout over 64 kB or a found line without `id`/`summary` is broken). Full table: design.md, "Check contract".

## Where things are

`~/.config/hal2/lookout/<farm>.yaml` (records, the daybook's `watches:` format; `<farm>` is the main checkout's project
name), `changes.jsonl` (one line per CLI change: at, by, farm, watch, op, changes {key: [old, new]}), `settings.json`,
`.store.lock`; state in `~/.local/state/hal2/lookout/` (`tick.log`, `heartbeat`, `tick.lock`, `log.jsonl`,
`state/<farm>/<id>/state.json` and `check/`, `state/<farm>/finds.jsonl`). The tick writes only `last_run`, `last_result`
and `state` into a record, without a change line (a settled check also ends the watch, logged `op: end` by `lookout tick`). `XDG_CONFIG_HOME`,
`XDG_STATE_HOME`, `LOOKOUT_DIR`, `LOOKOUT_STATE_DIR` move them.

## Settings (`settings.json`, names only, never a secret)

```json
{"notify": ["desktop"], "daily_budget_usd": 1.00,
 "telegram": {"token": "TELEGRAM_BOT_SEC", "chat": "TELEGRAM_CHAT_SEC", "repo": "/path/to/repo"}}
```

`telegram.token` and `telegram.chat` are secret names read with `hal2-cli-secrets show <NAME_SEC> --repo <repo>`; without
them `LOOKOUT_TELEGRAM_TOKEN` and `LOOKOUT_TELEGRAM_CHAT` are used. `daily_budget_usd` caps the judge runs of a day
(over it the find goes on unjudged).

## Daybook lookup order

The daybook CLI `daybook.py` is found by: an explicit path, `$LOOKOUT_DAYBOOK`, `skills/daybook/scripts/daybook.py`
beside this skill, then `~/.claude/skills/daybook/scripts/daybook.py`. Missing: the find stays in `finds.jsonl` and
the notification says there is no daybook item.

## The e-mail check (`checks/email.py`)

Binary: `$LOOKOUT_EMAIL_CLI` (a command line), else `hal2-cli-email`; it syncs first. Options: `--query`, `--address`,
`--account`, `--limit` (50), `--no-sync`, `--known-from CMD` (a command printing message ids to drop), `--first-hours`
(24, the first run's look-back), `--overlap-min` (15). Exit 0 no new mail; 10 one JSON line per mail (`id`
`email-<message-id>`); 75 with a cause `missing`, `auth` or `offline`; else 1. Its since-time is kept in
`$LOOKOUT_STATE/email-since.json`.

## Windows

`timer.py` has launchd and systemd only; on Windows `start` and `stop` print the gap and the `schtasks` line (D8).
