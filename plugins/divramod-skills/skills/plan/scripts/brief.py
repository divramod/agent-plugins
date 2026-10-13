"""brief.py: a plan's short Brief (research 0077, plan 0293): the section `## Brief` after the Goal with the four
labelled lines In, Out, Must and Proof, written from the plan's seed. `new` writes the template's placeholders
(`<...>`); `plan.py check` reports a plan that is not done and still holds the placeholder in Out or Proof, or the
placeholder `- Seed: <seedbag>#<n>` line in its Context (rule `plan-brief-filled`). A plan without the section passes
(legacy plans, decision D4); `plan.py` only wires this module in."""
import re

HEADING = "## Brief"
LABELS = ("In", "Out", "Must", "Proof")
MUST_BE_FILLED = ("Out", "Proof")
RULE = "plan-brief-filled"
LINE = re.compile(r"^- (In|Out|Must|Proof):\s*(.*)$")
SEED = re.compile(r"^- Seed:\s*(.*)$")
PLACEHOLDER = re.compile(r"^<[^<>]*>$")


def is_placeholder(value: str) -> bool:
    """Still the template's text (`<what it leaves alone>`), or empty."""
    value = value.strip()
    return not value or bool(PLACEHOLDER.match(value))


def seed_placeholder(value: str) -> bool:
    """The template's `<seedbag>#<n>`: a plan without a seed deletes the line, one with a seed fills it."""
    value = value.strip()
    return not value or value.startswith("<") and value.endswith(">")


def section(text: str, heading: str) -> list[str] | None:
    """The lines of the `## <heading>` section (up to the next `## `), None without it."""
    lines, found = text.splitlines(), None
    for line in lines:
        if found is None:
            if line.strip() == heading:
                found = []
        elif line.startswith("## "):
            break
        else:
            found.append(line)
    return found


def parse(text: str) -> dict[str, str] | None:
    """The Brief's four values (`""` for a label that is missing), None when the plan has no `## Brief`. A line
    that is no labelled line continues the one before it."""
    lines = section(text, HEADING)
    if lines is None:
        return None
    values, last = {label: "" for label in LABELS}, None
    for line in lines:
        match = LINE.match(line.rstrip())
        if match:
            last = match.group(1)
            values[last] = match.group(2).strip()
        elif last and line.strip():
            values[last] = f"{values[last]} {line.strip()}".strip()
    return values


def filled(text: str) -> dict[str, str] | None:
    """`parse`, with the template's placeholders turned into empty strings (what `plan.py current` shows)."""
    values = parse(text)
    return None if values is None else {k: "" if is_placeholder(v) else v for k, v in values.items()}


def seed(text: str) -> str | None:
    """The value of the Context's `- Seed:` line, None without one."""
    for line in section(text, "## Context") or []:
        match = SEED.match(line.rstrip())
        if match:
            return match.group(1).strip()
    return None


def problems(text: str, label: str, done: bool = False) -> list[str]:
    """The `plan-brief-filled` lines for a plan.md (`label` is its path): a Brief whose Out or Proof is still the
    placeholder, a Context `- Seed:` line still the placeholder. A plan that is done has none."""
    if done:
        return []
    found, values, at = [], parse(text), seed(text)
    if values is not None:
        found += [f"{label}: the Brief's {name} is still empty or the template's placeholder: write it from the seed "
                  f"({RULE})" for name in MUST_BE_FILLED if is_placeholder(values[name])]
    if at is not None and seed_placeholder(at):
        found.append(f"{label}: the Context's `- Seed:` line is still the placeholder: name the seed "
                     f"(`<seedbag>#<n>`) or delete the line ({RULE})")
    return found
