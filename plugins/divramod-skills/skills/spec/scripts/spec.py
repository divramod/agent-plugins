#!/usr/bin/env python3
"""spec.py: the deterministic part of the spec skill (hal2 plan 0364, step 4, D8 and D9).

A spec is a plan folder before its plan: `plans/<NNNN>-<slug>/spec.md` (and the design skill's `design/` and
`design.html`), no `plan.md`. It takes its number from the plan skill's `plan_number.py` (so no plan or spec of any
worktree or branch gets it twice) and its slug by the plan skill's naming rule (`names.py`: at most four words).

  spec.py new "<title>" [--description <d>] [--fetch] [--json]   write plans/<NNNN>-<slug>/spec.md from
                                                                  templates/spec.md and name it in plans/CURRENT_PLAN
  spec.py show [<spec>] [--json]                                  a spec: its front matter, sections, placeholders
                                                                  left, its design.html and whether it has a plan.md
  spec.py list [--json]                                           every spec folder of plans/
  spec.py approve [<spec>]                                        status draft -> approved (refused while a
                                                                  placeholder of the template is left)

<spec> is a number (`365`, `0365`), a folder name or a part of its slug; without it, plans/CURRENT_PLAN. `new` refuses
a title of more than four words and a slug a folder of plans/ already has. `--repo <dir>` names the checkout (default:
git's top level of the working directory). Exit 0 ok, 1 refused or not found, 2 bad arguments or git missing.
"""
import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "templates" / "spec.md"
sys.path.insert(0, next(str(_p / "scripts") for _p in HERE.parents if (_p / ".claude-plugin").is_dir()))
from skillpath import sibling  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)

sys.path.insert(0, str(sibling("plan") / "scripts"))
import envelope  # noqa: E402  (the plan skill's front matter reader)
import names  # noqa: E402  (plan-names-are-short)
import plan_number  # noqa: E402  (unique numbers across worktrees and branches)

PLANS = "plans"
POINTER = "CURRENT_PLAN"
SPEC = "spec.md"
PLAN = "plan.md"
DESIGN = "design.html"
FOLDER = re.compile(r"^(\d{4})-([a-z0-9-]+)$")
PLACEHOLDER = re.compile(r"<[a-z][^<>\n]*>")
STATUSES = ("draft", "approved")


class SpecError(Exception):
    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


def repo_root(repo: str | None) -> Path:
    if repo:
        return Path(repo).resolve()
    if shutil.which("git") is None:
        raise SpecError("git is missing: run check-prerequisites.sh", 2)
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if out.returncode != 0 or not out.stdout.strip():
        raise SpecError("not inside a git repository: pass --repo <dir>", 2)
    return Path(out.stdout.strip()).resolve()


