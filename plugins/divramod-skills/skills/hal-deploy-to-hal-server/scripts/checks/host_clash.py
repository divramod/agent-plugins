"""A host of this declaration is already served by another declared site."""

from checks import finding

SLUG = "host-clash"
WHY = "two declarations of one host make the apply quarantine a route and retry it on its 5-minute timer"


def run(ctx):
    mine, out = ctx.get("hosts") or [], []
    for other in ctx.get("other_sites") or []:
        shared = sorted(set(mine) & set(other["hosts"])) if other["zone"] == ctx.get("zone") else []
        if shared:
            kind = "static site" if other["static"] else "site"
            out.append(finding(SLUG, "error", f"{shared} already served by the {kind} {other['name']}: move each in one "
                               f"commit (remove it from {other['name']}.toml and add it here together), never a window "
                               "with two declarations of one host"))
    return out
