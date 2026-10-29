#!/usr/bin/env python3
"""A plan's files for reading, in either home, for the skills that read another field's plan (hal2 plan 0409 step 9:
get-state, the farmer, the tollman, transplant, spec, design; planhome.py has the homes).

- `plan_dir(root, slug)`: the folder holding the plan's files. The files home: `<root>/plans/<slug>`, the same path
  as before and no process started beyond reading the checkout's git config file (a checkout without `hal.farm` is
  always the files home). The store home: the plan rendered once per process into a scratch view outside the tree
  (never applied: a reader's copy), removed when the process ends; a plan the store lacks gives the files home's path,
  which does not exist.
- `is_store(root)`: the checkout's farm keeps its plans in the store; asked once per farm, not per field.
- `fresh()`: forget the renders and answers (a long-lived reader calls it per round).
- `registered(root)`: a context in which plan.py's own code (its `describe`) reads those copies as `plans/<...>`.
- `planread.py sync <trigger> [--root <dir>]`: the store's sync trigger for a shell script (merge-to-main's and the
  smuggle's landing end): prints the store's answer, nothing in the files home; always exit 0.
- `neutral(root)`: the farm's commits are neutral (hal2 plan 0409 D15: a Conventional head with a unit scope or none,
  no `Worktree:`/`Plan:`/`Step:` trailers; `hal2-cli-plans commits --json` says); False without `hal.farm` (no
  process) and on any failure; asked once per process and root. `planread.py neutral [--root <dir>]` prints `on` or
  `off`.
- `link_next(root, plan, step, kind)`: when neutral, names the plan and step the next commit links to
  (`hal2-cli-plans link-commit --next`, the post-commit hook links it); never raises. `planread.py link-next --root
  <dir> --plan P [--step S] [--kind K]` for a shell script.

`HAL2_CLI_PLANS` names another binary (planhome.py).
"""

from __future__ import annotations

import argparse
import atexit
import contextlib
import importlib.util
import json
import re
import sys
import threading
from pathlib import Path