def slugify(title: str) -> str:
    """The plan skill's slug of a title (plan.py's slugify): lower case, kebab, at most 60 characters."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not slug:
        raise SpecError("the title needs at least one letter or digit", 2)
    return slug[:60].rstrip("-")


def spec_folders(root: Path) -> list[Path]:
    """Every `plans/<NNNN>-<slug>/` holding a spec.md, by number."""
    folder = root / PLANS
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_dir() and FOLDER.match(p.name) and (p / SPEC).is_file())


def resolve(root: Path, ref: str | None) -> Path:
    """The spec folder `ref` names (number, folder name, slug part), else the one plans/CURRENT_PLAN names."""
    if not ref:
        pointer = root / PLANS / POINTER
        ref = pointer.read_text().strip() if pointer.is_file() else ""
        if not ref:
            raise SpecError(f"no spec named and {PLANS}/{POINTER} is missing or empty: name one (spec.py list)")
    ref = ref.strip().rstrip("/").removeprefix(f"{PLANS}/").removesuffix(f"/{SPEC}")
    found = spec_folders(root)
    exact = [p for p in found if p.name == ref or (ref.isdigit() and int(ref) == int(p.name[:4]))]
    loose = exact or [p for p in found if ref in p.name[5:]]
    if len(loose) == 1:
        return loose[0]
    if not loose:
        raise SpecError(f"no spec matches '{ref}' in {PLANS}/ (a folder holding {SPEC})")
    raise SpecError(f"'{ref}' matches several specs: {', '.join(p.name for p in loose)}")


def template_placeholders() -> set[str]:
    _, body = envelope.split(TEMPLATE.read_text())
    return set(PLACEHOLDER.findall(re.sub(r"<!--.*?-->", "", body, flags=re.S)))


def placeholders(text: str) -> list[str]:
    """The template's placeholders still in the spec's body, in order (a `<plan>` the user wrote is not one)."""
    _, body = envelope.split(text)
    known = template_placeholders()
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    return [p for p in PLACEHOLDER.findall(body) if p in known]


def sections(text: str) -> dict[str, str]:
    _, body = envelope.split(text)
    return {name: envelope.section(body, name).strip() for name in envelope.headings(body, 2)}


def describe(root: Path, folder: Path) -> dict:
    text = (folder / SPEC).read_text()
    front, _ = envelope.split(text)
    meta = envelope.parse(front) if front is not None else {}
    rel = folder.relative_to(root).as_posix()
    return {
        "number": folder.name[:4], "slug": folder.name, "folder": rel, "spec": f"{rel}/{SPEC}",
        "title": meta.get("title", ""), "description": meta.get("description", ""),
        "status": meta.get("status", ""), "created": str(meta.get("created", "")),
        "approved": str(meta["approved"]) if "approved" in meta else None,
        "plan": f"{rel}/{PLAN}" if (folder / PLAN).is_file() else None,
        "design": f"{rel}/{DESIGN}" if (folder / DESIGN).is_file() else None,
        "sections": sections(text), "placeholders": placeholders(text),
    }


def new(root: Path, title: str, description: str = "", fetch: bool = False) -> dict:
    """Write the spec folder and name it in plans/CURRENT_PLAN; refused before any number is taken."""
    try:
        names.refuse(title)
    except names.NameTooLong as error:
        raise SpecError(str(error)) from None
    slug = slugify(title)
    plans = root / PLANS
    taken = sorted(p.name for p in plans.glob(f"[0-9][0-9][0-9][0-9]-{slug}") if p.is_dir()) if plans.is_dir() else []
    if taken:
        spec_there = (plans / taken[0] / SPEC).is_file()
        hint = f"continue it with `/spec {taken[0][:4]}`" if spec_there else "a folder without spec.md"
        raise SpecError(f"{PLANS}/{taken[0]} already exists: {hint}; pick another title")
    try:
        if fetch:
            plan_number.git(root, "fetch", "--all", "--quiet")
        number = plan_number.next_number(root, slug)
    except plan_number.NumberError as error:
        raise SpecError(str(error)) from None
    folder = plans / f"{number:04d}-{slug}"
    if folder.exists():
        what = PLAN if (folder / PLAN).exists() else "the folder"
        raise SpecError(f"{folder.relative_to(root)}: {what} already exists; continue it with `/spec {number}`")
    description = " ".join((description or f"The spec of {title}: problem, scope, requirements and acceptance "
                            "criteria before its plan.").split())
    if len(description) > 200:
        raise SpecError(f"the description has {len(description)} characters; at most 200", 2)
    text = TEMPLATE.read_text().format(
        id=number, number=f"{number:04d}", title=" ".join(title.split()), quoted_title=envelope.quote(title),
        description=envelope.quote(description), date=dt.date.today().isoformat())
    folder.mkdir(parents=True)
    (folder / SPEC).write_text(text)
    (plans / POINTER).write_text(folder.name + "\n")
    return describe(root, folder)


def approve(root: Path, ref: str | None) -> dict:
    folder = resolve(root, ref)
    path = folder / SPEC
    text = path.read_text()
    left = placeholders(text)
    if left:
        raise SpecError(f"{folder.name}: {len(left)} placeholder(s) left, first {left[0]}: fill them before approving")
    text = envelope.set_key(text, "status", "approved")
    path.write_text(envelope.set_key(text, "approved", dt.date.today().isoformat()))
    return describe(root, folder)


def line(info: dict) -> str:
    plan = "plan.md" if info["plan"] else "no plan.md"
    design = info["design"] or "no design.html"
    left = f", {len(info['placeholders'])} placeholder(s) left" if info["placeholders"] else ""
    return f"{info['slug']}: {info['status'] or 'no status'}, {design}, {plan}{left} ({info['spec']})"


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="spec.py", description=__doc__.split("\n\n")[0])
    top.add_argument("--repo", help="the checkout (default: git's top level of the working directory)")
    sub = top.add_subparsers(dest="command", required=True)
    p_new = sub.add_parser("new", help="write a new spec folder")
    p_new.add_argument("title")
    p_new.add_argument("--description", default="")
    p_new.add_argument("--fetch", action="store_true", help="git fetch --all first, to see other clones' numbers")
    p_new.add_argument("--json", action="store_true")
    for name in ("show", "approve"):
        p = sub.add_parser(name)
        p.add_argument("spec", nargs="?")
        p.add_argument("--json", action="store_true")
    sub.add_parser("list").add_argument("--json", action="store_true")
    return top


def main(argv: list[str]) -> int:
    args = parser().parse_args(argv)
    try:
        root = repo_root(args.repo)
        if args.command == "list":
            rows = [describe(root, f) for f in spec_folders(root)]
            print(json.dumps(rows, indent=2) if args.json else "\n".join(map(line, rows)) or "no spec in plans/")
            return 0
        if args.command == "new":
            info = new(root, args.title, args.description, args.fetch)
        elif args.command == "approve":
            info = approve(root, args.spec)
        else:
            info = describe(root, resolve(root, args.spec))
    except SpecError as error:
        print(f"spec.py: {error}", file=sys.stderr)
        return error.code
    except envelope.FormatError as error:
        print(f"spec.py: the spec's front matter: {error}", file=sys.stderr)
        return 1
    print(json.dumps(info, indent=2) if args.json else line(info))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
