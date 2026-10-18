#!/usr/bin/env python3
"""A role's effective duties (hal2 plan 0360, D27, D73): the role skill's `## Duties`, overridden and extended by a
repository's `roles/<role>/ROLE.md`.

    python3 role_duties.py <role> [--repo <dir>] [--json]

A role skill (`skills/roles/<role>/SKILL.md`) lists its standard duties under `## Duties`, one `### <id>` each (id:
lowercase kebab-case; `### <id>: <title>` gives it a title), followed by a short paragraph. A repository's
`roles/<role>/ROLE.md` (read from the main checkout, `roles.main_checkout`) may have its own `## Duties`: an id the
skill has is overridden (the repository's text replaces the skill's, `source` `override`), a new id extends the list
(`extension`, after the skill's). Everything else of ROLE.md (front matter, Priorities, Rules, Tasks) is no duty.
Only `##` and `###` headings outside fenced code count. Text only: the farmer's and the tollman's round code
(`duties.py`, the ROLE.md front matter's `duties:` crons) stays the source of truth for what their ticks run.

Exit 0 with the list; 1 when a file's Duties section is malformed (a heading that is no id, an id twice); 2 for an
unknown role, naming the known ones (every skill in the skills unit's `roles/`).
"""

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import candidates, skills_root  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)

ROLE_SKILLS = ("farmer", "foreman", "lord", "mayor", "pope", "servant", "steward", "tollman")  # the flat (published) layout's roles
ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FENCE = re.compile(r"^\s*(```|~~~)")


@dataclass(frozen=True)
class Duty:
    id: str
    title: str
    text: str
    source: str  # skill | override | extension

    @property
    def first_line(self) -> str:
        return self.text.splitlines()[0] if self.text else self.title


class DutiesError(ValueError):
    pass


def known_roles(start=__file__) -> list[str]:
    """Every skill in the unit's `roles/` category; in a flat layout the role skills that are there."""
    root = skills_root(start)
    folder = root / "roles" if root else None
    if folder and folder.is_dir():
        return sorted(p.name for p in folder.iterdir() if (p / "SKILL.md").is_file())
    return [r for r in ROLE_SKILLS if skill_file(r, start)]


def skill_file(role: str, start=__file__) -> Path | None:
    """The role skill's SKILL.md (skillpath's search: beside this skill, in a category, flat)."""
    for path in candidates(role, start):
        if (path / "SKILL.md").is_file():
            return path / "SKILL.md"
    return None


def body_lines(text: str) -> list[str]:
    """The lines after a leading front matter block (`---` ... `---`)."""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for n, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                return lines[n + 1:]
    return lines


def parse(text: str, where: str = "") -> list[tuple[str, str, str]]:
    """The `## Duties` section's duties as (id, title, text), in order; [] without the section."""
    out: list[list[str]] = []
    inside = fenced = False
    for line in body_lines(text):
        if FENCE.match(line):
            fenced = not fenced
        heading = None if fenced else re.match(r"^(#{2,3}) +(.+?)\s*#*\s*$", line)
        if heading and len(heading.group(1)) == 2:
            inside = heading.group(2).strip().lower() == "duties"
            continue
        if not inside:
            continue
        if heading:
            ident, _, title = heading.group(2).partition(":")
            out.append([ident.strip(), title.strip(), ""])
        elif out:
            out[-1][2] += line + "\n"
    seen: set[str] = set()
    for ident, _, _ in out:
        if not ID.match(ident):
            raise DutiesError(f"{where}: `### {ident}` is no duty id (lowercase kebab-case)")
        if ident in seen:
            raise DutiesError(f"{where}: duty `{ident}` twice")
        seen.add(ident)
    return [(i, t, body.strip()) for i, t, body in out]


def merge(skill: list[tuple[str, str, str]], repo: list[tuple[str, str, str]]) -> list[Duty]:
    """The skill's duties, each replaced by the repository's of the same id; the repository's new ids after them."""
    own = {i: (t, body) for i, t, body in repo}
    out = []
    for ident, title, body in skill:
        if ident in own:
            t, b = own[ident]
            out.append(Duty(ident, t or title, b, "override"))
        else:
            out.append(Duty(ident, title, body, "skill"))
    have = {i for i, _, _ in skill}
    return out + [Duty(i, t, body, "extension") for i, t, body in repo if i not in have]


def role_file(role: str, repo: str | Path) -> Path:
    import roles  # the farmer's frame: git, main checkout (imported late: its import finds sibling skills)
    return roles.main_checkout(repo) / "roles" / role / "ROLE.md"


def duties(role: str, repo: str | Path | None = None, start=__file__) -> list[Duty]:
    """The effective duties of `role`, with `repo` its repository's ROLE.md applied. KeyError: unknown role."""
    path = skill_file(role, start)
    if path is None or role not in known_roles(start):
        raise KeyError(role)
    skill = parse(path.read_text(), str(path))
    own: list[tuple[str, str, str]] = []
    if repo is not None:
        file = role_file(role, repo)
        own = parse(file.read_text(), str(file)) if file.is_file() else []
    return merge(skill, own)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("role")
    p.add_argument("--repo", help="a checkout of the repository whose roles/<role>/ROLE.md applies")
    p.add_argument("--json", action="store_true", help="every field of every duty")
    args = p.parse_args(argv)
    try:
        found = duties(args.role, args.repo)
    except KeyError:
        print(f"role_duties: unknown role '{args.role}'; known: {', '.join(known_roles())}", file=sys.stderr)
        return 2
    except DutiesError as e:
        print(f"role_duties: {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"role": args.role, "skill": str(skill_file(args.role)),
                          "role_file": str(role_file(args.role, args.repo)) if args.repo else None,
                          "duties": [asdict(d) for d in found]}, indent=1))
        return 0
    width = max((len(d.id) for d in found), default=0)
    for d in found:
        print(f"{d.id:<{width}}  {d.source:<9}  {d.first_line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