def _planhome():
    """planhome.py beside this file, loaded by its path (never this folder on sys.path: a caller's modules keep their
    names); the one already loaded when plan.py's own process has it."""
    if "planhome" not in sys.modules:
        spec = importlib.util.spec_from_file_location("planhome", Path(__file__).resolve().parent / "planhome.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["planhome"] = module
        spec.loader.exec_module(module)
    return sys.modules["planhome"]


planhome = _planhome()

_KIND: dict[str, bool] = {}
_VIEWS: dict[str, planhome.View] = {}
_DIRS: dict[tuple[str, str], Path | None] = {}
_NEUTRAL: dict[str, bool] = {}
_LOCK = threading.Lock()  # get-state reads its fields' ledgers in a pool
FARM = re.compile(r"^\s*\[hal\]\s*$((?:\n(?!\s*\[).*)*)", re.M | re.I)
FARM_KEY = re.compile(r"^\s*farm\s*=\s*\"?([^\"\s#;]+)", re.M)


def git_dir(root: Path) -> Path | None:
    """The git dir of the checkout holding `root` (`.git`, or the folder a worktree's `.git` file names); None outside
    a checkout."""
    here = Path(root).resolve()
    top = next((p for p in (here, *here.parents) if (p / ".git").exists()), None)
    if top is None:
        return None
    dot = top / ".git"
    if dot.is_dir():
        return dot
    try:
        text = dot.read_text(encoding="utf-8").strip() if dot.is_file() else ""
    except OSError:
        return None
    if not text.startswith("gitdir:"):
        return None
    found = Path(text.removeprefix("gitdir:").strip())
    return found if found.is_absolute() else (top / found).resolve()


def farm_id(root: Path) -> str:
    """`hal.farm` of the checkout, read from its config files (no process); git's own answer when they include others;
    empty outside a checkout."""
    gd = git_dir(root)
    if gd is None:
        return ""
    common = gd
    if (gd / "commondir").is_file():
        common = (gd / (gd / "commondir").read_text().strip()).resolve()
    texts = []
    for config in (common / "config", gd / "config.worktree"):
        try:
            texts.append(config.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
    if any(re.search(r"^\s*\[include", t, re.M | re.I) for t in texts):
        return planhome.farm(root)
    found = ""
    for text in texts:
        for section in FARM.finditer(text):
            if (key := FARM_KEY.search(section.group(1))):
                found = key.group(1)
    return found


def is_store(root: Path) -> bool:
    """The farm of `root` keeps its plans in its store (`home --json` says `store`); False without a farm id."""
    farm = farm_id(root)
    if not farm:
        return False
    if farm not in _KIND:
        _KIND[farm] = planhome.home(Path(root)) is not None
    return _KIND[farm]


def fresh() -> None:
    """Forget what this process rendered and asked, so the next read renders again (a long-lived reader, the state
    page's server, calls it per page)."""
    with _LOCK:
        _DIRS.clear()
        _KIND.clear()
        _NEUTRAL.clear()
        planhome._HOMES.clear()


def _close() -> None:
    for view in _VIEWS.values():
        view.close(apply=False)
    _VIEWS.clear()
    _DIRS.clear()


atexit.register(_close)


def plan_dir(root: Path | str, slug: str) -> Path:
    """The folder of the plan `slug` (a folder name `<NNNN>-<slug>`) for reading; see the module's doc."""
    root = Path(root)
    on_disk = root / "plans" / slug
    if not slug or "/" in slug or not is_store(root):
        return on_disk
    farm = farm_id(root)
    key = (farm, slug)
    with _LOCK:
        return _render(root, farm, key) or on_disk


def _render(root: Path, farm: str, key: tuple[str, str]) -> Path | None:
    slug = key[1]
    if key not in _DIRS:
        view = _VIEWS.get(farm)
        if view is None:
            view = _VIEWS[farm] = planhome.View(root.resolve(), {})
        try:
            name = view.render(slug)
        except planhome.HomeError:
            name = None
        _DIRS[key] = view.dir / name if name else None
    return _DIRS[key]


@contextlib.contextmanager
def registered(root: Path | str):
    """While inside: the plan skill's own code (plan.py's `describe`) names this process's rendered plans of `root`
    as `plans/<...>` (planhome.register); nothing in the files home."""
    view = _VIEWS.get(farm_id(Path(root))) if is_store(Path(root)) else None
    before = planhome.view_of(Path(root))
    if view is not None:
        planhome.register(Path(root), view.dir)
    try:
        yield
    finally:
        if view is not None:
            planhome.register(Path(root), before)


def sync(root: Path | str | None, trigger: str) -> dict | None:
    """The store's sync trigger (planhome.sync) for the checkout `root`: its answer; None in the files home (no process
    started without a farm id) or on any failure."""
    if not root or not farm_id(Path(root)):
        return None
    return planhome.sync(Path(root).resolve(), trigger)


def neutral(root: Path | str) -> bool:
    """The commits of the checkout's farm are neutral (see the module's doc); False without a farm id (no process) and
    on any failure (no CLI, a bad answer, a non-zero exit)."""
    key = str(Path(root).resolve())
    if key not in _NEUTRAL:
        on = False
        if farm_id(Path(key)):
            try:
                on = planhome.run(Path(key), "commits", "--repo", key).get("neutral") is True
            except (planhome.HomeError, OSError, ValueError):
                on = False
        _NEUTRAL[key] = on
    return _NEUTRAL[key]


def link_next(root: Path | str, plan: str, step: str | None = None, kind: str = "step") -> bool:
    """When the commits are neutral, the next commit of `root` links to `plan` (`<NNNN>-<slug>` or its number) and
    `step`; whether the CLI recorded it. Never raises."""
    try:
        if not plan or not neutral(root):
            return False
        args = ["link-commit", "--next", "--plan", plan, "--kind", kind, "--repo", str(Path(root).resolve())]
        if step:
            args += ["--step", step]
        return planhome.run(Path(root).resolve(), *args).get("linked") is True
    except Exception:  # a link never fails a commit
        return False


def main(argv: list[str]) -> int:
    top = argparse.ArgumentParser(prog="planread.py", description=__doc__.split("\n\n")[0])
    sub = top.add_subparsers(dest="command", required=True)
    p_sync = sub.add_parser("sync", help="the store's sync trigger (nothing in the files home)")
    p_sync.add_argument("trigger", choices=planhome.TRIGGERS)
    p_sync.add_argument("--root", default=".")
    p_neutral = sub.add_parser("neutral", help="on or off: the farm's commits are neutral")
    p_neutral.add_argument("--root", default=".")
    p_link = sub.add_parser("link-next", help="the next commit links to a plan (nothing unless neutral)")
    p_link.add_argument("--root", default=".")
    p_link.add_argument("--plan", required=True)
    p_link.add_argument("--step", default="")
    p_link.add_argument("--kind", default="step", choices=["step", "handoff", "landing", "smuggle"])
    args = top.parse_args(argv)
    if args.command == "neutral":
        print("on" if neutral(args.root) else "off")
        return 0
    if args.command == "link-next":
        link_next(args.root, args.plan, args.step, args.kind)
        return 0
    done = sync(args.root, args.trigger)
    if done is not None:
        print(f"plan store sync ({args.trigger}): {json.dumps(done, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
