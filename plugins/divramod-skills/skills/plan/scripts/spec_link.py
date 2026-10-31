"""spec_link.py: a plan that grows from a spec and its designs (hal2 plan 0364, step 5; plan 0502, D6, D7, D9).

A spec is a plan from its start (D7): `spec.py new` writes `plans/<NNNN>-<slug>/plan.md` in state `spec` beside
spec.md. `plan.py new --spec <n|slug>` (and `/plan` on a current spec-state plan) plans it **in place**: the same
plan.md gets its step table and Notes, `status: spec` becomes `open`, the Brief is re-seeded from spec.md (In and Out
from its Scope, Must from its Requirements, Proof from its acceptance criteria) and from the accepted designs, one
per feat and kind (a Must line and the Proof: the result conforms to them), and Context links `spec.md` and
`design.html`. No second folder, no copy; the ledgers, the handoff and `grilled` stay. A legacy spec folder without a
plan.md still gets one written into it. The spec comes from the spec skill's `spec.py`, the designs from the design
skill's `design.py accepted --json`, both found through `skillpath.sibling`, never by a path. `plan.py` only wires
this in.

A spec updated after its plan has steps carries `spec_review: <round>` in plan.md's front matter (spec.py update, D6)
until `spec.py reviewed <n>` clears it; `review_problems` is the check's rule `plan-spec-review`.

  load(root, ref)        -> (spec info, folder); refuses a plan that is no longer in state spec, or a folder without spec.md
  in_place(folder)       -> True when the folder's plan.md is the spec-state one that `fill` plans
  fill(path, info, designs, goal, seed_line)   plan the spec-state plan.md in place (steps, Brief, Context, status open)
  review(text)           -> the round of the pending review flag, 0 without
  review_problems(text, label) -> the `plan-spec-review` lines of a plan.md
  accepted(root, folder) -> the accepted designs [{id, feat, kind, version, title, superseded}], [] without any
  seed(path, info, designs)  rewrite the new plan.md's Brief and Context
  fields(root, path)     -> {"spec": <path or "">, "designs": [...]} for `plan.py current`
  hint(root)             -> the error text when CURRENT_PLAN names a spec-only folder, else ""
"""
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import envelope
import folder as plan_folder
import planhome
import pointers

HERE = Path(__file__).resolve().parent
PLANS = "plans"
POINTER = "CURRENT_PLAN"
SPEC, PLAN, DESIGN = "spec.md", "plan.md", "design.html"
FOLDER = re.compile(r"^(\d{4})-[a-z0-9-]+$")
BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
SCOPE = re.compile(r"^(In|Out):\s*(.*)$")
TEMPLATE = HERE.parent / "templates" / PLAN
REVIEW, RULE = "spec_review", "plan-spec-review"
STEPS = re.compile(r"## Steps\n.*?(?=\n## )", re.S)
NOTES = re.compile(r"## Notes\n.*\Z", re.S)
BRIEF = re.compile(r"(## Brief\n\n)(.*?)(?=\n## )", re.S)
GOAL = re.compile(r"(## Goal\n\n)(.*?)(?=\n\n## )", re.S)
TEMPLATE_BRIEF = {"In": "- In: <what this plan delivers>", "Out": "- Out: <what it leaves alone>",
                  "Must": "- Must: <each requirement one line, the user's words quoted>",
                  "Proof": "- Proof: <the command or the UAT checks that show the whole works>"}


class SpecLinkError(Exception):
    pass


def sibling_script(skill: str, script: str) -> Path:
    """`<skill>/scripts/<script>` through the skills unit's skillpath.py."""
    try:
        base = next(p / "scripts" for p in HERE.parents if (p / ".claude-plugin").is_dir())
        if str(base) not in sys.path:
            sys.path.insert(0, str(base))
        from skillpath import sibling
        return sibling(skill, HERE / "plan.py") / "scripts" / script
    except (StopIteration, ImportError, FileNotFoundError):
        raise SpecLinkError(f"the {skill} skill is not installed beside the plan skill: `--spec` needs it") from None


def spec_module():
    path = sibling_script("spec", "spec.py")
    loaded = importlib.util.spec_from_file_location("spec_skill", path)
    module = importlib.util.module_from_spec(loaded)
    sys.modules.setdefault("spec_skill", module)
    loaded.loader.exec_module(module)
    return module


