"""`declare`: a site's TOML as a draft. It goes to stdout or to a named path; the real `sites/` folder only with
`--into-sites` (the user's go), and an existing file is never overwritten."""

from __future__ import annotations

import json
from pathlib import Path

import hal2
import inspect_compose


def _s(value: str) -> str:
    return json.dumps(value)  # a TOML basic string: JSON's escapes are TOML's


def render(a: dict) -> str:
    lines = [f"# {a['site']}: a container site on the hal9k server (drafted by hal-deploy-to-hal-server).",
             "schema = 1", f"zone = {_s(a['zone'])}", "hosts = [" + ", ".join(_s(h) for h in a["hosts"]) + "]",
             "keys = [" + ", ".join(_s(k) for k in a["keys"]) + "]", "", "[container]",
             f"image = {_s(a['image'])}", f"port = {a['port']}", f"health = {_s(a['health'])}",
             f"memory = {_s(a['memory'])}", f"cpus = {a['cpus']}", f"egress = {'true' if a['egress'] else 'false'}"]
    if a.get("max_body"):
        lines.append(f"max_body = {_s(a['max_body'])}")
    if a.get("max_image"):
        lines.append(f"max_image = {_s(a['max_image'])}")
    lines.append("secrets = [" + ", ".join(_s(s) for s in a.get("secrets", [])) + "]")
    lines.append("writable = [" + ", ".join(_s(w) for w in a.get("writable", [])) + "]")
    if a.get("env"):
        lines += ["", "[container.env]"] + [f"{k} = {_s(v)}" for k, v in sorted(a["env"].items())]
    return "\n".join(lines) + "\n"


def merge_compose(given: dict, compose: dict, service: str | None) -> tuple[dict, list[str]]:
    """`given` filled from the compose service; a flag that contradicts it is returned as a mismatch, never preferred."""
    derived = inspect_compose.derive(inspect_compose.pick(compose, given.get("image"), service)[1])
    merged, differ = dict(given), []
    for field in ("image", "port", "memory"):
        if merged.get(field) in (None, ""):
            merged[field] = derived[field]
        elif derived[field] is not None and merged[field] != derived[field]:
            differ.append(f"{field}: compose {derived[field]}, flag {merged[field]}")
    if not merged.get("env") and not merged.get("secrets"):
        merged["env"], merged["secrets"] = derived["env"], derived["secrets"]
    else:
        named, known = set(merged.get("env") or {}) | set(merged.get("secrets") or []), set(derived["env"]) | set(derived["secrets"])
        if named != known:
            differ.append(f"env names: compose {sorted(known)}, flags {sorted(named)}")
    return merged, differ


def write(text: str, out: Path, root: Path | None, into_sites: bool) -> Path:
    out = Path(out)
    if root is not None and out.resolve().parent == (root / hal2.SITES_DIR).resolve() and not into_sites:
        raise PermissionError("that is the real sites folder: only with --into-sites, after the user's go")
    if out.exists():
        raise FileExistsError(f"{out} exists: never overwritten")
    out.write_text(text)
    return out
