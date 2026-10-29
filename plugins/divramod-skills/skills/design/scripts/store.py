"""The design store of a plan folder (hal2 plan 0364, D3 and D6): `plans/<plan>/design/<feat>/<kind>/v<n>/` holds a
design version's files and its `meta.json`; `plans/<plan>/design/feats.json` (a list of feat names) gives the feat
order, else the folders do. A version is never changed once a newer one exists: `new_version` copies the previous
version's files into `v<n+1>` so an update starts from the old design.

The plan folder may hold no `plan.md` (a spec-only folder, D8): its title comes from plan.md's front matter, else
spec.md's H1, else the slug. `design/state.json` (the accept toggle and the comments, D7) is only read here.
"""

import datetime as dt
import json
import re
import shutil
import sys
from pathlib import Path

POINTER = "CURRENT_PLAN"
NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
VERSION = re.compile(r"^v(\d+)$")
FOLDER = re.compile(r"^(\d{4})-(.+)$")
H1 = re.compile(r"^#\s+(.+?)\s*$", re.M)
H1_PREFIX = re.compile(r"^(?:plan|spec)\s+\d+\s*:\s*", re.I)
META = "meta.json"
# The kinds of research 0093 first, in the order a reader walks a feature; any other kind follows by name.
KIND_ORDER = ("gui", "desktop", "web", "mobile", "flow", "workflow", "erd", "uml", "scenarios", "states",
              "sequence", "context", "nfr", "threats", "rollout")


class StoreError(Exception):
    pass


def repo_root(start: Path) -> Path:
    """The nearest folder at or above `start` with a `plans/` folder or a `.git`; `start` itself without one."""
    start = start.resolve()
    for folder in (start, *start.parents):
        if (folder / "plans").is_dir() or (folder / ".git").exists():
            return folder
    return start


def current_pointer(root: Path) -> str:
    """What the checkout's CURRENT_PLAN holds: the git dir's, else the old one in `plans/` (the plan skill's pointers.py,
    found through skillpath; the plans/ file alone where this script runs outside a skills unit)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / ".claude-plugin").is_dir():
            if str(parent / "scripts") not in sys.path:
                sys.path.insert(0, str(parent / "scripts"))
            import skillpath
            return skillpath.pointers(__file__).read(root, POINTER)
    file = root / "plans" / POINTER
    return file.read_text().strip() if file.is_file() else ""


def plan_dir(root: Path, plan: str | None) -> Path:
    """The plan folder: `--plan <n|slug>`, else the slug in the `CURRENT_PLAN` pointer."""
    plans = root / "plans"
    if not plan:
        text = current_pointer(root)
        plan = text.splitlines()[0].strip() if text else ""
        if not plan:
            raise StoreError(f"no plan: pass --plan <n|slug> or name one in {plans / POINTER}")
    if plan.isdigit():
        hits = sorted(plans.glob(f"{int(plan):04d}-*"))
        hits = [h for h in hits if h.is_dir()]
        if not hits:
            raise StoreError(f"no plan folder plans/{int(plan):04d}-*")
        return hits[0]
    folder = plans / plan
    if not folder.is_dir():
        raise StoreError(f"no plan folder {folder}")
    return folder


def _front_title(text: str) -> str:
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---\n", 3)
    for line in text[4:end if end > 0 else len(text)].splitlines():
        if line.startswith("title:"):
            return line[6:].strip().strip("\"'").strip()
    return ""


def plan_info(folder: Path) -> dict:
    """The plan's number and name: plan.md's front matter `title`, else spec.md's H1, else the slug."""
    match = FOLDER.match(folder.name)
    number, slug = (match.group(1), match.group(2)) if match else ("", folder.name)
    name = ""
    plan_md, spec_md = folder / "plan.md", folder / "spec.md"
    if plan_md.is_file():
        name = _front_title(plan_md.read_text())
    if not name and spec_md.is_file():
        heading = H1.search(spec_md.read_text())
        name = H1_PREFIX.sub("", heading.group(1)).strip() if heading else ""
    return {"number": number, "slug": folder.name, "name": name or slug.replace("-", " ")}


