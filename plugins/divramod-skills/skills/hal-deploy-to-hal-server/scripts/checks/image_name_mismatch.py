"""The declared image is not what the repository publishes."""

from checks import finding

SLUG = "image-name-mismatch"
WHY = "the server pulls only the declared repository, so a digest pushed under another name cannot be found"


def bare(image: str) -> str:
    head, _, last = image.rpartition("/")
    return f"{head}/{last.split('@')[0].split(':')[0]}"


def run(ctx):
    found, image = ctx.get("inspect"), ctx["container"].get("image")
    if found is None or not image:
        return []
    owner = "/".join(image.split("/")[:2]) + "/"
    published = sorted({bare(r["image"]) for r in found["image_refs"] if r["image"].startswith(owner)})
    if found["ci_builds_image"] and found["image_candidate"] and not published:
        published = [found["image_candidate"]]
    if not published or image in published:
        return []
    return [finding(SLUG, "warn", f"declared image {image}, the repository publishes {published}: use the same name or "
                    "the digest will not pull")]
