#!/usr/bin/env python3
"""Link every skill of this repo into the agents' skill folders.

  python3 scripts/install-skills.py [--dry-run] [--target DIR ...]

Default targets: ~/.claude/skills (Claude Code) and ~/.agents/skills (Codex and the other CLIs that read the
shared folder). For each skills/<name> it creates <target>/<name> as a symlink to the skill. Links that point into
this repo but no longer match a skill (renamed or removed skills) are deleted. Anything else in a target (real
folders, links to other places) is never touched; a name clash is reported and skipped.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGETS = ("~/.claude/skills", "~/.agents/skills")


def skills() -> dict[str, Path]:
    return {p.name: p for p in sorted((ROOT / "skills").iterdir()) if (p / "SKILL.md").is_file()}


def points_into_repo(link: Path) -> bool:
    target = Path(link.readlink())
    if not target.is_absolute():
        target = link.parent / target
    return ROOT.resolve() in target.resolve(strict=False).parents


def plan(target: Path, wanted: dict[str, Path]) -> list[tuple[str, Path, Path | None]]:
    """(action, link, source) for one target folder: link, relink, remove, keep or clash."""
    actions = []
    for name, source in wanted.items():
        link = target / name
        if link.is_symlink():
            same = link.resolve(strict=False) == source.resolve()
            if same:
                actions.append(("keep", link, source))
            elif points_into_repo(link):
                actions.append(("relink", link, source))
            else:
                actions.append(("clash", link, source))
        elif link.exists():
            actions.append(("clash", link, source))
        else:
            actions.append(("link", link, source))
    if target.is_dir():
        for link in sorted(target.iterdir()):
            if link.name not in wanted and link.is_symlink() and points_into_repo(link):
                actions.append(("remove", link, None))
    return actions


def apply(action: str, link: Path, source: Path | None) -> None:
    if action in ("relink", "remove"):
        link.unlink()
    if action in ("link", "relink") and source is not None:
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(source)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="print what would change, change nothing")
    parser.add_argument("--target", action="append", help="skill folder to install into (repeatable)")
    args = parser.parse_args(argv)

    wanted = skills()
    clashes = 0
    for raw in args.target or DEFAULT_TARGETS:
        target = Path(raw).expanduser()
        for action, link, source in plan(target, wanted):
            if action == "clash":
                clashes += 1
                print(f"skip   {link}: exists and is not a link into {ROOT}", file=sys.stderr)
                continue
            if action != "keep" and not args.dry_run:
                apply(action, link, source)
            print(f"{action:<6} {link}" + (f" -> {source}" if source and action != "keep" else ""))
    return 1 if clashes else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
