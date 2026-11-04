#!/usr/bin/env python3
"""spec.py: the deterministic part of the spec skill (hal2 plans 0364 and 0502, D6 to D9).

A spec is a plan from its start (D7): `new` makes the numbered folder `plans/<NNNN>-<slug>/` with `plan.md` in state
`spec` (no steps yet, the Brief the spec's text) beside `spec.md`, the ledgers and the design skill's `design/` and
`design.html`. It takes its number from the plan skill's `plan_number.py` (so no plan or spec of any worktree or
branch gets it twice) and its slug by the plan skill's naming rule (`names.py`: at most four words).

  spec.py new "<title>" [--description <d>] [--seed <seedbag>#<n>] [--fetch] [--json]
                                           the plan folder, plan.md in state spec and spec.md from templates/spec.md,
                                           named in the CURRENT_PLAN pointer; --seed links and marks the seed sent
  spec.py iterate [<spec>] [--json]        one round of a draft done: iteration + 1, the Brief re-seeded; prints the
                                           checkpoint: plan now, bring in for later, another round (spec_rounds.py)
  spec.py update [<spec>] [--what <text>]  a new round on any spec, also an approved or a planned one (D6): back to
                                           draft; a plan with steps gets `spec_review` in plan.md, nothing rewritten
  spec.py reviewed [<spec>]                clear the plan's `spec_review` flag once its Brief and steps were checked
  spec.py grilled [<spec>] [--how <text>]  stamp `grilled: <date> (<how>)` on spec.md and plan.md (/grill-plan)
  spec.py abandon [<spec>]                 the spec (and its unplanned plan) abandoned; a planned one is refused
  spec.py approve [<spec>]                 status draft -> approved (refused while a placeholder of the template is left)
  spec.py show [<spec>] [--json]           a spec: its front matter, sections, placeholders left, its design.html, its
                                           plan's state and whether a review is due
  spec.py list [--json]                    every spec folder of plans/

In a farm whose plans live in its plan store (`hal2-cli-plans home` says `store`) the spec is the store's and its
copy lives outside the tree: every answer adds `dir`, the folder to edit spec.md in (store_home.py).

<spec> is a number (`365`, `0365`), a folder name or a part of its slug; without it, the CURRENT_PLAN pointer. `new` refuses
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
sys.path.insert(0, str(HERE))  # spec_plan, spec_rounds (spec_link loads this file by its path)
TEMPLATE = HERE.parent / "templates" / "spec.md"
sys.path.insert(0, next(str(_p / "scripts") for _p in HERE.parents if (_p / ".claude-plugin").is_dir()))
from skillpath import sibling  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)

sys.path.insert(0, str(sibling("plan") / "scripts"))
import envelope  # noqa: E402  (the plan skill's front matter reader)
import occupied  # noqa: E402  (a started plan keeps the field, plan 0376 D2)
import overlap  # noqa: E402  (the start paths' overlap check, plan 0593 D16)
import names  # noqa: E402  (plan-names-are-short)
import plan_number  # noqa: E402  (unique numbers across worktrees and branches)
import planhome  # noqa: E402  (files or store, hal2 plan 0409)
import pointers  # noqa: E402  (CURRENT_PLAN: the git dir's in the store home, else plans/)
import seed as seeds  # noqa: E402  (plan.py new --seed: the seed a plan grows from)
import spec_plan  # noqa: E402  (plan.md in state spec)
import spec_rounds  # noqa: E402  (iterate, update, abandon, reviewed)

PLANS = "plans"
POINTER = "CURRENT_PLAN"
SPEC = "spec.md"
PLAN = "plan.md"
DESIGN = "design.html"
FOLDER = re.compile(r"^(\d{4})-([a-z0-9-]+)$")
PLACEHOLDER = re.compile(r"<[a-z][^<>\n]*>")
STATUSES = ("draft", "approved", "abandoned")
REVIEW = spec_rounds.REVIEW


CLAIM = None  # the store home's numbering (store_home.py sets it for `new`), None in the files home


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
    """Every `plans/<NNNN>-<slug>/` holding a spec.md, by number (in the store home: of the view, planhome.py)."""
    folder = planhome.plans_dir(root)
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_dir() and FOLDER.match(p.name) and (p / SPEC).is_file())


def resolve(root: Path, ref: str | None) -> Path:
    """The spec folder `ref` names (number, folder name, slug part), else the one CURRENT_PLAN pointer names."""
    if not ref:
        ref = pointers.read(root, POINTER)
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
    rel = planhome.rel(folder, root, posix=True)
    plan = folder / PLAN
    flag = envelope.get(plan.read_text(), REVIEW) if plan.is_file() else None
    return {
        "number": folder.name[:4], "slug": folder.name, "folder": rel, "spec": f"{rel}/{SPEC}",
        "title": meta.get("title", ""), "description": meta.get("description", ""),
        "status": meta.get("status", ""), "created": str(meta.get("created", "")),
        "iteration": int(meta.get("iteration") or 0), "grilled": str(meta.get("grilled") or ""),
        "plan": f"{rel}/{PLAN}" if plan.is_file() else None, "state": spec_plan.state(folder) or None,
        "steps": spec_plan.has_steps(folder), "review": flag, "review_due": flag is not None,
        "design": f"{rel}/{DESIGN}" if (folder / DESIGN).is_file() else None,
        "sections": sections(text), "placeholders": placeholders(text),
    }


def refusals(root: Path, title: str, description: str, here: bool, seed: str) -> tuple[str, str, dict | None]:
    """Every refusal of `new`, before any number is taken: (slug, description, the seed read or None)."""
    if (found := occupied.of(root)) is not None and not here:
        raise SpecError(occupied.refuse_text(found, "spec new"))
    try:
        names.refuse(title)
    except names.NameTooLong as error:
        raise SpecError(str(error)) from None
    try:
        sown = seeds.read(root, seed) if seed else None
    except seeds.SeedError as error:
        raise SpecError(str(error), 2) from None
    slug, plans = slugify(title), planhome.plans_dir(root)
    taken = sorted(p.name for p in plans.glob(f"[0-9][0-9][0-9][0-9]-{slug}") if p.is_dir()) if plans.is_dir() else []
    if taken:
        spec_there = (plans / taken[0] / SPEC).is_file()
        hint = f"continue it with `/spec {taken[0][:4]}`" if spec_there else "a plan without a spec.md"
        raise SpecError(f"{PLANS}/{taken[0]} already exists: {hint}; pick another title")
    description = " ".join((description or f"The spec of {title}: problem, scope, requirements and acceptance "
                            "criteria before its plan.").split())
    if len(description) > 200:
        raise SpecError(f"the description has {len(description)} characters; at most 200", 2)
    if here:
        try:
            occupied.check_here(root)
        except ValueError as error:
            raise SpecError(str(error)) from None
    return slug, description, sown


def numbered_folder(root: Path, slug: str, title: str, fetch: bool) -> tuple[int, Path]:
    """The new plan's number and folder: the store's claim in the store home, else the plan skill's reservation."""
    if CLAIM is not None:
        folder = CLAIM(slug, " ".join(title.split()))
        return int(folder.name[:4]), folder
    try:
        if fetch:
            plan_number.git(root, "fetch", "--all", "--quiet")
        number = plan_number.next_number(root, slug)
    except plan_number.NumberError as error:
        raise SpecError(str(error)) from None
    folder = planhome.plans_dir(root) / f"{number:04d}-{slug}"
    if folder.exists():
        what = PLAN if (folder / PLAN).exists() else "the folder"
        raise SpecError(f"{folder.relative_to(root)}: {what} already exists; continue it with `/spec {number}`")
    return number, folder


