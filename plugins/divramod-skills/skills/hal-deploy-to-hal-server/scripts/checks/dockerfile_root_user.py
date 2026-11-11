"""The final stage has no USER: the app runs as root inside the container."""

from checks import finding

SLUG = "dockerfile-root-user"
WHY = "the container drops every capability, but a process of root owns what it can reach and a non-root user costs one line"


def run(ctx):
    found = ctx.get("inspect")
    if found is None:
        return []
    root = sorted(name for name, facts in found["docker"].items() if facts["user"] in (None, "root", "0"))
    if not root:
        return []
    return [finding(SLUG, "warn", f"{root} set no USER in the final stage: add a non-root user (on node images, `USER node`)")]
