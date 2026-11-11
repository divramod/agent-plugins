"""Shared by the tests: a scratch farm repository, a declaration, a fake ssh, hal2's recorded adapt."""

import json
import stat
import tempfile
from pathlib import Path

import hal2

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMiR6IKIUk4JTFP/ukQK48Lt6OsxP0TldBJhlM8osXUj accounter-ci@github"
DIGEST = "sha256:" + "a" * 64
DECLARATION = f'''schema = 1
zone = "divramod-me"
hosts = ["accounter"]
keys = ["{KEY}"]

[container]
image = "ghcr.io/divramod/accounter-web"
port = 3000
health = "/healthcheck"
memory = "512M"
secrets = ["DATABASE_URL"]
writable = ["/tmp"]

[container.env]
NODE_ENV = "production"
'''


BLANK_INSPECT = {"name": "farm", "remote_name": None, "repo": "/farm", "dockerfiles": [], "ports": {}, "docker": {},
                 "health_routes": {}, "health_handlers": {}, "env_files": [], "env_names": [], "platform": "node",
                 "packages": [], "apps": [], "drivers": [], "frameworks": [], "workflows": [], "ci_builds_image": False,
                 "image_candidate": None, "build_contexts": [], "image_refs": [], "deploy_compose": None, "next_configs": [],
                 "vercel": {"deps": [], "env_readers": []}, "truncated": False}


def ctx(container: dict | None = None, inspect: dict | None = None, **extra) -> dict:
    """A check's input: inspect's findings blank but for what the test names."""
    return {"site": "demo", "container": container or {}, "inspect": {**BLANK_INSPECT, **(inspect or {})}, **extra}


def scratch() -> Path:
    return Path(tempfile.mkdtemp(prefix="deploy-skill-test-"))


def repo(tmp: Path, dockerfile="FROM node:22\nEXPOSE 3000\n", env=".env.example") -> Path:
    r = tmp / "farm"
    (r / "src").mkdir(parents=True)
    if dockerfile is not None:
        (r / "Dockerfile").write_text(dockerfile)
    (r / "package.json").write_text(json.dumps({"dependencies": {"astro": "5", "pg": "8"}}))
    (r / "src" / "health.ts").write_text('app.get("/healthcheck", ok)\n')
    (r / ".env.example").write_text("DATABASE_URL=\nNODE_ENV=production\nSTORAGE_DRIVER=s3\n")
    (r / ".env").write_text("REAL_SECRET=never-read\n")
    return r


def declaration(tmp: Path, text=DECLARATION, name="accounter") -> Path:
    path = tmp / f"{name}.toml"
    path.write_text(text)
    return path


def adapted(tmp: Path, case="good") -> str:
    """hal2's recorded `caddy adapt` of a container fixture: the checker replays it, no docker."""
    root = hal2.find_root()
    data = json.loads((root / "code/python/scripts/hal9k-site-check/fixtures/container" / f"{case}.json").read_text())
    path = tmp / f"{case}-adapted.json"
    path.write_text(json.dumps(data["adapted"]))
    return str(path)


def fake_ssh(tmp: Path, stdout: str, code: int) -> Path:
    """A stand-in for ssh: records its argv, prints a status, exits with `code`."""
    script = tmp / "fake-ssh"
    script.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" > '{tmp}/argv'\ncat <<'EOF'\n{stdout}\nEOF\nexit {code}\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script
