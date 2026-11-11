"""Names inlined at build time cannot be set on the container."""

from checks import finding

SLUG = "build-time-env"
WHY = "NEXT_PUBLIC_, VITE_ and PUBLIC_ values are compiled into the bundle, so the container's env never reaches them"


PREFIXES = ("NEXT_PUBLIC_", "VITE_", "PUBLIC_")


def is_build_time(name: str) -> bool:
    return name.startswith(PREFIXES)


def run(ctx):
    found, container = ctx.get("inspect"), ctx["container"]
    declared = sorted(n for n in set(container.get("env", {})) | set(container.get("secrets", [])) if is_build_time(n))
    if declared:
        return [finding(SLUG, "error", f"{declared} are inlined at build time: as container env they do nothing; make them "
                        "the image build's build-args (`ci-step --build-arg`)")]
    needed = sorted(n for n in (found or {}).get("env_names", []) if is_build_time(n))
    if not needed:
        return []
    return [finding(SLUG, "warn", f"{needed} are inlined at build time: pass them as the image build's build-args "
                    "(`ci-step --build-arg`), never as a declared env or secret")]
