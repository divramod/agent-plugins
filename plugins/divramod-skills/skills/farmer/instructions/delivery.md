# Woken for delivery

The tick's delivery check (`deliver_watch.py`, run by the `ci` duty, hal2 plan 0755 D30) reads the Mac's install job,
`f3-01-macos-install` (`f3-01-install-mac` in past runs), in the newest land run whose merge is green. The job is the box that installs main onto this Mac
(its host runner is offline until the CI supervisor wakes it for the queued job); nothing in the run needs it, so a
fault never holds a landing. The item's `text` says it, `evidence` holds `sha`, `run`, `job`, `conclusion`, `failed`
(the failed steps). It has already reached the user as one push (`alarm.py deliver-red`, once per sha); never push or
ring again for it.

| Kind | Do |
|---|---|
| `red` | Read the run's job log (`gh run view <run> --log-failed`; the failed step is in `failed`). A fault of main's code or of the Mac (a failed sign, a restart that did not come back, a Touch ID not answered) is a plan or a shot for the owner of the install; the Mac keeps its last good install, and only the green `deploy: record and clean` step moves `deliver/last.json`, so the next landing tries again by itself. Never run `deliver` steps by hand while a run is installing (they share one lock) |
| `stuck` | The job never started: the guard `h1-02-hz-host-install-mac-guard` closed the run after 15 minutes because the Mac's host runner took no job (it is on demand, the CI supervisor wakes it). Main has moved and nothing is lost. Look at the supervisor: `hal2-cli-ci status` and its power log; the runner is the CI supervisor's, never started or forced by hand from here. The next landing installs both. Say so in your report; no plan unless it repeats |

After acting: `python3 $S/mtm_scan.py record delivery - "<what>" --note "<why>"`.
