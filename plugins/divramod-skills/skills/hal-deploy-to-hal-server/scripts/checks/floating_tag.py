"""The repository's compose runs a floating tag; this server deploys one digest."""

from checks import finding

SLUG = "floating-tag"
WHY = "a tag says nothing about what runs, and the forced command takes only a digest"


def tag_of(image: str) -> str | None:
    last = image.rsplit("/", 1)[-1]
    if "@" in last:
        return None
    return last.split(":", 1)[1] if ":" in last else "latest"


def run(ctx):
    found, image = ctx.get("inspect"), ctx["container"].get("image")
    if found is None or not image:
        return []
    owner = "/".join(image.split("/")[:2]) + "/"
    floating = sorted({f"{r['file']}: {r['image']}" for r in found["image_refs"]
                       if r["image"].startswith(owner) and tag_of(r["image"]) == "latest"})
    if not floating:
        return []
    return [finding(SLUG, "warn", f"{floating} float on a tag: on this server CI must deploy the digest its push printed "
                    "(`ci-step`), and a compose file with :latest is not the deployment here")]
