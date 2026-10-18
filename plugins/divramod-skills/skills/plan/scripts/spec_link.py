"""spec_link.py: a plan that grows from a spec and its designs (hal2 plan 0364, step 5, D10 and D14).

`plan.py new --spec <n|slug>` writes `plan.md` (and the three other records) into the spec's folder, links `spec.md` and
`design.html` under Context and seeds the Brief from the spec (In and Out from its Scope, Must from its Requirements,
Proof from its acceptance criteria) and from the accepted designs, one per feat and kind (a Must line and the Proof:
the result conforms to them). The spec comes from the spec skill's `spec.py`, the designs from the design skill's
`design.py accepted --json`, both found through `skillpath.sibling`, never by a path. `plan.py` only wires this in.

  load(root, ref)        -> (spec info, folder); refuses a folder with a plan.md, or without spec.md
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

HERE = Path(__file__).resolve().parent
PLANS = "plans"
POINTER = "CURRENT_PLAN"
SPEC, PLAN, DESIGN = "spec.md", "plan.md", "design.html"
FOLDER = re.compile(r"^(\d{4})-[a-z0-9-]+$")
BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
SCOPE = re.compile(r"^(In|Out):\s*(.*)$")
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


def load(root: Path, ref: str) -> tuple[dict, Path]:
    spec = spec_module()
    try:
        folder = spec.resolve(root, ref)
        info = spec.describe(root, folder)
    except spec.SpecError as error:
        raise SpecLinkError(str(error)) from None
    if (folder / PLAN).is_file():
        raise SpecLinkError(f"{info['folder']} already has a plan.md: continue it with `plan.py use {info['number']}`")
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
    """Rewrite a new plan.md: the Brief from the spec and the designs, the Spec line under Context."""
    text = path.read_text()
    for label, lines in brief_values(info, designs).items():
        if lines:
            text = text.replace(TEMPLATE_BRIEF[label], f"- {label}: " + "\n  ".join(lines), 1)
    links = f"[spec.md]({SPEC})" + (f", its designs: [design.html]({DESIGN})" if info["design"] else "")
    line = f"- Spec: {links}\n"
    path.write_text(text.replace("## Context\n\n", f"## Context\n\n{line}", 1))


def warnings(info: dict) -> list[str]:
    found = []
    if info["status"] != "approved":
        found.append(f"{info['folder']}/spec.md is {info['status'] or 'without a status'}, not approved")
    if info["placeholders"]:
        found.append(f"{info['folder']}/spec.md still has {len(info['placeholders'])} placeholder(s), first "
                     f"{info['placeholders'][0]}: the Brief keeps the template's text for them")
    return found


def fields(root: Path, path: Path) -> dict:
    """What `plan.py current` adds for a plan folder that holds a spec.md: its path and the accepted designs."""
    folder = path.parent
    if not (folder / SPEC).is_file():
        return {"spec": "", "designs": []}
    try:
        designs = accepted(root, folder)
    except (SpecLinkError, json.JSONDecodeError):
        designs = []
    return {"spec": str((folder / SPEC).relative_to(root)), "designs": designs}


def hint(root: Path) -> str:
    """The error for `plan.py new` (without --spec) while CURRENT_PLAN names a spec folder that has no plan yet."""
    pointer = root / PLANS / POINTER
    ref = pointer.read_text().strip() if pointer.is_file() else ""
    folder = root / PLANS / ref
    if not FOLDER.match(ref) or not (folder / SPEC).is_file() or (folder / PLAN).exists():
        return ""
    return (f"{PLANS}/{POINTER} names the spec {ref}, which has no plan yet: plan it with "
            f"`plan.py new --spec {ref[:4]}`; for an unrelated plan pass --no-spec")
