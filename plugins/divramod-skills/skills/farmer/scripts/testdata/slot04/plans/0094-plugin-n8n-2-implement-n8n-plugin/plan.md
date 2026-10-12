# Plan 0094: plugin-n8n 2 implement n8n plugin (trimmed fixture: skills plan 0012)

## Decisions

- 2026-10-01 (user): the approach, scope ("i want it all": one plan), instances (a local stack and the new
  the new instance, not the old the old one), the pane managing the instance itself, the host (the app host,
  not an own server), public behind n8n's login + API key, and personal use only are in
  [INTENT.md](../../INTENT.md) (row of 2026-10-01 on n8n).
- 2026-10-01 (user): the plan may create the paid and public resources itself (the Route 53 record, the deploy on
  the app host, the instance reachable on the internet) and verify against the live instance before landing.
- 2026-10-02 (autogrill 1): built on today's pattern (domain lib, CLI, hal2-ffi, a Feature target), as plans 0095
  and 0100 were, until roadmap line I moves features onto the daemon; no `hal2-plugin.toml` (nothing of it runs on a
  node yet); macOS only, no hal2-api routes; n8n's instance MCP server for agents is not part of this plan.
- 2026-10-02 (autogrill 1): `hal2-n8n` depends on no other domain lib. The API key is a hal2-secrets name the
  surface resolves and hands in. The instance's lifecycle (start, stop, restart, update, logs, backup of n8n's own
  services) is one runner in `hal2-n8n` over the instance's `[runtime]` (plain `docker compose`, locally or through
  `ssh`), so the local e2e covers the commands the remote one runs. This refines INTENT's "the lifecycle logic stays
  in hal2-docker-compose": that lib keeps the local stack as a stack (up, down, reset, test, the Docker Compose
  pane); it has no remote actions and the production n8n is a service of `utils/deploy/hal9k/app`, not one of its
  stacks.
- 2026-10-02 (autogrill 1): production is deployed service by service: `deploy app --service ...` after a
  merge from main, so a deploy from this worktree never rebuilds or restarts the hub, Zitadel, Stalwart or hal2-web.
- 2026-10-02 (autogrill 1): n8n is pinned to an exact 2.x version (2.41.5, stable on 2026-10-02),
  never a floating tag; 3.0 is a later, deliberate update. The widget and the pane warn when the line has a newer
  patch (`api.n8n.io/api/versions`, undocumented: a failed lookup shows nothing). The client refuses an instance
  below the minimum version the spike finds.
- 2026-10-02 (autogrill 1): writes to an instance are confirmed by their diff: `push` and `credentials apply` write
  only with `--yes` (CLI) or after the dry run was shown (pane, as the MCP pane's writer). Workflow files live in
  `workflows/n8n/` of the repository an instance names.
- 2026-10-02 (autogrill 1): Run exists only for workflows with a webhook trigger (no execute endpoint, research
  0025 finding 2); nothing is added to the user's workflows to make them runnable.
- 2026-10-02 (autogrill 1): backups hold the database dump and encrypted exports, never `N8N_ENCRYPTION_KEY` (it
  stays in the secret store); production's database is also in pgBackRest's daily backup already.
- 2026-10-02 (autogrill 1): production hardening: owner by env (hash from the vault), secure cookies, one proxy
  hop, diagnostics off, `/metrics` off, public API on; no extra auth in Caddy (the user chose n8n's login + API key).
- 2026-10-02 (autogrill 1): the landing's gates do not need Docker for the app: hal2-macos's UI test runs against
  the fake n8n server; the real-n8n e2e and the latency budgets are the lib's `test-e2e` verb.
- 2026-10-02 (autogrill 1, provisional: taste): the pane follows the Hetzner and MCP panes (instance picker, tabs
  Workflows | Executions | Credentials | Instance, tables, a detail inspector). A manual grill can change it.
- 2026-10-02 (user): run now, after one autogrill round (the plan's offer); not parked until worktree 00 is done.
- 2026-10-02 (step 1, from [spike.md](spike.md)): a workflow file is matched to the instance's workflow by name
  (n8n assigns workflow ids, and a per-instance id map would be committed state); names are unique within
  `workflows_dir`; `push` never deletes, it lists workflows no file names. Credentials get one own id on every
  instance, so workflow files are not rewritten per instance. Minimum n8n: 2.35.0. The version comes from the
  instance's runtime (image tag), with the editor's meta tag as fallback.
- 2026-10-02 (step 3): `push` republishes a published workflow through its PUT and publishes a created one only
  with `--publish`; it never deletes or unpublishes. A file is its workflow by the `name` inside it. A missing
  credential reference is a warning, not a refusal. Declared credentials live in `<workflows_dir>/credentials.toml`
  with `${SECRET:NAME}` values, resolved by a second resolver (not the API key's); `apply` re-sends data only for a
  missing credential or with `--force`.
- 2026-10-06 (the user, via the farmer 04-13): 09 (plan 0147) joins the train: "also, i want 09 to finish now, when
  its done before the 04-train workflow finishes, it should be part of the train". The reland's run 37439482729 was
  stopped for it (`worktree stop 04`, before main moved) and origin/09 (`3ded7834`) merged.
- 2026-10-06 (the user, via the farmer 04-14): 07 (plan 0148) joins the train too: "then it could also take in 07.
  its also done". Run 37439895802 stopped and cancelled for it, origin/07 (`01cb561a`) merged.

## Notes
  `deploy app --service n8n n8n-runners` (volume `hal9k_n8n` kept, `instances check hal9k` ready, 2.41.5). The
  logins (production and local) are in the main checkout's gitignored `.env` (`N8N_PROD_*`, `N8N_LOCAL_*`) and in
