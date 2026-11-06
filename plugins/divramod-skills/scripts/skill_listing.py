#!/usr/bin/env python3
"""Count the skill listing: what every main session and subagent loads of this plugin's skills (plan 0485, 01.01).

Claude Code lists every model-invocable skill as its name and its description, `<` and `>` shown as `&lt;` and
`&gt;` (research 0118, notes-install-load.md M2); a skill with `disable-model-invocation: true` is left out. The rule
(README's Rules, "Skill listing"): a description at most 400 characters, use case first, no `<>`, and a skill only the
user types carries `disable-model-invocation: true`.

  python3 scripts/skill_listing.py            # one row per skill, the user-only ones, the total against the goal
  python3 scripts/skill_listing.py --json     # the same as JSON (schema 1)
  python3 scripts/skill_listing.py --root DIR # another skills folder (`<category>/<name>/SKILL.md` or `<name>/SKILL.md`)

Exit 0; 1 when the total is over the goal (`--strict`).
"""
import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
BOUND = 400
GOAL = 25_000
SCHEMA = 1


@dataclass(frozen=True)
class Skill:
    path: str  # `<category>/<name>` (or `<name>` in a flat folder)
    name: str
    description: str
    user_only: bool  # `disable-model-invocation: true`: not in the model's listing

    @property
    def listed(self) -> str:
        """The description as the listing shows it."""
        return self.description.replace("<", "&lt;").replace(">", "&gt;")

    @property
    def chars(self) -> int:
        """The skill's characters in the listing: name plus listed description; 0 for a user-only skill."""
        return 0 if self.user_only else len(self.name) + len(self.listed)


def front_matter(text: str) -> dict[str, str]:
    """The `key: value` lines between the first two `---` lines; a quoted value unquoted."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, sep, value = line.partition(":")
        if sep and key and not key.startswith((" ", "\t", "#")):
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            out[key.strip()] = value
    return out


def read(root: Path = SKILLS) -> list[Skill]:
    """Every skill under `root`, sorted by path."""
    skills = []
    for md in sorted(root.glob("*/SKILL.md")) + sorted(root.glob("*/*/SKILL.md")):
        meta = front_matter(md.read_text())
        rel = md.parent.relative_to(root).as_posix()
        skills.append(Skill(
            path=rel,
            name=meta.get("name", md.parent.name),
            description=meta.get("description", ""),
            user_only=meta.get("disable-model-invocation", "").lower() == "true",
        ))
    return sorted(skills, key=lambda s: s.path)


def total(skills: list[Skill]) -> int:
    return sum(s.chars for s in skills)


def report(skills: list[Skill]) -> dict:
    listed = [s for s in skills if not s.user_only]
    return {
        "schema": SCHEMA,
        "bound": BOUND,
        "goal": GOAL,
        "total": total(skills),
        "skills": [{"path": s.path, "name": s.name, "chars": s.chars, "description": len(s.listed),
                    "over": len(s.listed) > BOUND} for s in sorted(listed, key=lambda s: -s.chars)],
        "user_only": [s.path for s in skills if s.user_only],
    }


def text(rep: dict) -> str:
    rows = [f"{'chars':>6}  {'desc':>5}  skill"]
    rows += [f"{s['chars']:>6}  {s['description']:>5}{'*' if s['over'] else ' '} {s['path']}" for s in rep["skills"]]
    over = sum(s["over"] for s in rep["skills"])
    rows += [
        "",
        f"user-only, not listed ({len(rep['user_only'])}): {', '.join(rep['user_only']) or '-'}",
        f"listed: {len(rep['skills'])} skills, {over} with a description over {rep['bound']} (*)",
        f"total: {rep['total']:,} characters (goal ≤ {rep['goal']:,})",
    ]
    return "\n".join(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=SKILLS, help="the skills folder (default: this plugin's)")
    ap.add_argument("--json", action="store_true", help="print JSON (schema 1)")
    ap.add_argument("--strict", action="store_true", help="exit 1 when the total is over the goal")
    args = ap.parse_args(argv)
    rep = report(read(args.root))
    print(json.dumps(rep, indent=2) if args.json else text(rep))
    return 1 if args.strict and rep["total"] > GOAL else 0


if __name__ == "__main__":
    sys.exit(main())
