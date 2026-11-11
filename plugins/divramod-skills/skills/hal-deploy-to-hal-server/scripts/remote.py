"""`status` and `deploy` over a site's forced key, and what every engine verdict means for the user.

The server's forced command (code/python/scripts/hal9k-site-deploy-linux/forced.py) allows only `deploy sha256:<64
hex>` and `status`; exit 0 deployed or unchanged, 1 kept-previous, refused or failed, 2 usage, 3 no result within 10
minutes (the deploy goes on, `status` reads it later)."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

HOST = "hal9k.app"
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
SITE = re.compile(r"[a-z0-9-]+")
WAIT_SECONDS = 600 + 30

# verdict -> (outcome, tell the user at once, what it means)
VERDICTS = {
    "deployed": ("success", False, "the new container serves; the old one and unused images are removed"),
    "unchanged": ("success", False, "this digest already serves; nothing changed"),
    "kept-previous": ("kept-previous", False, "the candidate failed and was removed; the previous container still "
                      "serves; read reasons[] (pull, start, health, cutover, verify) and fix that"),
    "refused": ("refused", False, "the server refused before touching anything; reasons[] says which rule"),
    "failed": ("failed", True, "THE OLD CONTAINER DID NOT RESTART: the candidate is left up and may serve; tell the "
               "user now, do not retry, the server needs a person"),
}


def classify(status: dict | None, exit_code: int) -> dict:
    """What a status (the JSON the forced command printed) and its exit code mean."""
    if exit_code == 3:
        return {"outcome": "pending", "tell_user_now": False, "ok": False, "exit": 3,
                "meaning": "no result within 10 minutes: the deploy goes on; run `status` later and judge then"}
    if exit_code == 2 or not status:
        return {"outcome": "usage" if exit_code == 2 else "no-status", "tell_user_now": False, "ok": False,
                "exit": exit_code or 1, "meaning": "the server accepted no such command, or sent no status"}
    verdict = status.get("verdict")
    outcome, urgent, meaning = VERDICTS.get(verdict, ("unknown", True, f"verdict {verdict!r} is new: read the status"))
    return {"outcome": outcome, "verdict": verdict, "tell_user_now": urgent, "ok": outcome == "success",
            "exit": 0 if outcome == "success" else 1, "meaning": meaning, "reasons": status.get("reasons", []),
            "digest": status.get("digest"), "previous": status.get("previous")}


def ssh_argv(site: str, key: Path, known_hosts: Path, command: str, ssh: str = "ssh") -> list[str]:
    return [ssh, "-i", str(key), "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={known_hosts}",
            "-o", "BatchMode=yes", f"hal9k-site-{site}@{HOST}", command]


def call(site: str, key: Path, known_hosts: Path, command: str, ssh: str = "ssh", timeout: int = WAIT_SECONDS) -> dict:
    if not SITE.fullmatch(site):
        raise ValueError("a site name is [a-z0-9-]+")
    try:
        proc = subprocess.run(ssh_argv(site, key, known_hosts, command, ssh), capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return classify(None, 3)
    status = None
    for line in reversed(proc.stdout.splitlines()):
        try:
            status = json.loads(line)
            break
        except ValueError:
            continue
    out = classify(status, proc.returncode)
    if proc.returncode == 255:
        out.update(outcome="ssh-error", meaning="ssh itself failed (key, host key, network): "
                   + proc.stderr.strip()[-200:])
    return out


def deploy(site: str, digest: str, key: Path, known_hosts: Path, go: bool, ssh: str = "ssh") -> dict:
    """One digest. Refused without the user's go: nothing is run."""
    if not go:
        raise PermissionError("a real deploy needs the user's go: ask, then run again with --go")
    if not DIGEST.fullmatch(digest):
        raise ValueError("the digest is sha256: and 64 lowercase hex characters")
    return call(site, key, known_hosts, f"deploy {digest}", ssh)


def status(site: str, key: Path, known_hosts: Path, ssh: str = "ssh") -> dict:
    return call(site, key, known_hosts, "status", ssh)
