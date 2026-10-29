"""spec.py in a farm whose plans live in its plan store (hal2 plan 0409 step 9, design §1: a spec's files are the
store's docs; the plan skill's planhome.py has the views).

spec.py's own code runs unchanged on two copies outside the tree: the whole store rendered into a scratch view to
find and list the specs (never applied), and the farm's edit folder (`home --json`'s `edit`, a stable view: a copy
with edits of its own is kept) holding the spec it writes. `new` numbers the spec by the store (`hal2-cli-plans new`,
the plan's plan.md then removed: a spec folder has none), `approve` sets its status; both apply the copy back, so
the model's own edits of spec.md in that copy go in too. Every answer adds `dir`, the copy's folder: the model edits
spec.md there and runs `spec.py show` (or `approve`) to apply it.
"""

from __future__ import annotations

from pathlib import Path

import planhome


def apply(view: planhome.View, spec) -> None:
    done = view.apply()
    refused = (done or {}).get("refused") or []
    if refused:
        raise spec.SpecError(f"the plan store refused the spec's copy: {'; '.join(map(str, refused))} (fix the copy "
                             f"in {view.dir} and run spec.py show)")


def run(spec, root: Path, info: dict, args):
    """The command `args` on the store's copies: spec.py's JSON answer (a list for `list`)."""
    scratch = planhome.View(root, info)
    try:
        scratch.render_all()
        planhome.register(root, scratch.dir)
        if args.command == "list":
            return [spec.describe(root, f) for f in spec.spec_folders(root)]
        stable = planhome.View(root, info, stable=True)
        if args.command == "new":
            slug = spec.slugify(args.title)
            taken = [f for f in scratch.folders() if f[5:] == slug]
            if taken:
                raise spec.SpecError(f"{spec.PLANS}/{taken[0]} already exists in the plan store: continue it with "
                                     f"`/spec {taken[0][:4]}`; pick another title")
            if (current := planhome.pointer_slug(root)):
                stable.render(current)  # the occupied check reads the current plan
            planhome.register(root, stable.dir)
            spec.CLAIM = lambda name, title: unplanned(stable.claim(name, title))
            found = spec.new(root, args.title, args.description, False, args.here)
        else:
            name = spec.resolve(root, args.spec).name
            stable.render(name)
            planhome.register(root, stable.dir)
            found = spec.approve(root, name) if args.command == "approve" else spec.describe(root, stable.dir / name)
        apply(stable, spec)
        return {**found, "dir": str(stable.dir / found["slug"])}
    except planhome.HomeError as error:
        raise spec.SpecError(str(error)) from None
    finally:
        spec.CLAIM = None
        planhome.register(root, None)
        scratch.close(apply=False)


def unplanned(folder: Path) -> Path:
    """A claimed plan's folder without its plan.md (a spec folder before its plan)."""
    (folder / "plan.md").unlink(missing_ok=True)
    return folder
