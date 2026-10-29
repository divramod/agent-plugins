"""plan.py in the store home (hal2 plan 0409 step 8; planhome.py has the view): a command renders the plans it needs
into a scratch view outside the tree, runs plan.py's own code on it (so both homes print the same), applies what it
changed and, when a step turned done or dropped, calls the store's sync trigger.

What a command needs: the plan it names (`--plan`, `use`'s plan, `--parent`, `new --spec`'s spec, `check`'s folders), the plans the
pointers name (CURRENT_PLAN, PREVIOUS_PLAN), and the masterplan each of those belongs to; `list`, `leave`, `convert`,
`new --masterplan` (its crop) and a `check` of every plan render the whole store. `new` takes its number from the store (`hal2-cli-plans new`) and
writes plan.py's template into that folder. `check` takes the records problems from the store's own check
(`hal2-cli-plans check`), the numbers need none (the store numbers them).

`edit` and `apply`, both homes: `edit [--plan]` names the folder the model edits (a step's Task, a ledger): the plan's
own in the files home, the farm's edit folder in the store home (`home --json`'s `edit`, rendered unless the copy has
edits of its own); `apply` takes that folder's edits into the store (nothing to do in the files home).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import masterplan
import planhome

EDIT_COMMANDS = ("edit", "apply")
WHOLE = ("list", "leave", "convert")
ENDS = ("done", "dropped")
_VIEW: planhome.View | None = None


def add_parsers(sub) -> None:
    p_edit = sub.add_parser("edit", help="the folder to edit a plan's files in (the store home: a copy outside the "
                                         "tree, then `apply`)")
    p_edit.add_argument("--plan")
    sub.add_parser("apply", help="take the edit folder's changes into the plan store (the files home: nothing to do)")


def wanted(root: Path, args) -> list[str] | None:
    """The plans `args` needs, None for every plan."""
    if args.command in WHOLE or (args.command == "check" and not args.folders):
        return None
    if args.command == "new" and getattr(args, "masterplan", False):
        return None  # its crop: the first no unfinished masterplan of the store uses (masterplan.used_crops)
    refs = [str(v) for v in (getattr(args, "plan", None), getattr(args, "parent", None), getattr(args, "spec", None))
            if v]
    if args.command == "check":
        refs += [Path(f).name for f in args.folders]
    refs += [planhome.pointer_slug(root), planhome.pointer_slug(root, "PREVIOUS_PLAN")]
    return [r for r in dict.fromkeys(refs) if r]


def render(view: planhome.View, refs: list[str] | None) -> None:
    folders = view.render_all() if refs is None else [f for r in refs if (f := view.render(r))]
    for folder in folders:
        plan = view.dir / folder / "plan.md"
        parent = masterplan.parent_of(plan.read_text()) if plan.is_file() else None
        if parent is not None and refs is not None:
            view.render(str(parent))


def run(root: Path, info: dict, args, dispatch) -> int:
    """`dispatch(root, args)` on a view of the store; its exit code."""
    global _VIEW
    view = _VIEW = planhome.View(root, info)
    code = 1
    try:
        render(view, wanted(root, args))
        if args.command == "check" and args.folders:
            args.folders = [view.dir / Path(f).name for f in args.folders]
        planhome.register(root, view.dir)
        code = dispatch(root, args)
    finally:
        planhome.register(root, None)
        _VIEW = None
        view.close(apply=code == 0)
    status = str(getattr(args, "status", "") or "").strip().lower()
    if code == 0 and args.command == "status" and status.startswith(ENDS):
        planhome.sync(root, "step-done")
    return code


def claim(root: Path, slug: str) -> Path:
    """A new plan's folder in the running view, numbered by the store."""
    if _VIEW is None:
        raise planhome.HomeError("no view of the plan store is open")
    return _VIEW.claim(slug)


def records(root: Path, folders: list[Path]) -> tuple[int, list[str]] | None:
    """The store's records check (`hal2-cli-plans check`) as check_records answers: (files, problem lines), only
    the named folders' when given; None when the CLI cannot say."""
    binary = planhome.cli()
    if binary is None:
        return None
    try:
        done = subprocess.run([binary, "check", "--repo", str(root), "--json"], capture_output=True, text=True,
                              timeout=planhome.TIMEOUT)
        found = json.loads(done.stdout) if done.returncode in (0, 1) and done.stdout.strip() else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if not isinstance(found, dict) or not isinstance(found.get("problems"), list):
        return None
    prefixes = tuple(f"plans/{Path(f).name}/" for f in folders)
    problems = [str(p) for p in found["problems"] if not prefixes or str(p).startswith(prefixes)]
    return int(found.get("files") or 0), problems


def on_disk(root: Path, ref: str) -> Path | None:
    """The files home's folder of the plan `ref` (a slug or a number)."""
    ref = ref.strip().rstrip("/").removesuffix("/plan.md").rsplit("/", 1)[-1]
    for folder in sorted((root / "plans").glob("[0-9][0-9][0-9][0-9]-*")):
        if folder.name == ref or (ref.isdigit() and int(folder.name[:4]) == int(ref)):
            return folder
    return None


def edit(root: Path, args) -> int:
    """`edit` / `apply` (see the module's doc); prints JSON."""
    info = planhome.home(root)
    if args.command == "apply":
        done = planhome.View(root, info, stable=True).apply() if info else None
        print(json.dumps({"home": "store" if info else "files", "applied": done}, indent=2))
        return 0
    ref = args.plan or planhome.pointer_slug(root)
    if not ref:
        raise planhome.HomeError("no plan: name it with --plan <n> (CURRENT_PLAN names none)")
    if info is None:
        folder = on_disk(root, ref)
        if folder is None:
            raise planhome.HomeError(f"no plan matches '{ref}' in plans")
        out = {"home": "files", "dir": str(folder), "apply": None}
    else:
        view = planhome.View(root, info, stable=True)
        name = view.render(ref)
        if name is None:
            raise planhome.HomeError(f"no plan matches '{ref}' in the plan store")
        out = {"home": "store", "dir": str(view.dir / name), "edited": view.edited(name),
               "apply": "python3 <plan skill>/scripts/plan.py apply"}
    print(json.dumps(out, indent=2))
    return 0
