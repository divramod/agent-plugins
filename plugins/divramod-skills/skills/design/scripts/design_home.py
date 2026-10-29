"""design.py in a farm whose plans live in its plan store (hal2 plan 0409 step 9, design §1: a plan's designs are the
store's docs; the plan skill's planhome.py has the views).

The plan folder design.py works on is then a copy outside the tree: the farm's edit folder (`home --json`'s `edit`, a
stable view that keeps a copy with edits of its own), the plan rendered there from the store. Its paths are absolute,
so the model writes a version's files where `new` prints them; every command that ends well applies the copy back
(the model's own edits of it too), and the review server applies after each saved accept or comment. `design.py
apply` applies the copy after the model's edits alone. In the files home `folder` is None and nothing here runs.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import load  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)

import store  # noqa: E402

planhome = load("plan", "planhome", __file__)
_VIEWS: list = []
_LOCK = threading.Lock()


def folder(root: Path, plan: str | None) -> Path | None:
    """The plan's folder in the store home's edit copy; None in the files home."""
    info = planhome.home(root)
    if info is None:
        return None
    ref = plan or planhome.pointer_slug(root)
    if not ref:
        raise store.StoreError("no plan: pass --plan <n|slug> or name one in the CURRENT_PLAN pointer")
    view = planhome.View(root, info, stable=True)
    try:
        name = view.render(ref)
    except planhome.HomeError as error:
        raise store.StoreError(str(error)) from None
    if not name:
        raise store.StoreError(f"no plan {ref} in the plan store")
    _VIEWS.append(view)
    return view.dir / name


def apply() -> None:
    """Apply every copy this process opened; a records problem the copy adds is a StoreError."""
    with _LOCK:
        for view in _VIEWS:
            try:
                done = view.apply()
            except planhome.HomeError as error:
                raise store.StoreError(f"the plan store: {error}") from None
            refused = (done or {}).get("refused") or []
            if refused:
                raise store.StoreError(f"the plan store refused the copy in {view.dir}: {'; '.join(map(str, refused))}")


def follow(review) -> None:
    """The review server's saves go into the store as they happen."""
    write = review.write

    def write_and_apply(at: Path, data: dict) -> None:
        write(at, data)
        apply()

    review.write = write_and_apply
