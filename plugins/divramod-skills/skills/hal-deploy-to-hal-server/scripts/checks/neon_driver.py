"""The Neon serverless driver needs Neon's HTTP proxy."""

from checks import finding

SLUG = "neon-driver"
WHY = "the driver speaks Neon's HTTP and WebSocket proxy, so it cannot reach a plain Postgres on a server"


def run(ctx):
    found = ctx.get("inspect")
    if found is None or "@neondatabase/serverless" not in found["drivers"]:
        return []
    return [finding(SLUG, "warn", "@neondatabase/serverless needs Neon's HTTP proxy: it works against hosted Neon; a "
                    "plain Postgres needs that proxy beside it or another driver (references/limits.md, per-app Postgres)")]
