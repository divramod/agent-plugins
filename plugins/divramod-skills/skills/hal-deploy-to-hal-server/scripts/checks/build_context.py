"""The farm's CI builds with a context that lacks the Dockerfile's COPY sources."""

from checks import finding

SLUG = "build-context"
WHY = "COPY reads from the build context, so with the wrong context no image is built and nothing can deploy"


def run(ctx):
    found = ctx.get("inspect")
    if found is None:
        return []
    return [finding(SLUG, "error", f"{b['workflow']} builds {b['file']} with context {b['context']}, which lacks "
                    f"{b['missing']}: point the context at the app's folder")
            for b in found["build_contexts"] if b["missing"]]
