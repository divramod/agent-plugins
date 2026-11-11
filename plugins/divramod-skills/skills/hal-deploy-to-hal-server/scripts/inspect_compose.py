"""The farm's deploy description: `utils/docker-compose/deploy/remote-hub/docker-compose.yml` (steueragenten plan 0760). The
engine starts the container, never compose; this file is only read, so `declare` derives from it and `check` proves the
`[container]` table against it (`deploy-content`). Stdlib only: an indentation reader for the blocks compose files use."""

from __future__ import annotations

import re
from pathlib import Path

PATH = "utils/docker-compose/deploy/remote-hub/docker-compose.yml"
KEY = re.compile(r"""^(?P<key>[A-Za-z0-9_.<-]+|"[^"]+"|'[^']+')\s*:(?:\s+(?P<value>.*))?$""")
FROM_OUTSIDE = re.compile(r"^\$\{?[A-Za-z_][A-Za-z0-9_]*(?:[:?-][^}]*)?\}?$")
MEMORY = re.compile(r"^([1-9][0-9]*)\s*([kKmMgG])[bB]?$")
UNITS = {"K": 1024, "M": 1024**2, "G": 1024**3}


QUOTED = re.compile(r"""^(['"])(.*?)\1\s*(?:#.*)?$""")


def _clean(text: str) -> str:
    return text.strip() if QUOTED.match(text.strip()) else re.sub(r"(^|\s)#.*$", "", text).strip()


def _scalar(text: str | None):
    text = "" if text is None else _clean(text)
    quoted = QUOTED.match(text)
    return quoted[2] if quoted else (text or None)


def _lines(text: str) -> list[tuple[int, str]]:
    out = []
    for raw in text.splitlines():
        body = raw.lstrip()
        if body and not body.startswith("#") and body != "---":
            out.append((len(raw) - len(body), body))
    return out


def _block(lines: list[tuple[int, str]], start: int, indent: int):
    """The block at `indent`: a list or a map; a line neither (a `|` scalar's text) is skipped."""
    if lines[start][1].startswith("- "):
        items, i = [], start
        while i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("- "):
            body = lines[i][1][2:].strip()
            m = KEY.match(body) if not body.startswith(("'", '"')) else None
            items.append({_scalar(m["key"]): _scalar(m["value"])} if m else _scalar(body))
            i += 1
            while i < len(lines) and lines[i][0] > indent:
                if isinstance(items[-1], dict) and (m := KEY.match(lines[i][1])):
                    items[-1][_scalar(m["key"])] = _scalar(m["value"])
                i += 1
        return items, i
    found, i = {}, start
    while i < len(lines) and lines[i][0] >= indent:
        level, body = lines[i]
        m = KEY.match(body) if level == indent else None
        i += 1
        if m is None:
            continue
        key, value = _scalar(m["key"]), m["value"]
        if value is not None and _clean(value) and not _clean(value).startswith(("|", ">")):
            found[key] = _scalar(value)
        elif i < len(lines) and lines[i][0] > indent and not (value and _clean(value)):
            found[key], i = _block(lines, i, lines[i][0])
        elif i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("- "):
            found[key], i = _block(lines, i, indent)  # a list at its key's own indent, as YAML allows
        else:
            found[key] = None
    return found, i


def _image(value) -> str | None:
    if not isinstance(value, str):
        return None
    head, _, last = value.rpartition("/")
    name = re.split(r"[@:]", last, maxsplit=1)[0]
    return None if "$" in head or "$" in name or not head else f"{head}/{name}"


def _port(service: dict) -> int | None:
    for item in [*(service.get("ports") or []), *(service.get("expose") or [])]:
        text = str(item.get("target")) if isinstance(item, dict) else str(item)
        last = text.rsplit(":", 1)[-1].split("/")[0]
        if last.isdigit():
            return int(last)
    return None


def _env(service: dict) -> dict:
    raw = service.get("environment") or {}
    pairs = raw.items() if isinstance(raw, dict) else [(*str(e).split("=", 1), None)[:2] for e in raw]
    return {name: (None if value is None or FROM_OUTSIDE.match(str(value)) else str(value)) for name, value in pairs}


def _memory(service: dict) -> str | None:
    limits = ((service.get("deploy") or {}).get("resources") or {}).get("limits") or {}
    m = MEMORY.match(str(limits.get("memory") or service.get("mem_limit") or ""))
    return f"{m[1]}{m[2].upper()}" if m else None


def parse(text: str) -> dict:
    """Per service what a site needs; an env name with no literal value comes from outside, so it is a secret."""
    lines = _lines(text)
    tree = _block(lines, 0, lines[0][0])[0] if lines else {}
    services = tree.get("services") if isinstance(tree, dict) else None
    return {name: {"image": _image(s.get("image")), "port": _port(s), "env": _env(s), "memory": _memory(s)}
            for name, s in (services or {}).items() if isinstance(s, dict)}


def load(repo: Path) -> dict | None:
    path = Path(repo) / PATH
    if not path.is_file():
        return None
    return {"path": PATH, "services": parse(path.read_text(errors="ignore"))}


def pick(compose: dict, image: str | None = None, name: str | None = None) -> tuple[str, dict]:
    """The service meant: by name, by the declared image, or the only one; ValueError names the choices."""
    services = compose["services"]
    if name:
        if name not in services:
            raise ValueError(f"{compose['path']} has no service {name!r}: {sorted(services)}")
        return name, services[name]
    matching = [n for n, s in services.items() if image and s["image"] == image]
    candidates = matching or sorted(services)
    if len(candidates) != 1:
        raise ValueError(f"{compose['path']}: name one service with --compose-service: {sorted(services)}")
    return candidates[0], services[candidates[0]]


def derive(service: dict) -> dict:
    """What `declare` takes from the service; None where the file says nothing."""
    return {"image": service["image"], "port": service["port"], "memory": service["memory"],
            "env": {k: v for k, v in service["env"].items() if v is not None},
            "secrets": sorted(k for k, v in service["env"].items() if v is None)}


def _bytes(size) -> int | None:
    m = MEMORY.match(str(size or ""))
    return int(m[1]) * UNITS[m[2].upper()] if m else None


def compare(service: dict, container: dict) -> list[str]:
    """Each disagreement between the compose service and a `[container]` table, in words; a side that is silent passes."""
    out = []
    for field, theirs, ours in (("image", service["image"], container.get("image")),
                                ("port", service["port"], container.get("port"))):
        if theirs is not None and ours is not None and theirs != ours:
            out.append(f"{field}: compose {theirs}, [container] {ours}")
    if service["memory"] and container.get("memory") and _bytes(service["memory"]) != _bytes(container["memory"]):
        out.append(f"memory: compose {service['memory']}, [container] {container['memory']}")
    declared = set(container.get("env", {})) | set(container.get("secrets", []))
    if set(service["env"]) - declared:
        out.append(f"env names only in compose: {sorted(set(service['env']) - declared)}")
    if declared - set(service["env"]):
        out.append(f"env names only in [container]: {sorted(declared - set(service['env']))}")
    return out
