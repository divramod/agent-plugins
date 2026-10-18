#!/usr/bin/env python3
"""Link every skill of this repo into the agents' skill folders.

  python3 scripts/install-skills.py [--dry-run] [--check] [--unlink] [--quiet] [--target DIR ...]

Default targets: ~/.claude/skills (Claude Code) and ~/.agents/skills (Codex and the other CLIs that read the
shared folder). For each skills/<name> or skills/<category>/<name> it creates <target>/<name> as a symlink to the
skill (flat, whatever the category). Links that point into this repo but no longer match a skill (renamed, moved or
removed skills, also a link that went dangling at a move) are relinked or deleted; a link into any skills unit of
this repository (code/*/apps/skills/, so also one left in the old folder of a unit that moved, plan 0360) is ours. Anything else in a target (real
folders, links to other places) is never touched; a name clash is a warning on stderr and skipped (exit 0, so a
delivery never fails on it). Two skills of one name in different categories are an error that links nothing (exit 1).
--unlink removes every link into this repo and nothing else. --check changes nothing: exit 1 naming each skill not linked to this repo (missing, clash) and each stale link, else
exit 0. --quiet prints only changes (nothing when all is linked).
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGETS = ("~/.claude/skills", "~/.agents/skills")


class DuplicateSkills(Exception):
    """Two skills of one name in different categories."""


def skills() -> dict[str, Path]:
    """name -> folder: skills/<name>/ (flat) and skills/<category>/<name>/ (a folder with SKILL.md is a skill, else
    a category looked into one level). The link name is the folder name; two of one name raise DuplicateSkills."""
    found: dict[str, list[Path]] = {}
    for top in sorted((ROOT / "skills").iterdir()):
        if (top / "SKILL.md").is_file():
            found.setdefault(top.name, []).append(top)
        elif top.is_dir():
            for sub in sorted(top.iterdir()):
                if (sub / "SKILL.md").is_file():
                    found.setdefault(sub.name, []).append(sub)
    dupes = {name: paths for name, paths in found.items() if len(paths) > 1}
    if dupes:
        raise DuplicateSkills("; ".join(f"{name} is in {' and '.join(str(p) for p in paths)}"
                                        for name, paths in sorted(dupes.items())))
    return {name: paths[0] for name, paths in sorted(found.items())}


def repo_root(start: Path) -> Path | None:
    """The first folder from start upwards holding .git (a folder, or a file in a worktree)."""
    for folder in (start, *start.parents):
        if (folder / ".git").exists():
            return folder
    return None


def points_into_repo(link: Path) -> bool:
    """Whether link is ours: its target lies under ROOT, or under a skills unit of ROOT's repository
    (code/<category>/apps/skills/), so the links of a unit that moved to another category folder are relinked."""
    target = Path(link.readlink())
    if not target.is_absolute():
        target = link.parent / target
    target = target.resolve(strict=False)
    if ROOT.resolve() in target.parents:
        return True
    repo = repo_root(ROOT.resolve())
    if repo is None or repo not in target.parents:
        return False
    parts = target.relative_to(repo).parts
    return len(parts) > 4 and parts[0] == "code" and parts[2:4] == ("apps", "skills")


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
    parser.add_argument("--check", action="store_true", help="change nothing; exit 1 when a skill is not linked")
    parser.add_argument("--unlink", action="store_true", help="remove every link into this repo (link-skills.sh --unlink)")
    parser.add_argument("--quiet", action="store_true", help="print only what changes")
    parser.add_argument("--target", action="append", help="skill folder to install into (repeatable)")
    args = parser.parse_args(argv)

    try:
        wanted = skills()
    except DuplicateSkills as e:
        print(f"error: two skills share a link name, nothing linked: {e}", file=sys.stderr)
        return 1
    targets = [Path(raw).expanduser() for raw in args.target or DEFAULT_TARGETS]
    if args.check:
        return check(targets, wanted)
    if args.unlink:
        wanted = {}  # nothing is wanted: every link into this repo is stale and goes
    for target in targets:
        for action, link, source in plan(target, wanted):
            if action == "clash":
                print(f"warning: {link} exists and is not a link into {ROOT}; skipped", file=sys.stderr)
                continue
            if action == "keep" and args.quiet:
                continue
            if action != "keep" and not args.dry_run:
                apply(action, link, source)
            print(f"{action:<6} {link}" + (f" -> {source}" if source and action != "keep" else ""))
    return 0


def check(targets: list[Path], wanted: dict[str, Path]) -> int:
    bad = []
    for target in targets:
        for action, link, _ in plan(target, wanted):
            if action == "link":
                bad.append(f"missing {link}")
            elif action == "relink":
                bad.append(f"wrong-target {link}")
            elif action == "clash":
                bad.append(f"clash {link} (not a link into {ROOT})")
            elif action == "remove":
                bad.append(f"stale {link}")
    for line in bad:
        print(line)
    if not bad:
        print(f"all {len(wanted)} skills linked")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
