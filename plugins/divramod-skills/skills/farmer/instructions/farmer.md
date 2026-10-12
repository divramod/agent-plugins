# Woken for the farmer's own work (farmer)

| Kind | Do |
|---|---|
| `delegate-failed` | A servant could not be started (the evidence names the brief and the error). A passing cause (no free slot, a busy session): leave it, the next tick retries the waiting brief. A broken tool (create.py, free.py): `python3 $S/farmer.py delegate --brief <brief> --title <title>` once by hand; still failing: notify the user with the error |

Log it: `python3 $S/mtm_scan.py record delegate <slot|-> "<title>" --note "<what happened>"`.