def design_root(folder: Path) -> Path:
    return folder / "design"


def _subdirs(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return [d for d in folder.iterdir() if d.is_dir() and NAME.match(d.name)]


def feats(folder: Path) -> list[str]:
    """The feats in their order: feats.json's list first, then the remaining folders by name."""
    root = design_root(folder)
    present = sorted(d.name for d in _subdirs(root))
    order_file = root / "feats.json"
    listed = []
    if order_file.is_file():
        raw = json.loads(order_file.read_text())
        listed = [f if isinstance(f, str) else f.get("id", "") for f in raw]
    ordered = [f for f in listed if f in present]
    return ordered + [f for f in present if f not in ordered]


def kind_key(kind: str) -> tuple:
    return (KIND_ORDER.index(kind), "") if kind in KIND_ORDER else (len(KIND_ORDER), kind)


def kinds(folder: Path, feat: str) -> list[str]:
    return sorted((d.name for d in _subdirs(design_root(folder) / feat)), key=kind_key)


def versions(folder: Path, feat: str, kind: str) -> list[int]:
    base = design_root(folder) / feat / kind
    if not base.is_dir():
        return []
    found = (VERSION.match(d.name) for d in base.iterdir() if d.is_dir())
    return sorted(int(m.group(1)) for m in found if m)


def version_dir(folder: Path, feat: str, kind: str, n: int) -> Path:
    return design_root(folder) / feat / kind / f"v{n}"


def design_id(feat: str, kind: str, n: int) -> str:
    """The stable id of a design version, the key of `design/state.json` (step 2's review state)."""
    return f"{feat}/{kind}/v{n}"


def read_meta(path: Path) -> dict:
    meta = path / META
    if not meta.is_file():
        return {}
    try:
        data = json.loads(meta.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def files(path: Path) -> list[Path]:
    """A version's design files (every file but meta.json), `current.*` before `new.*`, the rest by name."""
    found = [f for f in path.iterdir() if f.is_file() and f.name != META and not f.name.startswith(".")]
    rank = {"current": 0, "new": 1}
    return sorted(found, key=lambda f: (f.suffix, rank.get(f.stem, 2), f.name))


def _check_name(what: str, value: str) -> None:
    if not NAME.match(value):
        raise StoreError(f"{what} '{value}' must be kebab-case: lowercase letters, digits and dashes")


def _add_feat(folder: Path, feat: str) -> None:
    """A new feat goes to the end of feats.json, when the plan keeps one."""
    order_file = design_root(folder) / "feats.json"
    if not order_file.is_file():
        return
    raw = json.loads(order_file.read_text())
    if feat not in [f if isinstance(f, str) else f.get("id") for f in raw]:
        order_file.write_text(json.dumps(raw + [feat], indent=2) + "\n")


def new_version(folder: Path, feat: str, kind: str, title: str = "", base: str = "",
                now: dt.datetime | None = None) -> Path:
    """Create `v<n+1>` of the feat's kind, its files copied from `v<n>`; older versions stay untouched (D6)."""
    _check_name("feat", feat)
    _check_name("kind", kind)
    existing = versions(folder, feat, kind)
    n = (existing[-1] if existing else 0) + 1
    target = version_dir(folder, feat, kind, n)
    target.mkdir(parents=True)
    previous = {}
    if existing:
        source = version_dir(folder, feat, kind, existing[-1])
        previous = read_meta(source)
        for f in files(source):
            shutil.copy2(f, target / f.name)
    stamp = (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = {"id": design_id(feat, kind, n), "feat": feat, "kind": kind, "version": n,
            "title": title or previous.get("title") or f"{feat} {kind}", "created": stamp,
            "from": f"v{existing[-1]}" if existing else None, "base": base or previous.get("base", "")}
    (target / META).write_text(json.dumps(meta, indent=2) + "\n")
    _add_feat(folder, feat)
    return target


def read_state(folder: Path) -> dict:
    """`design/state.json`'s designs (id -> {accepted, comments}); empty when missing or broken."""
    path = design_root(folder) / "state.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    designs = data.get("designs") if isinstance(data, dict) else None
    return designs if isinstance(designs, dict) else {}
