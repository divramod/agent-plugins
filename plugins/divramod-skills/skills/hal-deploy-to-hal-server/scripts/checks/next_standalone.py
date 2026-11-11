"""A Next.js app without `output: "standalone"`: the image carries all of node_modules."""

from checks import finding

SLUG = "next-standalone"
WHY = "the standalone output is what fits the image cap and a read-only root; without it the image ships the whole dependency tree"


def run(ctx):
    found = ctx.get("inspect")
    if found is None:
        return []
    plain = [c["path"] for c in found["next_configs"] if not c["standalone"]]
    if not plain:
        return []
    return [finding(SLUG, "warn", f"{plain} set no `output: \"standalone\"`: add it and copy .next/standalone and "
                    ".next/static into the image's final stage, or the image carries all of node_modules")]
