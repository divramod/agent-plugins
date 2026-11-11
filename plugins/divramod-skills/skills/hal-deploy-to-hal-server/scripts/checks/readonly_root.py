"""The container's root is read-only and only declared paths are writable."""

from checks import finding

SLUG = "readonly-root"
WHY = "the root file system is read-only and only `writable` paths are tmpfs, so a write elsewhere fails at runtime"


def run(ctx):
    found, writable = ctx.get("inspect"), ctx["container"].get("writable", [])
    if found is None:
        return []
    out = []
    if "/tmp" not in writable:
        out.append(finding(SLUG, "warn", "/tmp is not in writable: most runtimes write there and the root is read-only"))
    if "next" in found["frameworks"] and not any(w.endswith("/.next/cache") for w in writable):
        out.append(finding(SLUG, "warn", "Next.js writes its cache under .next/cache: add <WORKDIR>/.next/cache to writable"))
    return out
