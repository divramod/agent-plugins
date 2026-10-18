#!/usr/bin/env python3
"""Check that the plugin manifests agree with skills/ and with each other.

- every skills/<name>/SKILL.md and skills/<category>/<name>/SKILL.md is listed in .claude-plugin/plugin.json `skills`
  by its real path (`./skills/<name>` or `./skills/<category>/<name>`), and vice versa
- each SKILL.md frontmatter `name` equals its folder name, and has a `description`; names are unique across categories
- every `../<name>/SKILL.md` link in a skill's .md files resolves to a skill (skillpath.sibling's rules: beside it,
  else in any category of the skills root; plan 0360 D19)
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import skillpath  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SIBLING_LINK = re.compile(r"\]\((?:\.\./)+([A-Za-z0-9][A-Za-z0-9._-]*)/SKILL\.md(?:#[^)]*)?\)")
PREREQ_SCRIPTS = ("check-prerequisites.sh", "install-prerequisites.sh")
# A script that contains one of these calls external command-line tools.
TOOL_MARKERS = ("subprocess", "shutil.which", "command -v", "os.system(")


def load(rel, root=ROOT):
    return json.loads((root / rel).read_text())


def skill_files(root: Path = ROOT) -> list[Path]:
    """Every SKILL.md of skills/<name>/ (flat) and skills/<category>/<name>/ (a folder without SKILL.md is a category)."""
    return sorted([*(root / "skills").glob("*/SKILL.md"), *(root / "skills").glob("*/*/SKILL.md")])


def layout_errors(root: Path = ROOT) -> list[str]:
    """Names unique across categories and every sibling link of a skill's .md files resolving (D19, D20)."""
    errors, seen = [], {}
    for skill_md in skill_files(root):
        seen.setdefault(skill_md.parent.name, []).append(skill_md.parent.relative_to(root))
    for name, paths in sorted(seen.items()):
        if len(paths) > 1:
            errors.append(f"skill name '{name}' is in {' and '.join(str(p) for p in paths)}: names are unique")
    for skill_md in skill_files(root):
        for md in sorted(skill_md.parent.rglob("*.md")):
            if "testdata" in md.parts or "fixtures" in md.parts:
                continue
            for target in dict.fromkeys(SIBLING_LINK.findall(md.read_text(errors="ignore"))):
                try:
                    skillpath.sibling(target, md)
                except FileNotFoundError:
                    errors.append(f"{md.relative_to(root)}: link to the skill '{target}' does not resolve "
                                  f"(skills/{target} or skills/<category>/{target})")
    return errors


def uses_tools(folder: Path) -> bool:
    """True when a script directly in folder (not the prereq scripts or tests) calls external tools."""
    return any(
        any(marker in f.read_text(errors="ignore") for marker in TOOL_MARKERS)
        for f in folder.iterdir()
        if f.is_file() and f.suffix in (".py", ".sh") and f.name not in PREREQ_SCRIPTS
        and not f.name.startswith("test_")  # tests may run scripts; they don't need tools of their own
    )


def prereq_errors(skill: Path, base: Path | None = None) -> list[str]:
    """Missing or non-executable prereq scripts in skill/scripts and each skill/scripts/<folder>/."""
    scripts = skill / "scripts"
    if not scripts.is_dir():
        return []
    subfolders = [d for d in sorted(scripts.iterdir()) if d.is_dir() and not d.name.startswith((".", "_"))]
    need = [d for d in subfolders if uses_tools(d)]
    if uses_tools(scripts) or need:  # scripts/ itself, or the aggregators over the per-folder scripts
        need.insert(0, scripts)
    errors = []
    base = base or skill.parent.parent
    for folder in need:
        for name in PREREQ_SCRIPTS:
            f = folder / name
            rel = f.relative_to(base)
            if not f.is_file():
                errors.append(f"{rel} missing ({folder.name}/ scripts call external tools)")
            elif not os.access(f, os.X_OK):
                errors.append(f"{rel} is not executable")
    return errors


def alias_errors(root: Path = ROOT) -> list[str]:
    spec = importlib.util.spec_from_file_location("gen_aliases", Path(__file__).resolve().with_name("gen-aliases.py"))
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    return [] if gen.main(["--check"], root=root) == 0 else ["shortcut skills are out of date: run scripts/gen-aliases.py"]


def listing_errors(root: Path, claude: dict) -> list[str]:
    """plugin.json `skills` holds each skill's real path, no more, no less."""
    on_disk = {f"./{p.parent.relative_to(root).as_posix()}" for p in skill_files(root)}
    listed = set(claude.get("skills", []))
    errors = [f"{s} is missing from .claude-plugin/plugin.json skills" for s in sorted(on_disk - listed)]
    return errors + [f"{s} is listed in .claude-plugin/plugin.json but has no SKILL.md" for s in sorted(listed - on_disk)]


def front_errors(root: Path) -> list[str]:
    errors = []
    for skill_md in skill_files(root):
        m = re.match(r"^---\n(.*?)\n---\n", skill_md.read_text(), re.S)
        front = m.group(1) if m else ""
        name = re.search(r"^name:\s*(.+)$", front, re.M)
        if not name or name.group(1).strip() != skill_md.parent.name:
            errors.append(f"{skill_md.relative_to(root)}: frontmatter name must be '{skill_md.parent.name}'")
        if not re.search(r"^description:\s*\S", front, re.M):
            errors.append(f"{skill_md.relative_to(root)}: frontmatter description is missing")
    return errors


def manifest_errors(root: Path, claude: dict) -> list[str]:
    codex = load(".codex-plugin/plugin.json", root)
    errors = [f"plugin {key} differs: claude={claude.get(key)} codex={codex.get(key)}"
              for key in ("name", "version") if claude.get(key) != codex.get(key)]
    if codex.get("skills") != "./skills/":
        errors.append(".codex-plugin/plugin.json skills must be './skills/'")
    for label, rel in (("claude", ".claude-plugin/marketplace.json"), ("codex", ".agents/plugins/marketplace.json")):
        if not (root / rel).is_file():  # hal2: the marketplace files are the marketplace folder's, not the plugin's
            continue
        names = [p.get("name") for p in load(rel, root).get("plugins", [])]
        if claude.get("name") not in names:
            errors.append(f"{label} marketplace does not list plugin '{claude.get('name')}'")
    return errors


def check(root: Path = ROOT) -> tuple[list[str], dict]:
    claude = load(".claude-plugin/plugin.json", root)
    errors = alias_errors(root) + listing_errors(root, claude) + front_errors(root) + layout_errors(root)
    for skill_md in skill_files(root):
        errors += prereq_errors(skill_md.parent, root)
    return errors + manifest_errors(root, claude), claude


def main() -> int:
    errors, claude = check()
    for e in errors:
        print(f"error: {e}", file=sys.stderr)
    if not errors:
        print(f"ok: {len(skill_files())} skill(s), plugin {claude['name']} v{claude['version']}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
