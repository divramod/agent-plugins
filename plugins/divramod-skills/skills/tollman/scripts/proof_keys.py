#!/usr/bin/env python3
"""A car's plugin keys, scanned without a build (hal2 plan 0490 step 8, L61; the tollman builds nothing, plan 0467).

proof.py's light check `keys` for a crop that changes a key file: a no-build port of hal2-workspace-checks'
`plugin_keys` (`code/rust/libs/hal2-workspace-checks/src/plugin_keys.rs`: `sequence`, `conflicts`). The keymap is
every `[[contributes.commands]]` key of the crates' `hal2-plugin.toml`, every `contributes.commands` key of the core
plugins' modules (`hal9k-plugin-<name>/manifest.json`) and hal9k-desktop's `app-keys.json`; two commands holding one
sequence where both apply (the same `when`, or none on one side) clash, unless both are the app's or one command
is declared twice (a module repeats its plugin's commands).

The trial merge is read as: the field's files at its hitched head, but the barn's version of a key file the barn
changed since the car left it and the crop did not (one `git diff <head>...<barn>`, one `git show` each). Only a
clash naming one of the crop's key files is the car's: its line starts with that path, so proof.findings keeps it.
"""

import json
import re
import tomllib
from pathlib import Path

APP_KEYS = "code/typescript/apps/hal9k-desktop/src/commands/app-keys.json"
MANIFEST = re.compile(r"^code/rust/(apps|libs)/[^/]+/hal2-plugin\.toml$")
MODULE = re.compile(r"^code/typescript/apps/hal9k-plugin-[^/]+/manifest\.json$")
ALIASES = {"control": "ctrl", "ctrl": "ctrl", "opt": "alt", "option": "alt", "alt": "alt", "command": "cmd",
           "cmd": "cmd"}


def key_file(path: str) -> bool:
    """Whether a path is read by the keymap."""
    return path == APP_KEYS or bool(MANIFEST.match(path) or MODULE.match(path))


def chord(text: str) -> str:
    """One chord as compared: its modifiers by their one name, sorted, deduped, before the key (`sequence`)."""
    if text.endswith("--"):
        mods, key = text[:-2], "-"
    else:
        mods, _, key = text.rpartition("-")
        if not key:
            mods, key = "", text
    names = sorted({ALIASES.get(m.lower(), m.lower()) for m in mods.split("-") if m})
    low = key.lower()
    key = {"esc": "escape", "return": "enter"}.get(low, low if len(key) > 1 else key)
    return "-".join([*names, key])


def sequence(keys: str) -> str:
    return " ".join(chord(c) for c in keys.split())


def held(path: str, holder: str, command: str, keys: str, when) -> dict:
    when = " ".join(str(when).split()) if when else ""
    return {"path": path, "holder": holder, "command": command, "keys": keys, "sequence": sequence(keys),
            "when": when or None}


def parse(path: str, text: str) -> list[dict]:
    """The keys one file holds; a file that does not parse holds none (the gate's other checks name it)."""
    try:
        if path == APP_KEYS:
            return [held(path, "app", r["command"], r["keys"], r.get("when")) for r in json.loads(text)
                    if isinstance(r.get("command"), str) and isinstance(r.get("keys"), str)]
        doc = tomllib.loads(text) if path.endswith(".toml") else json.loads(text)
    except (ValueError, TypeError, AttributeError):
        return []
    commands = (doc.get("contributes") or {}).get("commands") or []
    return [held(path, str(doc.get("id", "")), str(c.get("id", "")), k, c.get("when"))
            for c in commands if isinstance(c, dict) for k in c.get("keys") or [] if isinstance(k, str)]


def conflicts(keys: list[dict], crop: set[str]) -> list[str]:
    """`<crop path>: key <keys> (<when>): held by <holder> <command> and <holder> <command>` for each clash a crop
    file takes part in, sorted, once."""
    found = set()
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            overlap = a["when"] is None or b["when"] is None or a["when"] == b["when"]
            if (a["command"] == b["command"] or (a["holder"] == "app" and b["holder"] == "app")
                    or a["sequence"] != b["sequence"] or not overlap):
                continue
            mine = [s["path"] for s in (a, b) if s["path"] in crop]
            if not mine:
                continue
            x, y = sorted((a, b), key=lambda s: (s["holder"], s["command"]))
            when = x["when"] or y["when"] or "everywhere"
            found.add(f"{mine[0]}: key {x['keys']} ({when}): held by {x['holder']} {x['command']} and {y['holder']} "
                      f"{y['command']}; take a free key (L61, plugin_keys)")
    return sorted(found)


def on_disk(field: str) -> list[str]:
    """The field's key files."""
    root = Path(field)
    found = [*root.glob("code/rust/*/*/hal2-plugin.toml"), *root.glob("code/typescript/apps/hal9k-plugin-*/manifest.json"),
             root / APP_KEYS]
    return sorted(p.relative_to(root).as_posix() for p in found if p.is_file())


def texts(field: str, barn: str, head: str, files: list[str], run) -> dict[str, str]:
    """{path: text} of the key files as the trial merge has them (see the module text)."""
    code, out = run(["git", "diff", "--name-only", "--no-renames", f"{head}...{barn}"], field)
    moved = {p for p in out.splitlines() if key_file(p)} - set(files) if code == 0 else set()
    got = {}
    for path in sorted(set(on_disk(field)) | moved):
        if path in moved:
            code, text = run(["git", "show", f"{barn}:{path}"], field)
            if code == 0:
                got[path] = text
            continue
        try:
            got[path] = (Path(field) / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            pass
    return got


def check(field: str, barn: str, head: str, files: list[str], run) -> tuple[int, str]:
    """proof.py's `keys` check: (0, '') no clash of the crop's, (1, its lines) red."""
    crop = {f for f in files if key_file(f)}
    if not crop:
        return 0, ""
    keys = [k for path, text in texts(field, barn, head, files, run).items() for k in parse(path, text)]
    lines = conflicts(keys, crop)
    return (1 if lines else 0), "\n".join(lines)
