#!/usr/bin/env python3
"""Find a sibling skill from a script of another skill, in the flat layout (`skills/<name>/`: installed, published)
and in the category layout (`skills/<category>/<name>/`: the source). Plan 0360, decision D20.

  from skillpath import sibling
  CREATE = sibling("create-worktree-session") / "scripts" / "create.py"

A caller finds this folder by walking up to the nearest `.claude-plugin/` and putting its `scripts/` on sys.path:

  for _p in Path(__file__).resolve().parents:
      if (_p / ".claude-plugin").is_dir():
          sys.path.insert(0, str(_p / "scripts")); break

`sibling(name)` looks in the calling skill's own parent folder first, then in `<skills root>/*/<name>`, then in
`<skills root>/<name>`; a folder counts when it holds a SKILL.md. It raises FileNotFoundError naming the skill.
"""
from pathlib import Path


def unit_root(start) -> Path | None:
    """The nearest parent of `start` holding `.claude-plugin/` (the skills unit, or its published copy)."""
    here = Path(start).resolve()
    for parent in [here, *here.parents]:
        if (parent / ".claude-plugin").is_dir():
            return parent
    return None


def repo_root(start) -> Path | None:
    """The nearest parent of `start` holding `.git` (a folder, or a file in a worktree), at any depth."""
    here = Path(start).resolve()
    for parent in [here, *here.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def skills_root(start) -> Path | None:
    unit = unit_root(start)
    return unit / "skills" if unit else None


def own_skill(start) -> Path | None:
    """The skill folder (nearest parent holding SKILL.md) that `start` lies in."""
    here = Path(start).resolve()
    for parent in here.parents:
        if (parent / "SKILL.md").is_file():
            return parent
    return None


def candidates(name: str, start) -> list[Path]:
    found = []
    own = own_skill(start)
    if own is not None:
        found.append(own.parent / name)
    root = skills_root(start)
    if root is not None and root.is_dir():
        found += sorted(root.glob(f"*/{name}"))
        found.append(root / name)
    return found


def sibling(name: str, start=None) -> Path:
    """The folder of the skill `name`, as seen from the script `start` (default: the calling script)."""
    if start is None:
        import inspect
        start = inspect.stack()[1].filename
    for path in candidates(name, start):
        if (path / "SKILL.md").is_file():
            return path
    raise FileNotFoundError(f"skill '{name}' not found beside or under the skills root of {start}")


def load(skill: str, module: str, start=None):
    """The module `module` of the skill `skill`'s scripts/, loaded by its path under its own name (once: sys.modules),
    never by putting that folder on sys.path, so the caller's own modules keep their names; None when the skill or
    the file is missing (a copied script outside a skills unit). `load("plan", "planread")`: plan files in either
    home (hal2 plan 0409 step 9)."""
    import importlib.util
    import sys
    if module in sys.modules:
        return sys.modules[module]
    if start is None:
        import inspect
        start = inspect.stack()[1].filename
    try:
        path = sibling(skill, start) / "scripts" / f"{module}.py"
    except FileNotFoundError:
        return None
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(module, path)
    found = importlib.util.module_from_spec(spec)
    sys.modules[module] = found
    try:
        spec.loader.exec_module(found)
    except Exception:
        del sys.modules[module]
        raise
    return found



class _TreePointers:
    """The plan skill's pointers.py when it is missing (a copied script outside a skills unit): the files home only."""

    @staticmethod
    def path(root, name):
        return Path(root) / "plans" / name

    @classmethod
    def exists(cls, root, name):
        return cls.path(root, name).is_file()

    @classmethod
    def read(cls, root, name):
        try:
            return cls.path(root, name).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            return ""

    @classmethod
    def remove(cls, root, name):
        cls.path(root, name).unlink(missing_ok=True)

    @classmethod
    def write(cls, root, name, text):
        cls.path(root, name).write_text(text.rstrip("\n") + "\n", encoding="utf-8")
        return cls.path(root, name)

    target = path


def pointers(start=None):
    """The plan skill's `pointers` module (a checkout's CURRENT_PLAN, PREVIOUS_PLAN, LEAD in the git dir, else
    plans/; hal2 plan 0409 step 12): `pointers().read(root, "LEAD")`; the files home's bare stand-in without it."""
    if start is None:
        import inspect
        start = inspect.stack()[1].filename
    return load("plan", "pointers", start) or _TreePointers


if __name__ == "__main__":
    import sys
    print(sibling(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else __file__))
