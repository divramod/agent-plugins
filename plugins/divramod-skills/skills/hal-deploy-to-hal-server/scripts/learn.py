"""`learn <slug>`: a problem met during a deploy becomes a check with its test and a line in references/problems.md
(D17). The scaffold's test fails until it reproduces the problem, so the step cannot be skipped. Outside hal2 the skill
cannot change hal2: `--brief` prints a brief for hal2's farmer instead."""

from __future__ import annotations

import re
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SLUG = re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*")

CHECK = '''"""{problem}"""

from checks import finding

SLUG = "{slug}"
WHY = "{problem}"


def run(ctx):
    # TODO: read ctx["container"] and ctx["inspect"] (None without a repository), return finding(SLUG, severity, detail)
    return []
'''
TEST = '''"""The check `{slug}`: the problem, reproduced."""

import unittest

from checks import {module}


class {cls}Test(unittest.TestCase):
    def test_reproduces_the_problem(self):
        self.fail("write the test: the input that showed `{slug}` must give a finding, a good one must not")

    def test_without_a_repository_it_finds_nothing_or_declares_so(self):
        ctx = {{"site": "demo", "container": {{}}, "inspect": None}}
        self.assertIsInstance({module}.run(ctx), list)


if __name__ == "__main__":
    unittest.main()
'''
BRIEF = """Brief for hal2's farmer: a new check for the skill hal-deploy-to-hal-server

Problem met while deploying: {problem}

Add to code/agents/apps/skills/skills/actions/hal-deploy-to-hal-server/ (the skill's own `learn {slug}` scaffolds it):
- scripts/checks/{module}.py: SLUG = "{slug}", `run(ctx)` returning findings (see scripts/checks/__init__.py)
- scripts/test_check_{module}.py: the input that showed the problem must give a finding, a good one none
- a line in references/problems.md
Done when `python3 -m unittest -q` in the skill's scripts/ passes (test_checks.py fails on a check without a test).
"""


def module_of(slug: str) -> str:
    return slug.replace("-", "_")


def check_slug(slug: str) -> str:
    if not SLUG.fullmatch(slug):
        raise ValueError("a slug is kebab-case: letters, digits, hyphens")
    return slug


def brief(slug: str, problem: str) -> str:
    return BRIEF.format(slug=check_slug(slug), module=module_of(slug), problem=problem or "(describe it)")


def scaffold(slug: str, problem: str, skill: Path = SKILL) -> list[str]:
    check_slug(slug)
    module = module_of(slug)
    problem = (problem or "TODO: one line, what went wrong and how a check sees it").replace('"', "'").replace("\n", " ")
    check, test = skill / "scripts/checks" / f"{module}.py", skill / "scripts" / f"test_check_{module}.py"
    for path in (check, test):
        if path.exists():
            raise FileExistsError(f"{path.name} exists: the problem {slug} is already a check")
    check.write_text(CHECK.format(slug=slug, problem=problem))
    cls = "".join(p.capitalize() for p in slug.split("-"))
    test.write_text(TEST.format(slug=slug, module=module, cls=cls))
    log = skill / "references/problems.md"
    with log.open("a") as handle:
        handle.write(f"- `{slug}`: {problem} (checks/{module}.py, test_check_{module}.py)\n")
    return [str(check), str(test), str(log)]
