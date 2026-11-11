"""`inspect <repo>`: read-only findings about a farm's repository, as data. It reads files, runs nothing, writes nothing,
and never reads a real `.env` (only `.env.example` and `.env.sample`)."""

from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path

import inspect_app
import inspect_compose
import inspect_docker

SCHEMA = 1
# Build output and a farm's own planning trees: never part of an image, and a farm's plans outnumber its code.
SKIP = {".git", "node_modules", "dist", "build", ".next", ".astro", "target", "__pycache__", ".venv", ".turbo",
        ".react-router", ".vercel", ".cache", "coverage", ".planning", "plans", "research", "shotfiles", "daybook",
        "transcripts"}
MAX_FILES, MAX_BYTES, MAX_DEPTH = 20_000, 200_000, 16
ENV_EXAMPLES = {".env.example", ".env.sample", ".env.production.example"}
HEALTH = re.compile(r"""["'`](/(?:api/)?(?:healthz?|healthcheck|health-check|ready|readyz|up)(?:/[a-z]+)?)["'`]""")
DRIVERS = ("pg", "postgres", "@neondatabase/serverless", "@supabase/supabase-js", "prisma", "drizzle-orm", "mysql2",
           "mongodb", "redis", "ioredis", "@aws-sdk/client-s3", "better-sqlite3")
FRAMEWORKS = ("next", "astro", "@vercel/react-router", "react-router", "express", "fastify", "hono", "nuxt", "vite")
ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=", re.M)
REMOTE = re.compile(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?\s*$", re.M)


def walk(root: Path):
    """Breadth first: when the cap ends the walk, what sits near the root (`.github`, a Dockerfile) was seen."""
    count = 0
    queue = deque([(root, 0)])
    while queue:
        folder, depth = queue.popleft()
        try:
            entries = sorted(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.name in SKIP or entry.is_symlink():
                continue
            if entry.is_dir():
                if depth < MAX_DEPTH:
                    queue.append((entry, depth + 1))
            elif entry.is_file():
                count += 1
                if count > MAX_FILES:
                    return
                yield entry


def read(path: Path) -> str:
    try:
        return path.read_text(errors="ignore")[:MAX_BYTES]
    except OSError:
        return ""


def _packages(files: list[Path], root: Path) -> list[dict]:
    packages = []
    for f in files:
        if f.name == "package.json":
            try:
                data = json.loads(read(f))
                deps = sorted(set(data.get("dependencies", {})) | set(data.get("devDependencies", {})))
            except (ValueError, AttributeError, TypeError):
                continue
            packages.append({"path": str(f.parent.relative_to(root)), "deps": deps,
                             "frameworks": sorted(d for d in FRAMEWORKS if d in deps)})
    return packages


def _package(packages: list[dict]) -> dict:
    deps = {d for p in packages for d in p["deps"]}
    return {"packages": [p["path"] for p in packages], "drivers": sorted(d for d in DRIVERS if d in deps),
            "frameworks": sorted(d for d in FRAMEWORKS if d in deps), "apps": inspect_app.apps(packages)}


def inspect(repo: Path) -> dict:
    root = Path(repo)
    if not root.is_dir():
        raise FileNotFoundError(f"{repo} is not a folder")
    files = list(walk(root))
    rel = lambda f: str(f.relative_to(root))  # noqa: E731
    dockerfiles = sorted(rel(f) for f in files if f.name == "Dockerfile" or f.name.startswith("Dockerfile."))
    docker = {name: inspect_docker.dockerfile_facts(read(root / name)) for name in dockerfiles}
    handlers = inspect_app.health_handlers(files, root, read)
    health: dict[str, list[str]] = {route: list(h["files"]) for route, h in handlers.items()}
    for f in files:
        if f.suffix in {".ts", ".tsx", ".js", ".mjs", ".py", ".go", ".rs", ".astro", ".yml", ".yaml", ".json"}:
            if not inspect_app.is_test(rel(f)):
                for route in HEALTH.findall(read(f)):
                    health.setdefault(route, []).append(rel(f))
    env_names: set[str] = set()
    env_files = []
    for f in files:
        if f.name in ENV_EXAMPLES:
            env_files.append(rel(f))
            env_names |= set(ENV_LINE.findall(read(f)))
    # Read from their folder, not the walk: the cap can end the walk in a big tree before them.
    workflows = sorted(rel(f) for f in (root / ".github/workflows").glob("*") if f.suffix in {".yml", ".yaml"})
    builds_image = any("build-push-action" in read(root / w) or "docker build" in read(root / w) for w in workflows)
    platform = "node" if (root / "package.json").is_file() or any(f.name == "package.json" for f in files) else None
    for marker, name in (("pyproject.toml", "python"), ("Cargo.toml", "rust"), ("go.mod", "go")):
        if platform is None and any(f.name == marker for f in files):
            platform = name
    owner = REMOTE.search(read(root / ".git" / "config")) if (root / ".git").is_dir() else None
    image = f"ghcr.io/{owner[1].lower()}/{owner[2].lower()}" if owner else None
    packages = _packages(files, root)
    return {"schema": SCHEMA, "repo": str(root), "name": root.resolve().name, "remote_name": owner[2] if owner else None,
            "dockerfiles": dockerfiles, "ports": {name: facts["ports"] for name, facts in docker.items()}, "docker": docker,
            "health_routes": {k: sorted(set(v)) for k, v in sorted(health.items())}, "health_handlers": handlers,
            "env_files": env_files, "env_names": sorted(env_names), "platform": platform, **_package(packages),
            "workflows": workflows, "ci_builds_image": builds_image, "image_candidate": image,
            "build_contexts": inspect_docker.build_contexts(root, workflows, read),
            "image_refs": inspect_docker.image_refs(files, root, read), "deploy_compose": inspect_compose.load(root),
            "next_configs": inspect_app.next_configs(files, root, read),
            "vercel": inspect_app.vercel_signs(packages, files, root, read), "truncated": len(files) >= MAX_FILES}
