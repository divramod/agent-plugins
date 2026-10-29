"""Where a checkout's plans live, files or store (hal2 plan 0409 step 8, design §3 and §6, A8 and A11).

The files home is today's: `plans/<NNNN>-<slug>/` in the checkout, and nothing here runs a process beyond one `git
config` (a checkout without `hal.farm` never asks the CLI). In the store home (`hal2-cli-plans home --json` says
`store`) no plan file is in the tree: a script works on a **view**, the plans it needs rendered by `hal2-cli-plans
render --to <dir>` into a folder outside the tree; it runs its own code on that folder unchanged, and the view is
applied back (`apply`) when a file changed. The pointers (CURRENT_PLAN, PREVIOUS_PLAN, LEAD) stay in the checkout's
`plans/` (hal2 plan 0409 step 12 moves them).

- `home(root)`: the CLI's `home --json` answer when the farm's home is the store, else None (the files home).
- `View(root, info)`: a scratch view (a fresh folder, removed by `close`), for one script run.
- `View(root, info, stable=True)`: the farm's edit folder (`home --json`'s `edit`, `<state root>/plans/<farm>/<branch>/`)
  where the model edits a step's Task, a handoff, the ledgers; it is rendered again only while the copy has no edit
  of its own (`.hal-view.json` keeps each file's hash at its render), and `apply` takes the edits in.
- `register(root, dir)` / `plans_dir(root)` / `rel(path, root)`: the scripts find the plan folders below `plans_dir`
  and print their paths as `plans/<...>` in either home.
- `sync(root, trigger)`: the sync trigger after a step ends, a handoff is written or a landing ends (`sync --if-due`;
  a landing's end first marks the fragments its CHANGELOG.md took in: `landed`); it never fails the caller.

`HAL2_CLI_PLANS` names another binary (a hal2 worktree's debug build, a test's).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ENV = "HAL2_CLI_PLANS"
NAME = "hal2-cli-plans"
CHANGELOG_ENV = "HAL2_CLI_CHANGELOG"
CHANGELOG = "hal2-cli-changelog"
SNAPSHOT = ".hal-view.json"
BASE = ".base.json"
TIMEOUT = 120
TRIGGERS = ("step-done", "handoff", "landing")

_VIEWS: dict[Path, Path] = {}
_HOMES: dict[Path, dict | None] = {}


class HomeError(Exception):
    pass


def cli() -> str | None:
    """The CLI: `$HAL2_CLI_PLANS` when it names a file, else the one on PATH; None when neither."""
    named = os.environ.get(ENV, "").strip()
    if named:
        return named if Path(named).expanduser().is_file() else None
    return shutil.which(NAME)


def farm(root: Path) -> str:
    """The checkout's farm id (`hal.farm` of its git config); empty without one."""
    try:
        done = subprocess.run(["git", "-C", str(root), "config", "--get", "hal.farm"], capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def run(root: Path, *args: str) -> dict:
    """The CLI's JSON answer to `args` in the checkout `root`; HomeError with its message when it fails."""
    binary = cli()
    if binary is None:
        raise HomeError(f"{NAME} is not installed: the plans of this farm live in its store")
    try:
        done = subprocess.run([binary, *args, "--json"], cwd=root, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError) as error:
        raise HomeError(f"{NAME} {' '.join(args)}: {error}") from error
    try:
        answer = json.loads(done.stdout) if done.stdout.strip() else {}
    except ValueError:
        answer = {}
    if done.returncode != 0:
        message = (answer.get("error") or {}).get("message") if isinstance(answer, dict) else None
        error = HomeError(message or done.stderr.strip() or f"{NAME} {' '.join(args)} exited {done.returncode}")
        error.code = done.returncode
        raise error
    return answer if isinstance(answer, dict) else {"items": answer}


def home(root: Path) -> dict | None:
    """`home --json` of the checkout's farm when its home is the store; None for the files home (no farm id, no
    store, no CLI or an answer it cannot give: the files are read as before)."""
    key = Path(root).resolve()
    if key not in _HOMES:
        info = None
        if farm(key):
            try:
                answer = run(key, "home", "--repo", str(key))
            except HomeError:
                answer = {}
            info = answer if answer.get("home") == "store" and answer.get("edit") else None
        _HOMES[key] = info
    return _HOMES[key]


def register(root: Path, folder: Path | None) -> None:
    """The plan folders of `root` are below `folder` (a view) from now on; None: the checkout's `plans/` again."""
    key = Path(root).resolve()
    if folder is None:
        _VIEWS.pop(key, None)
    else:
        _VIEWS[key] = Path(folder)


def view_of(root: Path) -> Path | None:
    return _VIEWS.get(Path(root).resolve())


def plans_dir(root: Path) -> Path:
    """The folder holding the plan folders of `root`: its view's in the store home, else `root/plans`."""
    return view_of(root) or Path(root) / "plans"


def rel(path: Path, root: Path, posix: bool = False) -> str:
    """`path` as the checkout names it: `plans/<...>` for a file of the view, else relative to `root` (`/`-separated
    with `posix`, else the system's separator, as `str(path.relative_to(root))`)."""
    view = view_of(root)
    if view is not None:
        try:
            return (Path("plans") / Path(path).relative_to(view)).as_posix()
        except ValueError:
            pass
    found = Path(path).relative_to(root)
    return found.as_posix() if posix else str(found)


def inside(path: Path, root: Path) -> bool:
    """`path` is below `root`, or below its view."""
    view = view_of(root)
    return Path(path).is_relative_to(root) or (view is not None and Path(path).is_relative_to(view))


def store_note(root: Path, number: str) -> str:
    """For a subagent's prompt in the store home: where the plan's files are (a copy, then `apply`); empty else."""
    if view_of(root) is None:
        return ""
    plan = Path(__file__).resolve().parent / "plan.py"
    return (f" The plan's files live in the farm's plan store, not under plans/: `python3 {plan} edit --plan {number}`"
            " names the folder holding a copy of them (the paths above are below it); write your step file there and "
            f"run `python3 {plan} apply` after each write.")


def digest(folder: Path) -> dict[str, str]:
    """Each file below `folder` (a plan folder) by its path and sha256."""
    out = {}
    for path in sorted(folder.rglob("*")) if folder.is_dir() else []:
        if path.is_file():
            out[path.relative_to(folder).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


class View:
    """The plans of a store-home checkout rendered outside the tree; see the module's doc."""

    def __init__(self, root: Path, info: dict, stable: bool = False):
        self.root, self.info, self.stable = Path(root).resolve(), info, stable
        if stable:
            self.dir = Path(info["edit"])
            self.dir.mkdir(parents=True, exist_ok=True)
        else:
            self.dir = Path(tempfile.mkdtemp(prefix="hal2-plans-view-"))
        self.snap = self.read_snapshot()

    def read_snapshot(self) -> dict:
        try:
            return json.loads((self.dir / SNAPSHOT).read_text())
        except (OSError, ValueError):
            return {}

    def write_snapshot(self) -> None:
        (self.dir / SNAPSHOT).write_text(json.dumps(self.snap, sort_keys=True))

    def folders(self) -> list[str]:
        return sorted(p.name for p in self.dir.iterdir() if p.is_dir() and p.name[:4].isdigit())

    def edited(self, folder: str) -> bool:
        """The copy of `folder` holds an edit not applied yet (its files differ from their render)."""
        return folder in self.snap and digest(self.dir / folder) != self.snap[folder]

    def render(self, ref: str) -> str | None:
        """Render the plan `ref` (a number or a slug) into the view; its folder, None when the store has no such plan.
        A stable view keeps a copy with edits of its own as it is."""
        ref = str(ref).strip().rstrip("/").removesuffix("/plan.md").rsplit("/", 1)[-1]
        if not ref:
            return None
        known = [f for f in self.folders() if f == ref or (ref.isdigit() and int(f[:4]) == int(ref))]
        if known and self.edited(known[0]):
            return known[0]
        try:
            done = run(self.root, "render", ref, "--to", str(self.dir), "--repo", str(self.root))
        except HomeError as error:
            if getattr(error, "code", 1) == 3:
                return None
            raise
        folder = str(done.get("folder") or "")
        if folder:
            self.snap[folder] = digest(self.dir / folder)
            self.write_snapshot()
        return folder or None

    def render_all(self) -> list[str]:
        done = run(self.root, "render", "--all", "--to", str(self.dir), "--repo", str(self.root))
        folders = [str(f) for f in done.get("plans") or []]
        for folder in folders:
            self.snap[folder] = digest(self.dir / folder)
        self.write_snapshot()
        return folders

    def claim(self, slug: str, title: str = "") -> Path:
        """A new plan `<NNNN>-<slug>` numbered by the store (`hal2-cli-plans new`, titled `title`, else the slug),
        rendered: its folder in the view."""
        made = run(self.root, "new", title or slug, "--no-current", "--repo", str(self.root))
        if title and str(made.get("slug") or "")[5:] != slug:
            raise HomeError(f"{NAME} new {title!r} made {made.get('slug')}, not <NNNN>-{slug}")
        folder = self.render(str(made.get("slug") or ""))
        if not folder:
            raise HomeError(f"{NAME} new {slug}: no plan to render")
        return self.dir / folder

    def changed(self) -> list[str]:
        """The folders whose files differ from their render (a new or removed file counts)."""
        return [f for f in self.folders() if digest(self.dir / f) != self.snap.get(f)]

    def apply(self) -> dict | None:
        """Apply the view's edits to the store (nothing to do: None); the store's answer. Refused: HomeError."""
        if not self.changed() or not (self.dir / BASE).is_file():
            return None
        done = run(self.root, "apply", str(self.dir), "--repo", str(self.root))
        for folder in self.folders():
            self.snap[folder] = digest(self.dir / folder)
        self.write_snapshot()
        return done

    def close(self, apply: bool = True) -> dict | None:
        """Apply (unless told not to) and, for a scratch view, remove its folder."""
        try:
            return self.apply() if apply else None
        finally:
            if not self.stable:
                shutil.rmtree(self.dir, ignore_errors=True)


def _pointers():
    """pointers.py beside this file, loaded by its path: planread loads this module by path, so the plan folder is not
    on sys.path here."""
    if "pointers" not in sys.modules:
        spec = importlib.util.spec_from_file_location("pointers", Path(__file__).resolve().parent / "pointers.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["pointers"] = module
        spec.loader.exec_module(module)
    return sys.modules["pointers"]


def pointer_slug(root: Path, name: str = "CURRENT_PLAN") -> str:
    """The plan slug a pointer of the checkout names; empty for a shot, a task or no pointer."""
    text = _pointers().read(root, name)  # the git dir's, else plans/
    first = text.split()[0] if text.split() else ""
    return first if len(first) > 5 and first[:4].isdigit() and first[4] == "-" and "/" not in first else ""


def landed(root: Path) -> list[str] | None:
    """A landing's end in the store home: the fragments the landed CHANGELOG.md holds marked with its commit
    (`hal2-cli-changelog landed`, `$HAL2_CLI_CHANGELOG` names another binary); the plans marked, None when it cannot
    say (no CLI, a failure)."""
    named = os.environ.get(CHANGELOG_ENV, "").strip()
    binary = named if named and Path(named).expanduser().is_file() else (None if named else shutil.which(CHANGELOG))
    if binary is None:
        return None
    try:
        done = subprocess.run([binary, "landed", "--json"], cwd=root, capture_output=True, text=True, timeout=TIMEOUT)
        answer = json.loads(done.stdout) if done.returncode == 0 and done.stdout.strip() else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return [str(p) for p in answer.get("landed") or []] if isinstance(answer, dict) else None


def sync(root: Path, trigger: str) -> dict | None:
    """The store's sync trigger (`sync --if-due <trigger>`): its answer, None in the files home or on any failure. At a
    landing's end it first marks the landed fragments (`landed`; the answer's `fragments_landed`)."""
    if trigger not in TRIGGERS or home(root) is None:
        return None
    marked = landed(Path(root)) if trigger == "landing" else None
    try:
        answer = run(Path(root), "sync", "--if-due", trigger, "--repo", str(root))
    except HomeError:
        return None
    return {**answer, "fragments_landed": marked} if marked else answer
