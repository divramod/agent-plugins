# Woken for delivery

The tick's delivery check (`deliver_watch.py`, run by the `ci` duty, hal2 plan 0728 D20) reads the Mac's host-side
delivery, `python3 code/python/scripts/deliver-pull-macos/main.py status --json` in the main checkout (schema 1). The
land run no longer has an install box, so a red delivery shows only here. The item's `text` says it, `evidence` holds
`sha`, `run`, `reason`, `log`, `steps`. A red delivery has already reached the user as one push (`alarm.py deliver-red`,
once per sha); never push or ring again for it.

| Kind | Do |
|---|---|
| `red` | Read the sha's `log` (the failed step is the one with `failure` in `steps`). A fault of main's code or of the Mac (a failed sign, a restart that did not come back) is a plan or a shot for the owner of the unit; the Mac keeps its last good install, and only a green `record` moves `deliver/last.json`, so the next main sha is tried again by itself. Never run `deliver` steps by hand while the agent is delivering (they share one lock) |
| `agent-down` | The agent `local.hal2.deliver-pull` is not loaded (a reboot leaves it stopped: boot quiet, plan 0724). In the main checkout run `python3 code/python/scripts/deliver-pull-macos/main.py install` (or `start`); the yard's `/mfm` does it too. Not installed at all and no yard session near: say so in your report |
| `schema` | The unit changed its status shape: update `deliver_watch.py` and its test to the new schema, then the unit's README names it |

After acting: `python3 $S/mtm_scan.py record delivery - "<what>" --note "<why>"`.