def new(root: Path, title: str, description: str = "", fetch: bool = False, here: bool = False,
        seed: str = "") -> dict:
    """Write the plan folder (plan.md in state spec, the ledgers, spec.md) and name it in the CURRENT_PLAN pointer;
    refused before any number is taken, and in an occupied field (a started plan is current) unless `here`: the
    user's switch, the plan goes to PREVIOUS_PLAN. `seed` (`<seedbag>#<n>`) is linked into the plan and marked sent."""
    slug, description, sown = refusals(root, title, description, here, seed)
    found = overlap.scan(root, f"{title}\n{description}")  # plan 0593 D16: settled before the spec is written
    number, folder = numbered_folder(root, slug, title, fetch)  # in the store home the claim comes after every check
    title = " ".join(title.split())
    text = TEMPLATE.read_text().format(
        id=number, number=f"{number:04d}", title=title, quoted_title=envelope.quote(title),
        description=envelope.quote(description), date=dt.date.today().isoformat())
    folder.mkdir(parents=True, exist_ok=CLAIM is not None)
    (folder / SPEC).write_text(text)
    spec_plan.write(root, folder, number, title, description, seeds.context_line(sown) if sown else "")
    if here:
        try:
            occupied.switch_here(root, folder.name)
        except ValueError as error:
            shutil.rmtree(folder)
            raise SpecError(str(error)) from None
    pointers.write(root, POINTER, folder.name)
    overlap.attach(folder / spec_plan.PLAN, found)
    print(overlap.report(found, folder), file=sys.stderr)
    info = describe(root, folder)
    info["overlap"] = overlap.lines(found)
    if sown:
        info["seed"] = seeds.mark(root, sown)
    return info


