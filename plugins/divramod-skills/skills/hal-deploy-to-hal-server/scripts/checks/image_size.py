"""The final stage carries a full node_modules, so the image may pass max_image."""

from checks import finding

SLUG = "image-size"
WHY = "the engine sums the layers before the pull and refuses an image over max_image; only the built image shows its real size"


def run(ctx):
    found = ctx.get("inspect")
    if found is None:
        return []
    heavy = sorted(name for name, facts in found["docker"].items() if facts["copies_node_modules"])
    if not heavy:
        return []
    limits = ctx.get("limits") or {}
    cap = ctx["container"].get("max_image", limits.get("default_max_image", "the default"))
    return [finding(SLUG, "warn", f"{heavy} copy all of node_modules into the final stage: measure the pushed image against "
                    f"max_image ({cap}; the pull is refused over it) or copy only production dependencies")]
