"""What `inspect` reads about a repository's apps: file-based health routes and what their handlers depend on, the
deployable apps of a monorepo, Next.js's output mode and the signs of a build made for Vercel."""

from __future__ import annotations

import re
from pathlib import Path

HEALTH_PATH = re.compile(r"/(?:api/)?(?:healthz?|healthcheck|health-check|ready|readyz|up)(?:/[a-z]+)?")
ROUTE_ROOTS = ("routes", "pages", "app")
CODE = {".ts", ".tsx", ".js", ".mjs", ".astro"}
TEST_FILE = re.compile(r"(\.|/)(test|spec)\.[a-z]+$|(^|/)(tests?|__tests__|e2e)/")
DATABASE = re.compile(r"database|\bdb\b|\bsql\b|supabase|prisma|drizzle", re.I)
UNAVAILABLE = re.compile(r"\b503\b")
RATE_LIMIT = re.compile(r"rate.?limit|limiter|limitHealth|\b429\b", re.I)
NEXT_CONFIG = re.compile(r"next\.config\.[a-z]+$")
STANDALONE = re.compile(r"""output\s*:\s*["']standalone["']""")
VERCEL_DEPS = ("@vercel/react-router", "@astrojs/vercel", "@sveltejs/adapter-vercel", "@vercel/remix")
VERCEL_ENV = re.compile(r"\bVERCEL_ENV\b")


def is_test(rel: str) -> bool:
    return TEST_FILE.search(rel) is not None


def route_of(rel: str) -> str | None:
    """The URL a file-based router (Next, Astro, React Router) serves this file at, or None."""
    path = Path(rel)
    if path.suffix not in CODE:
        return None
    parts = list(path.with_suffix("").parts)
    for root in ROUTE_ROOTS:
        if root in parts:
            segments = parts[len(parts) - 1 - parts[::-1].index(root) + 1:]
            break
    else:
        return None
    segments = [s for s in segments if not s.startswith("(")]
    if segments[-1:] in (["route"], ["index"]):
        segments = segments[:-1]
    route = "/" + "/".join(segments)
    return route if HEALTH_PATH.fullmatch(route) else None


def health_handlers(files: list[Path], root: Path, read) -> dict:
    """Per health route the files serving it and what they depend on; comments count, they say what the handler checks."""
    found: dict[str, dict] = {}
    for f in files:
        rel = str(f.relative_to(root))
        route = None if is_test(rel) else route_of(rel)
        if route is None:
            continue
        text = read(f)
        entry = found.setdefault(route, {"files": [], "database": False, "status_503": False, "rate_limited": False})
        entry["files"].append(rel)
        entry["database"] |= DATABASE.search(text) is not None
        entry["status_503"] |= UNAVAILABLE.search(text) is not None
        entry["rate_limited"] |= RATE_LIMIT.search(text) is not None
    return dict(sorted(found.items()))


def apps(packages: list[dict]) -> list[str]:
    """The packages under an `apps` folder that a web framework serves: each would be one container."""
    return sorted(p["path"] for p in packages if "apps" in Path(p["path"]).parts and p["frameworks"])


def next_configs(files: list[Path], root: Path, read) -> list[dict]:
    return [{"path": str(f.relative_to(root)), "standalone": STANDALONE.search(read(f)) is not None}
            for f in files if NEXT_CONFIG.fullmatch(f.name)]


def vercel_signs(packages: list[dict], files: list[Path], root: Path, read) -> dict:
    """The Vercel build dependencies, and the non-test sources that read VERCEL_ENV at runtime."""
    deps = sorted({d for p in packages for d in p["deps"] if d in VERCEL_DEPS})
    readers = sorted(str(f.relative_to(root)) for f in files
                     if f.suffix in {".ts", ".tsx", ".js", ".mjs"} and not f.name.endswith(".d.ts")
                     and not is_test(str(f.relative_to(root))) and VERCEL_ENV.search(read(f)))
    return {"deps": deps, "env_readers": readers}