def approve(root: Path, ref: str | None) -> dict:
    folder = resolve(root, ref)
    path = folder / SPEC
    text = path.read_text()
    if envelope.get(text, "status") == "abandoned":
        raise SpecError(f"{folder.name}: the spec is abandoned")
    left = placeholders(text)
    if left:
        raise SpecError(f"{folder.name}: {len(left)} placeholder(s) left, first {left[0]}: fill them before approving")
    path.write_text(envelope.set_key(text, "status", "approved"))
    return describe(root, folder)


def line(info: dict) -> str:
    plan = f"plan {info['state'] or 'without status'}" if info["plan"] else "no plan.md"
    design = info["design"] or "no design.html"
    left = f", {len(info['placeholders'])} placeholder(s) left" if info["placeholders"] else ""
    review = ", REVIEW DUE: the plan's Brief and steps" if info["review_due"] else ""
    return (f"{info['slug']}: {info['status'] or 'no status'}, round {info['iteration']}, {design}, {plan}{left}{review} "
            f"({info['spec']})")


def act(root: Path, args) -> dict:
    """The command `args` on the spec it names (spec.py's JSON answer); also what store_home.py runs on its copy."""
    if args.command == "approve":
        return approve(root, args.spec)
    if args.command == "iterate":
        return spec_rounds.iterate(sys.modules[__name__], root, args.spec)
    if args.command == "update":
        return spec_rounds.update(sys.modules[__name__], root, args.spec, args.what)
    if args.command == "abandon":
        return spec_rounds.abandon(sys.modules[__name__], root, args.spec)
    if args.command == "reviewed":
        return spec_rounds.reviewed(sys.modules[__name__], root, args.spec)
    if args.command == "grilled":
        return spec_rounds.grilled(sys.modules[__name__], root, args.spec, args.how)
    return describe(root, resolve(root, args.spec))


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="spec.py", description=__doc__.split("\n\n")[0])
    top.add_argument("--repo", help="the checkout (default: git's top level of the working directory)")
    sub = top.add_subparsers(dest="command", required=True)
    p_new = sub.add_parser("new", help="write a new plan folder with plan.md in state spec and spec.md")
    p_new.add_argument("title")
    p_new.add_argument("--description", default="")
    p_new.add_argument("--seed", default="", metavar="SEEDBAG#N", help="the seed this spec grows from (plan.py new --seed)")
    p_new.add_argument("--fetch", action="store_true", help="git fetch --all first, to see other clones' numbers")
    p_new.add_argument("--here", action="store_true", help="the user's words only: switch an occupied field")
    p_new.add_argument("--json", action="store_true")
    for name in ("show", "approve", "iterate", "update", "abandon", "reviewed", "grilled"):
        p = sub.add_parser(name)
        p.add_argument("spec", nargs="?")
        p.add_argument("--json", action="store_true")
        if name == "update":
            p.add_argument("--what", default="", help="what changed, for the commit and the review")
        if name == "grilled":
            p.add_argument("--how", default="", help="how it was grilled, e.g. 'autogrill x1'")
    sub.add_parser("list").add_argument("--json", action="store_true")
    return top


def main(argv: list[str]) -> int:
    args = parser().parse_args(argv)
    try:
        root = repo_root(args.repo)
        if (home := planhome.home(root)) is not None:
            import store_home  # noqa: PLC0415  (the store home only)
            info = store_home.run(sys.modules[__name__], root, home, args)
            if args.command == "list":
                print(json.dumps(info, indent=2) if args.json else "\n".join(map(line, info)) or "no spec in plans/")
            else:
                print(json.dumps(info, indent=2) if args.json else f"{line(info)}; edit it in {info['dir']}")
            return 0
        if args.command == "list":
            rows = [describe(root, f) for f in spec_folders(root)]
            print(json.dumps(rows, indent=2) if args.json else "\n".join(map(line, rows)) or "no spec in plans/")
            return 0
        info = new(root, args.title, args.description, args.fetch, args.here, args.seed) \
            if args.command == "new" else act(root, args)
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
