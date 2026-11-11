"""The farm's deploy compose file and the `[container]` table disagree."""

import inspect_compose
from checks import finding

SLUG = "deploy-content"
WHY = "the compose file is the app's one description and the engine runs the [container] table: the two must say the same"


def run(ctx):
    compose = (ctx.get("inspect") or {}).get("deploy_compose")
    if not compose:
        return []
    try:
        name, service = inspect_compose.pick(compose, ctx["container"].get("image"))
    except ValueError as err:
        return [finding(SLUG, "error", str(err))]
    differ = inspect_compose.compare(service, ctx["container"])
    if not differ:
        return []
    return [finding(SLUG, "error", f"{compose['path']} service {name} and the [container] table differ: {'; '.join(differ)}")]
