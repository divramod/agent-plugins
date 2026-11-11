#!/usr/bin/env python3
"""hal-deploy-to-hal-server: inspect, declare, check, ci-step, status, deploy, learn. Every command takes `--json`.
Exit 0 ok, 1 a problem found or a deploy that did not succeed, 2 a usage or setup error, 3 (deploy, status) no result
within 10 minutes."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ci_step  # noqa: E402
import declare  # noqa: E402
import hal2  # noqa: E402
import inspect_compose  # noqa: E402
import inspect_repo  # noqa: E402
import learn  # noqa: E402
import remote  # noqa: E402

HELP = """/hal-deploy-to-hal-server <command>: put a farm's container app on the hal9k server, code first.
  inspect <repo>                  read-only findings: Dockerfile, port, health route, env names, drivers
  declare --site S --zone Z [--repo R] ...   the site's TOML as a draft, from the farm's deploy compose file when it has one (stdout, or --out <path>; --into-sites after the user's go)
  check --declaration <toml> [--repo <repo>]   hal2's validation, the route through hal9k-site-check, every check
  ci-step --site S --image I [--context C --file F --build-arg N]   the CI steps for the farm: publish the image, then `deploy sha256:<digest>`
  status --site S --key K --known-hosts F      the server's last deploy status
  deploy --site S --digest D --key K --known-hosts F --go   one digest; --go only after the user's yes
  learn <slug> [--problem T] [--brief]         a new problem becomes a check with its test (SKILL.md, A new problem)
Every command takes --json. h or help prints this."""


def emit(args, data, text: str) -> None:
    print(json.dumps(data, indent=2, sort_keys=True) if args.json else text)


def die(args, message: str, code: int = 2) -> int:
    if getattr(args, "json", False):
        print(json.dumps({"error": message}))
    else:
        print(f"hal-deploy-to-hal-server: {message}", file=sys.stderr)
    return code


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hal-deploy-to-hal-server", add_help=False)
    sub = p.add_subparsers(dest="cmd")
    for name in ("h", "help"):
        sub.add_parser(name)

    def add(name):
        s = sub.add_parser(name)
        s.add_argument("--json", action="store_true")
        return s

    add("inspect").add_argument("repo")
    d = add("declare")
    for flag in ("--site", "--zone", "--image", "--health", "--memory", "--max-body", "--max-image", "--out", "--repo", "--compose-service"):
        d.add_argument(flag)
    d.add_argument("--host", action="append", default=[])
    d.add_argument("--key", action="append", default=[], help="a public ssh key line")
    d.add_argument("--secret", action="append", default=[])
    d.add_argument("--env", action="append", default=[], help="NAME=value")
    d.add_argument("--writable", action="append", default=[])
    d.add_argument("--port", type=int)
    d.add_argument("--cpus", type=float, default=1.0)
    d.add_argument("--no-egress", action="store_true")
    d.add_argument("--into-sites", action="store_true")
    c = add("check")
    c.add_argument("--declaration", required=True)
    c.add_argument("--repo")
    c.add_argument("--adapted", help="the adapted Caddy JSON instead of running docker (tests)")
    c.add_argument("--image", help="the Caddy image")
    s = add("ci-step")
    s.add_argument("--site", required=True)
    s.add_argument("--image", required=True)
    s.add_argument("--context", default=".", help="the image build's context, for an app in a subfolder")
    s.add_argument("--file", default="Dockerfile", help="the Dockerfile's path")
    s.add_argument("--build-arg", action="append", default=[], help="a build-time name, e.g. NEXT_PUBLIC_API_URL")
    s.add_argument("--repo", help="the farm's repository: git secret or the plain form")
    for name in ("status", "deploy"):
        r = add(name)
        r.add_argument("--site", required=True)
        r.add_argument("--key", required=True)
        r.add_argument("--known-hosts", required=True)
        r.add_argument("--ssh", default="ssh")
    sub.choices["deploy"].add_argument("--digest", required=True)
    sub.choices["deploy"].add_argument("--go", action="store_true")
    ln = add("learn")
    ln.add_argument("slug")
    ln.add_argument("--problem", default="")
    ln.add_argument("--brief", action="store_true")
    return p


def cmd_inspect(a) -> int:
    try:
        found = inspect_repo.inspect(Path(a.repo))
    except FileNotFoundError as err:
        return die(a, str(err))
    emit(a, found, f"{found['repo']}: dockerfiles {found['dockerfiles'] or 'none'}, ports {found['ports']}, "
         f"health {list(found['health_routes']) or 'none'}, env {found['env_names']}, drivers {found['drivers']}, "
         f"platform {found['platform']}")
    return 0


def compare_existing(a, compose) -> int:
    """`declare --repo R --out <existing>`: the table on disk against the compose file; nothing is written."""
    table = tomllib.loads(Path(a.out).read_text()).get("container", {})
    differ = inspect_compose.compare(inspect_compose.pick(compose, table.get("image"), a.compose_service)[1], table)
    emit(a, {"compared": a.out, "mismatches": differ}, "\n".join(differ) or f"{a.out} matches {compose['path']}")
    return 1 if differ else 0


def cmd_declare(a) -> int:
    try:
        env = dict(item.split("=", 1) for item in a.env)
    except ValueError:
        return die(a, "--env is NAME=value")
    compose = inspect_compose.load(Path(a.repo)) if a.repo else None
    secrets = a.secret
    if compose:
        try:
            if a.out and Path(a.out).exists():
                return compare_existing(a, compose)
            given = {"image": a.image, "port": a.port, "memory": a.memory, "env": env, "secrets": secrets}
            merged, differ = declare.merge_compose(given, compose, a.compose_service)
        except (ValueError, OSError) as err:
            return die(a, str(err))
        if differ:
            return die(a, f"{compose['path']} says otherwise: {'; '.join(differ)}", 1)
        a.image, a.port, a.memory, env, secrets = (merged["image"], merged["port"], merged["memory"], merged["env"],
                                                   merged["secrets"])
    need = {"--site": a.site, "--zone": a.zone, "--image": a.image, "--port": a.port, "--health": a.health,
            "--memory": a.memory, "--host": a.host, "--key": a.key}
    missing = [k for k, v in need.items() if not v]
    if missing:
        return die(a, f"declare needs {', '.join(missing)}")
    text = declare.render({"site": a.site, "zone": a.zone, "hosts": a.host, "keys": a.key, "image": a.image,
                           "port": a.port, "health": a.health, "memory": a.memory, "cpus": a.cpus,
                           "egress": not a.no_egress, "max_body": a.max_body, "max_image": a.max_image,
                           "secrets": secrets, "env": env,
                           "writable": a.writable})
    if not a.out:
        emit(a, {"draft": text}, text.rstrip("\n"))
        return 0
    try:
        root = hal2.find_root()
    except hal2.NoHal2:
        root = None
    try:
        path = declare.write(text, Path(a.out), root, a.into_sites)
    except (PermissionError, FileExistsError, OSError) as err:
        return die(a, str(err))
    emit(a, {"written": str(path)}, f"wrote {path}")
    return 0


def cmd_check(a) -> int:
    try:
        root = hal2.find_root()
    except hal2.NoHal2 as err:
        return die(a, str(err))
    import check_decl
    result = check_decl.check(Path(a.declaration), root, Path(a.repo) if a.repo else None, a.adapted, a.image)
    lines = [f"validation: {'ok' if result['validation']['ok'] else result['validation'].get('error')}"]
    if result["route"]:
        lines.append(f"route: {result['route']['verdict']} {result['route'].get('error', '')}".rstrip())
        lines += [f"  {r['rule']}: {r['detail']}" for r in result["route"]["reasons"]]
    lines += [f"{f['severity']} {f['check']}: {f['detail']}" for f in result["findings"]]
    emit(a, result, "\n".join(lines) + f"\nok: {result['ok']}")
    return 0 if result["ok"] else 1


def cmd_ci_step(a) -> int:
    try:
        text = ci_step.render(a.site, a.image, a.context, a.file, a.build_arg, Path(a.repo) if a.repo else None)
    except ValueError as err:
        return die(a, str(err))
    emit(a, {"site": a.site, "steps": text}, text.rstrip("\n"))
    return 0


def cmd_remote(a) -> int:
    try:
        if a.cmd == "deploy":
            out = remote.deploy(a.site, a.digest, Path(a.key), Path(a.known_hosts), a.go, a.ssh)
        else:
            out = remote.status(a.site, Path(a.key), Path(a.known_hosts), a.ssh)
    except (PermissionError, ValueError) as err:
        return die(a, str(err))
    text = f"{out['outcome']}: {out['meaning']}" + ("\nTELL THE USER NOW" if out["tell_user_now"] else "")
    emit(a, out, text)
    return out["exit"]


def cmd_learn(a) -> int:
    try:
        if a.brief:
            text = learn.brief(a.slug, a.problem)
            emit(a, {"brief": text}, text)
            return 0
        try:
            hal2.find_root()
        except hal2.NoHal2:
            return die(a, "outside hal2 this skill cannot change itself: use `learn <slug> --brief` for hal2's farmer")
        files = learn.scaffold(a.slug, a.problem)
    except (ValueError, FileExistsError) as err:
        return die(a, str(err))
    emit(a, {"written": files}, "scaffolded:\n" + "\n".join(files) + "\nwrite the test, then the check, until green")
    return 0


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    if a.cmd in (None, "h", "help"):
        print(HELP)
        return 0
    handler = {"inspect": cmd_inspect, "declare": cmd_declare, "check": cmd_check, "ci-step": cmd_ci_step,
               "status": cmd_remote, "deploy": cmd_remote, "learn": cmd_learn}[a.cmd]
    return handler(a)


if __name__ == "__main__":
    sys.exit(main())
