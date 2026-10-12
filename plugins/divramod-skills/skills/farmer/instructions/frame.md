# Woken for the round frame (frame)

| Kind | Do |
|---|---|
| `mfm-failed` | merge-from-main in the farmer slot failed (conflict, a setup task, a hook). The farmer never changes its branch beyond roles/farmer/ROLE.md: a conflict outside it means main and the farmer branch disagree on a file the farmer must not hold. Read the evidence; `git merge --abort` when a merge is half done, notify the user with the files. A failing setup task: delegate its fix |
| `role-invalid`, `role-gone` | Notices: push them to the user. Never edit roles/farmer/ROLE.md |
| `no-handler` | A due duty without a tick handler: run it as its subskill says |

Log each: `python3 $S/mtm_scan.py record <kind> - "<what>" --note "<why>"`.
