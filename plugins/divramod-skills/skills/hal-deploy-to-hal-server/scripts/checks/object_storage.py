"""The app needs object storage, which the server does not offer."""

from checks import finding

SLUG = "object-storage"
WHY = "a container has only tmpfs paths and the server offers no storage yet (plan 0759 Q1), so its files need a hosted bucket"


NAMES = {"STORAGE_DRIVER", "S3_ENDPOINT", "S3_BUCKET"}


def run(ctx):
    found = ctx.get("inspect")
    if found is None or not ("@aws-sdk/client-s3" in found["drivers"] or NAMES & set(found["env_names"])):
        return []
    out = [finding(SLUG, "warn", "the app stores files in object storage and the server offers none: keep the hosted "
                   "bucket (S3_* as secrets, egress on), see references/limits.md (per-app storage)")]
    if "STORAGE_DRIVER" in found["env_names"] and "STORAGE_DRIVER" not in ctx["container"].get("env", {}):
        out.append(finding(SLUG, "warn", "STORAGE_DRIVER is not set in [container.env]: name the driver, its default may "
                           "follow the hosting platform"))
    return out
