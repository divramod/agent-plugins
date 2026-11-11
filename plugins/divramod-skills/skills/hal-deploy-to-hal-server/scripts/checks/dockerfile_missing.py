"""The repository has no Dockerfile: there is no image to deploy."""

from checks import finding

SLUG = "dockerfile-missing"
WHY = "a container site deploys an image; without a Dockerfile the farm has none to build"


def run(ctx):
    found = ctx.get("inspect")
    if found is None or found["dockerfiles"]:
        return []
    return [finding(SLUG, "error", "no Dockerfile in the repository: write one (the image runs as a non-root user) "
                    "before declaring the site")]
