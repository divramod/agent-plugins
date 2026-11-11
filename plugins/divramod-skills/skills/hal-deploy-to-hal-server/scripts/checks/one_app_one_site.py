"""The repository holds several deployable apps; a site is one container."""

from checks import finding

SLUG = "one-app-one-site"
WHY = "one site is one container on one image, so a second app is a second site with its own declaration and key"


def run(ctx):
    found = ctx.get("inspect")
    if found is None or len(found["apps"]) < 2:
        return []
    return [finding(SLUG, "warn", f"{len(found['apps'])} apps in this repository ({', '.join(found['apps'])}): a site is "
                    f"one of them; this declaration ({ctx['site']}) covers one, each other app needs its own site")]
