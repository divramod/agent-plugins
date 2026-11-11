"""The declared port is not one the Dockerfile exposes."""

from checks import finding

SLUG = "port-mismatch"
WHY = "the proxy dials the declared port; an image listening elsewhere never passes its health check"


def run(ctx):
    found = ctx.get("inspect")
    if found is None:
        return []
    exposed = sorted({p for ports in found["ports"].values() for p in ports})
    port = ctx["container"].get("port")
    if not exposed or port in exposed:
        return []
    return [finding(SLUG, "warn", f"declared port {port}, the Dockerfile exposes {exposed}")]
