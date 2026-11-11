# Known limits (plan 0759's open questions; named here, never decided by the skill)

- **Per-app Postgres and object storage (Q1):** the server runs one container per site and builds no database or
  storage for it. An app needing its own Postgres or S3 keeps a hosted one (a secret such as `DATABASE_URL`) until the
  user decides; say so in the report.
- **Production host or a separate server (Q2):** apps share the production host, capped together by `[sites]
  containers_memory` in hal9k.toml. Do not size memory to fit if the cap is exceeded; report it.
- **Private image pull credential (Q3):** the deploy key may only name a digest, so a private ghcr.io image is refused
  with the reason `pull`. Public images deploy; for a private one tell the user it waits for Q3.
- **Moving an app off its current host:** a farm's own record may keep it elsewhere (Vercel, Neon and Supabase free
  tiers, another server). The checks say what a move needs; whether it moves is the user's and that farm's call.
- **An app on the zone's apex:** refused here (plan 0759 D14); the apex keeps its own server until the user decides
  otherwise. A subdomain is a dry run of the route, not a move of the site.
- **How an app stops depending on its platform:** `VERCEL_ENV` as a declared value or a code change in the farm, a
  Dockerfile, a non-root user: the farm's code, written in that farm, never from this skill.

Ask the user (Q form) only when one of these blocks the deploy; never decide it.
