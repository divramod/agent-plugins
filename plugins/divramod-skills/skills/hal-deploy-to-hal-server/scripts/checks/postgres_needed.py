"""The app needs Postgres, which the server does not offer."""

from checks import finding

SLUG = "postgres-needed"
WHY = "the server builds no database for an app yet (plan 0759 Q1), so the database stays hosted and must be reachable"


DRIVERS = {"pg", "postgres", "drizzle-orm", "prisma", "@neondatabase/serverless"}


def run(ctx):
    found = ctx.get("inspect")
    if found is None:
        return []
    used = sorted(DRIVERS & set(found["drivers"]))
    if not used:
        return []
    if ctx["container"].get("egress") is False:
        return [finding(SLUG, "error", f"{used} need a database, and egress = false closes the only way to a hosted one")]
    return [finding(SLUG, "warn", f"{used}: the server offers no Postgres for an app: the database stays hosted, its URL "
                    "a secret (references/limits.md, per-app Postgres)")]
