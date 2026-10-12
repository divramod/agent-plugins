#!/usr/bin/env python3
"""Check that the plugin manifests agree with skills/ and with each other.

- every skills/<name>/SKILL.md is listed in .claude-plugin/plugin.json `skills`, and vice versa
- each SKILL.md frontmatter `name` equals its folder name, and has a `description`
- .claude-plugin/plugin.json and .codex-plugin/plugin.json share name + version
- the plugin name matches in both marketplaces
- every scripts folder whose own scripts call external tools (scripts/ itself, or a per-source
  scripts/<folder>/) ships executable check-prerequisites.sh and install-prerequisites.sh; when any
  scripts/<folder>/ does, scripts/ also ships both as aggregators (see CLAUDE.md, "Skill script rules")
- the shortcut skills generated from aliases.json are up to date (scripts/gen-aliases.py --check)

Run: python3 scripts/check-plugins.py   (exit 1 on any problem)
"""
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREREQ_SCRIPTS = ("check-prerequisites.sh", "install-prerequisites.sh")
# A script that contains one of these calls external command-line tools.
TOOL_MARKERS = ("subprocess", "shutil.which", "command -v", "os.system(")


def load(rel):
    return json.loads((ROOT / rel).read_text())


def uses_tools(folder: Path) -> bool:
    """True when a script directly in folder (not the prereq scripts or tests) calls external tools."""
    return any(
        any(marker in f.read_text(errors="ignore") for marker in TOOL_MARKERS)
        for f in folder.iterdir()
        if f.is_file() and f.suffix in (".py", ".sh") and f.name not in PREREQ_SCRIPTS
        and not f.name.startswith("test_")  # tests may run scripts; they don't need tools of their own
    )


def prereq_errors(skill: Path) -> list[str]:
    """Missing or non-executable prereq scripts in skill/scripts and each skill/scripts/<folder>/."""
    scripts = skill / "scripts"
    if not scripts.is_dir():
        return []
    subfolders = [d for d in sorted(scripts.iterdir()) if d.is_dir() and not d.name.startswith((".", "_"))]
    need = [d for d in subfolders if uses_tools(d)]
    if uses_tools(scripts) or need:  # scripts/ itself, or the aggregators over the per-folder scripts
        need.insert(0, scripts)
    errors = []
    for folder in need:
        for name in PREREQ_SCRIPTS:
            f = folder / name
            rel = f.relative_to(skill.parent.parent)
            if not f.is_file():
                errors.append(f"{rel} missing ({folder.name}/ scripts call external tools)")
            elif not os.access(f, os.X_OK):
                errors.append(f"{rel} is not executable")
    return errors


def alias_errors() -> list[str]:
    spec = importlib.util.spec_from_file_location("gen_aliases", ROOT / "scripts" / "gen-aliases.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    return [] if gen.main(["--check"]) == 0 else ["shortcut skills are out of date: run scripts/gen-aliases.py"]


def main() -> int:
    errors = alias_errors()
    claude = load(".claude-plugin/plugin.json")
    codex = load(".codex-plugin/plugin.json")
    claude_mkt = load(".claude-plugin/marketplace.json") if (ROOT / ".claude-plugin/marketplace.json").is_file() else None
    codex_mkt = load(".agents/plugins/marketplace.json") if (ROOT / ".agents/plugins/marketplace.json").is_file() else None

    on_disk = {f"./skills/{p.parent.name}" for p in (ROOT / "skills").glob("*/SKILL.md")}
    listed = set(claude.get("skills", []))
    for s in sorted(on_disk - listed):
        errors.append(f"{s} is missing from .claude-plugin/plugin.json skills")
    for s in sorted(listed - on_disk):
        errors.append(f"{s} is listed in .claude-plugin/plugin.json but has no SKILL.md")

    for skill_md in sorted((ROOT / "skills").glob("*/SKILL.md")):
        m = re.match(r"^---\n(.*?)\n---\n", skill_md.read_text(), re.S)
        front = m.group(1) if m else ""
        name = re.search(r"^name:\s*(.+)$", front, re.M)
        if not name or name.group(1).strip() != skill_md.parent.name:
            errors.append(f"{skill_md.relative_to(ROOT)}: frontmatter name must be '{skill_md.parent.name}'")
        if not re.search(r"^description:\s*\S", front, re.M):
            errors.append(f"{skill_md.relative_to(ROOT)}: frontmatter description is missing")

    for skill in sorted(p.parent for p in (ROOT / "skills").glob("*/SKILL.md")):
        errors += prereq_errors(skill)

    for key in ("name", "version"):
        if claude.get(key) != codex.get(key):
            errors.append(f"plugin {key} differs: claude={claude.get(key)} codex={codex.get(key)}")
    if codex.get("skills") != "./skills/":
        errors.append(".codex-plugin/plugin.json skills must be './skills/'")
    for label, mkt in (("claude", claude_mkt), ("codex", codex_mkt)):
        if mkt is None:  # hal2: the marketplace files are the marketplace folder's, not the plugin's
            continue
        names = [p.get("name") for p in mkt.get("plugins", [])]
        if claude.get("name") not in names:
            errors.append(f"{label} marketplace does not list plugin '{claude.get('name')}'")

    for e in errors:
        print(f"error: {e}", file=sys.stderr)
    if not errors:
        print(f"ok: {len(on_disk)} skill(s), plugin {claude['name']} v{claude['version']}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
