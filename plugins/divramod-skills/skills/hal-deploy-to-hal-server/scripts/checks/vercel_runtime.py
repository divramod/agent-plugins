"""The build is made for Vercel, and the code asks Vercel who it is."""

from checks import finding

SLUG = "vercel-runtime"
WHY = "off Vercel the preset still shapes the build and VERCEL_ENV is unset, so production switches stay off without an error"


def run(ctx):
    found = ctx.get("inspect")
    if found is None:
        return []
    out = []
    if found["vercel"]["deps"]:
        out.append(finding(SLUG, "warn", f"built with {found['vercel']['deps']}: the server bundle is shaped for Vercel; "
                           "the image's start command must serve that output (its `start` script, not Vercel's builder)"))
    readers = found["vercel"]["env_readers"]
    if readers and "VERCEL_ENV" not in ctx["container"].get("env", {}):
        out.append(finding(SLUG, "warn", f"VERCEL_ENV is read by {readers} and unset in a container: what it switches "
                           "(production cookies, the storage driver) falls to its non-production value"))
    return out