def status_of(folder: Path) -> str:
    """plan.md's status (`spec`, `open`, ...); "" without a plan.md or without front matter (a legacy plan)."""
    path = folder / PLAN
    if not path.is_file():
        return ""
    text = path.read_text()
    return plan_folder.header(text, "status") if plan_folder.is_record(text) else ""


def in_place(folder: Path) -> bool:
    return status_of(folder) == "spec"


def load(root: Path, ref: str) -> tuple[dict, Path]:
    spec = spec_module()
    try:
        folder = spec.resolve(root, ref)
        info = spec.describe(root, folder)
    except spec.SpecError as error:
        raise SpecLinkError(str(error)) from None
    if (folder / PLAN).is_file() and not in_place(folder):
        state = status_of(folder) or "a legacy plan"
        raise SpecLinkError(f"{info['folder']} is already planned (plan.md is {state}, not spec): continue it with "
                            f"`plan.py use {info['number']}`")
    return info, folder


def accepted(root: Path, folder: Path) -> list[dict]:
    """The accepted design versions of the spec folder (`design.py accepted --json`); [] without a review state, since
    nothing is accepted before `design/state.json` exists (no subprocess for a plan that has only drafts)."""
    if not (folder / "design" / "state.json").is_file():
        return []
    script = sibling_script("design", "design.py")
    out = subprocess.run([sys.executable, str(script), "accepted", "--json", "--repo", str(root),
                          "--plan", folder.name], capture_output=True, text=True)
    if out.returncode != 0:
        raise SpecLinkError(f"design.py accepted: {(out.stderr or out.stdout).strip()}")
    rows = json.loads(out.stdout).get("accepted", [])
    return [{k: row.get(k) for k in ("id", "feat", "kind", "version", "title", "superseded")} for row in rows]


def items(text: str, left: list[str]) -> list[str]:
    """The bullets of a section as one string each (an indented line continues the one above); a bullet that still
    holds a placeholder of the spec template is no content."""
    found: list[str] = []
    for line in text.splitlines():
        match = BULLET.match(line)
        if match:
            found.append(match.group(1).strip())
        elif line.strip() and found and line[0] in " \t":
            found[-1] += " " + line.strip()
    return [i for i in found if not any(p in i for p in left)]


def criteria(text: str, left: list[str]) -> list[str]:
    """The ids of the acceptance table's rows that are filled in."""
    ids = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.strip().startswith("|") else []
        if len(cells) < 2 or cells[0] in ("ID", "") or set("".join(cells)) <= set("-: "):
            continue
        if not any(p in line for p in left):
            ids.append(cells[0])
    return ids


def brief_values(info: dict, designs: list[dict]) -> dict[str, list[str]]:
    """The lines to write into In, Out, Must and Proof; a label without content keeps the template's placeholder."""
    sections, left = info["sections"], info["placeholders"]
    values: dict[str, list[str]] = {label: [] for label in TEMPLATE_BRIEF}
    for item in items(sections.get("Scope", ""), left):
        match = SCOPE.match(item)
        if match and match.group(2) and match.group(2).lower() != "none":
            values[match.group(1)].append(match.group(2))
    values["Must"] = items(sections.get("Requirements", ""), left)
    ids = criteria(sections.get("Acceptance criteria", ""), left)
    if designs:
        names = ", ".join(d["id"] for d in designs)
        values["Must"].append(f"conforms to the accepted designs: {names} (design.html)")
    proof = []
    if ids:
        proof.append(f"the acceptance criteria {', '.join(ids)} of spec.md hold (the UATs)")
    if designs:
        proof.append("the result conforms to the accepted designs")
    values["Proof"] = ["; ".join(proof)] if proof else []
    return values


def seed(path: Path, info: dict, designs: list[dict]) -> None:
    """Rewrite a plan.md's Brief from the spec and the designs and its Context's Spec line; a label the spec says
    nothing for keeps the template's placeholder (`plan.py check` reports it)."""
    text = BRIEF.sub(lambda m: m.group(1) + "\n".join(TEMPLATE_BRIEF.values()) + "\n", path.read_text(), count=1)
    for label, lines in brief_values(info, designs).items():
        if lines:
            text = text.replace(TEMPLATE_BRIEF[label], f"- {label}: " + "\n  ".join(lines), 1)
    links = f"[spec.md]({SPEC})" + (f", its designs: [design.html]({DESIGN})" if info["design"] else "")
    text = re.sub(r"^- Spec: .*\n", "", text, flags=re.M)
    path.write_text(text.replace("## Context\n\n", f"## Context\n\n- Spec: {links}\n", 1))


