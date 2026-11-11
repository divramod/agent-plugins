---
name: hal-deploy-to-hal-server
description: Put a farm's container app on the hal9k server, code first — inspect, declare the site, check its Caddy route, print the CI step, read status, deploy one digest after the user's go; each new problem becomes a tested check. Use when the user says /hal-deploy-to-hal-server, "deploy this app to the hal9k server", "host this app on hal9k" or "why did the hal9k deploy fail". `h` shows help.
---

# hal-deploy-to-hal-server

Scripts do every deterministic part; you only name hosts, size memory, read the findings and word what a check cannot.
`S=<skill-dir>/scripts`, `D="python3 $S/main.py"`; every command takes `--json`. Design: hal2's plan 0759 (design.md
section 10). hal2's tree is found from the script's real path or `HAL2_ROOT`; outside hal2 only `inspect`, `declare`
without `--out`, `ci-step`, `status` and `learn --brief` work, and `check` says so. Never `cargo install`.

| Call | Does |
|---|---|
| `$D inspect <repo>` | read-only findings: Dockerfile, port, health route, env names (never `.env`), drivers, platform |
| `$D declare --site S --zone Z --host H --key "<pub>" --image I --port P --health /h --memory 512M [--max-image 3G] [--out f.toml]` | the site TOML as a draft; a named path, never hal2's `sites/` unasked (`--into-sites` after the user's go) |
| `$D check --declaration f.toml [--repo <repo>]` | hal2's validation, the generated route through `hal9k-site-check` (needs docker), every check of `scripts/checks/`; exit 1 on a problem |
| `$D ci-step --site S --image I [--repo R --context C --file F --build-arg N]` | the farm's CI steps (`--repo`: a farm on git secret reveals the deploy key with its one CI gpg key and removes it; others get the plain form, marked off the standard; an app in a subfolder: its context and Dockerfile; a build-time name: `--build-arg`); printed, never written into its repository |
| `$D status --site S --key K --known-hosts F` | the server's last deploy status over the forced key |
| `$D deploy --site S --digest sha256:... --key K --known-hosts F --go` | one digest; refused without `--go`, which only the user's yes allows |
| `$D learn <slug> [--problem T] [--brief]` | scaffold a check, its test and a line in `references/problems.md` |
| `/hal-deploy-to-hal-server h` | print this table and stop |

## The order

1. `inspect` the repo; read what it says (no Dockerfile, a port, the health route, env names, a database driver).
2. `declare` a draft to a named path; you choose host, memory and which names are secrets. The key is the farm's public
   deploy key (`ssh-keygen -t ed25519` in the farm; the private half is the git secret `.secrets/HAL9K_DEPLOY_KEY_SEC` on the standard, else the CI secret `HAL9K_DEPLOY_KEY`).
3. `check` with `--repo`; fix every `error` finding, judge each `warn`; a route verdict other than `accepted` stops here.
4. `ci-step`: give the user the steps for the farm's pipeline (the farm owns its CI).
5. Landing the declaration in hal2 and `deploy app` are hal2's and the user's: say what they must do. Then a real
   `deploy` only on the user's go.

Two rules from the farms. **A deploy compose file:** where the farm has `utils/docker-compose/deploy/remote-hub/docker-compose.yml`,
that file is the app's one description: pass `declare --repo <repo>` (`--compose-service` when it has several) so image, port,
env names and memory come from it; `declare --repo R --out <existing.toml>` and `check --repo R` report any difference
(`deploy-content`). It is only read: the engine starts the container, never compose. **A cut-over from a static site:** the
host leaves the static site's declaration and joins the container's in one commit; two declarations of one host make the
apply quarantine a route and retry it on its 5-minute timer (`host-clash` refuses it).

## Reading a deploy's result

`deploy` and `status` print `outcome`, `meaning`, `reasons`; the exit follows the engine.

| outcome | Exit | Do |
|---|---|---|
| `success` (deployed, unchanged) | 0 | report it |
| `kept-previous` | 1 | the candidate failed (`reasons[]`: pull, start, health, cutover, verify), the old container still serves; fix the cause, see A new problem |
| `refused` | 1 | the server refused before touching anything; `reasons[]` names the rule |
| `failed` | 1 | THE OLD CONTAINER DID NOT RESTART and the candidate is left up: tell the user at once, do not retry |
| `pending` | 3 | no result within 10 minutes; the deploy goes on: run `status` later, never deploy again blindly |
| `ssh-error` | 1 | key, host key or network; nothing was deployed |

## A new problem (required)

A problem met during a deploy is not done until the skill knows it. Before calling the deploy done: reproduce it,
`$D learn <slug> --problem "<one line>"`, write the test (it fails until you do) and then the check, run `python3 -m
unittest -q` in `scripts/` until green, and resume the deploy. `test_checks.py` fails on a check without a test or
without its line in `references/problems.md`. Outside hal2 the skill cannot change hal2: run `learn <slug> --brief`
and hand the brief to hal2's farmer instead. A one-off fact that no code can see goes into `references/limits.md`.

## Known limits

[references/limits.md](references/limits.md): per-app Postgres and storage (Q1), production host or a separate server
(Q2), a private image's pull credential (Q3). Named, never decided here.
