"""A name in `.env.example` is neither an `env` value nor a `secrets` name of the declaration."""

from checks import finding
from checks.build_time_env import is_build_time

SLUG = "undeclared-env"
WHY = "the container only gets what the declaration names; a missing variable fails at runtime, not at deploy"


def run(ctx):
    found = ctx.get("inspect")
    if found is None:
        return []
    container = ctx["container"]
    declared = set(container.get("env", {})) | set(container.get("secrets", []))
    missing = sorted(n for n in set(found["env_names"]) - declared if not is_build_time(n))
    if not missing:
        return []
    return [finding(SLUG, "warn", f".env.example names {missing}, not in [container] env or secrets: "
                    "declare each as a value or a secret (or say it is unused)")]