def fill(path: Path, info: dict, designs: list[dict], goal: str = "", seed_line: str = "") -> None:
    """Plan the spec-state plan.md at `path` in place (D7): the template's step table (before Pre-authorized) and
    Notes, `status: open`, no review flag, the Goal when `goal` is given, the seed line when `seed_line` is, the
    Brief and the Spec line from the spec and its accepted designs. Ledgers, handoff and `grilled` stay."""
    text, template = path.read_text(), TEMPLATE.read_text()
    if "\n## Steps\n" not in text:
        steps = STEPS.search(template).group(0).rstrip("\n")
        text = text.replace("## Pre-authorized", steps + "\n\n## Pre-authorized", 1) if "## Pre-authorized" in text \
            else text.rstrip("\n") + "\n\n" + steps + "\n"
    if "\n## Notes\n" not in text:
        text = text.rstrip("\n") + "\n\n" + NOTES.search(template).group(0).rstrip("\n") + "\n"
    text = text.replace("- none: the plan is still a spec", "- none: the plan needs no user-only decision")
    if goal:
        text = GOAL.sub(lambda m: m.group(1) + goal, text, count=1)
    if seed_line:
        text = re.sub(r"^- Seed: .*\n", "", text, flags=re.M).replace("## Context\n\n", f"## Context\n\n{seed_line}\n", 1)
    path.write_text(text)
    plan_folder.write_key(path, "status", "open")
    plan_folder.write_key(path, REVIEW, None)
    seed(path, info, designs)


def review(text: str) -> int:
    """The round of the spec change a plan.md still has to review (front matter `spec_review`), 0 when none."""
    try:
        value = envelope.get(text, REVIEW)
    except envelope.FormatError:
        return 0
    return int(value) if isinstance(value, int) or str(value or "").isdigit() else 0


def review_problems(text: str, label: str) -> list[str]:
    """The `plan-spec-review` line of a plan.md whose spec changed after the plan had steps (spec.py update) and
    was not reviewed yet (spec.py reviewed)."""
    round_ = review(text)
    if not round_:
        return []
    number = Path(label).parent.name[:4].lstrip("0") or "<n>"
    return [f"{label}: the spec changed in round {round_}: review the Brief and the steps, then "
            f"`spec.py reviewed {number}` ({RULE})"]


def warnings(info: dict) -> list[str]:
    found = []
    if info["status"] != "approved":
        found.append(f"{info['folder']}/spec.md is {info['status'] or 'without a status'}, not approved")
    if info["placeholders"]:
        found.append(f"{info['folder']}/spec.md still has {len(info['placeholders'])} placeholder(s), first "
                     f"{info['placeholders'][0]}: the Brief keeps the template's text for them")
    return found


def fields(root: Path, path: Path) -> dict:
    """What `plan.py current` adds for a plan folder that holds a spec.md: its path, the accepted designs and the
    pending review round (`spec_review`, 0 without)."""
    folder = path.parent
    if not (folder / SPEC).is_file():
        return {"spec": "", "designs": [], "spec_review": 0}
    try:
        designs = accepted(root, folder)
    except (SpecLinkError, json.JSONDecodeError):
        designs = []
    return {"spec": planhome.rel(folder / SPEC, root), "designs": designs, "spec_review": review(path.read_text())}


def hint(root: Path) -> str:
    """The error for `plan.py new` (without --spec) while CURRENT_PLAN names a spec that is not planned yet (a plan
    in state spec, or a legacy spec folder without plan.md)."""
    ref = pointers.read(root, POINTER)
    folder = planhome.plans_dir(root) / ref  # the store home's view (planhome.py), else plans/
    if not FOLDER.match(ref) or not (folder / SPEC).is_file() or (folder / PLAN).exists() and not in_place(folder):
        return ""
    return (f"{PLANS}/{POINTER} names the spec {ref}, which is not planned yet: plan it in place with "
            f"`plan.py new --spec {ref[:4]}`; for an unrelated plan pass --no-spec")
