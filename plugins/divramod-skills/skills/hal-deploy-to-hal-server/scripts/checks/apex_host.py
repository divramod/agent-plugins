"""The app lives on the zone's apex, which hal9k refuses."""

from checks import finding

SLUG = "apex-host"
WHY = "the zone's apex and its server stay untouched (plan 0759 D14), so the app gets a subdomain or stays where it is"


def norm(name: str) -> str:
    return name.lower().replace(".", "-")


def run(ctx):
    hosts, domain, found = ctx.get("hosts") or [], ctx.get("domain"), ctx.get("inspect")
    if "@" in hosts:
        return [finding(SLUG, "error", f"the apex of {domain or 'the zone'} is refused (plan 0759 D14): declare a subdomain")]
    if found is None or not domain:
        return []
    if norm(domain) not in {norm(found["name"]), norm(found["remote_name"] or "")}:
        return []
    return [finding(SLUG, "warn", f"this repository is the site {domain}, whose apex hal9k refuses (D14): this declaration "
                    f"serves {[f'{h}.{domain}' for h in hosts]}, the apex stays on its own server")]
