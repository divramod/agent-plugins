"""The declared health path is missing from the repository, or its answer depends on more than the app."""

from checks import finding

SLUG = "health-route"
WHY = "the engine calls the health path before it cuts over: anything but a 2xx keeps the old container"


def run(ctx):
    found, health = ctx.get("inspect"), ctx["container"].get("health")
    if found is None or not health:
        return []
    handler = found["health_handlers"].get(health)
    if handler is None:
        if health in found["health_routes"]:
            return []
        known = sorted(found["health_routes"]) or "none"
        return [finding(SLUG, "warn", f"declared health {health} is not a route of the repository (found: {known}): "
                        "a path that answers 404 keeps the previous container")]
    out = []
    where = ", ".join(handler["files"])
    if handler["database"] and handler["status_503"]:
        out.append(finding(SLUG, "warn", f"{health} ({where}) answers 503 when its database is unreachable: the "
                           "container needs its database secret and network at the first deploy, or it is kept out"))
    if handler["rate_limited"]:
        out.append(finding(SLUG, "warn", f"{health} ({where}) is rate limited: the engine polls it every second for up "
                           "to a minute from one address and a 429 counts as unhealthy; raise the limit for the deploy"))
    return out
