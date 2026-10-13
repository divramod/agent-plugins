"""Plan names are short (the global record plan-names-are-short): the slug after a plan's number has at most four
words; a research plan's `research-` does not count. `plan.py new` refuses a longer title, `plan.py check` reports a
longer slug of a plan that has not landed (its plan file is not on the default branch; without one, only the current
plan counts). Landed plans keep their names."""
import re
import subprocess
from pathlib import Path

MAX_WORDS = 4
RESEARCH = "research"
NUMBER = re.compile(r"^\d{4}-")
RULE = "plan-names-are-short"


class NameTooLong(Exception):
    pass


def words(name: str, numbered: bool = False) -> list[str]:
    """The words of a title, or of a slug with its number (`numbered`: `0293-brief-and-sprout`); a leading
    `research` does not count."""
    found = re.sub(r"[^a-z0-9]+", "-", NUMBER.sub("", name.lower()) if numbered else name.lower()).strip("-").split("-")
    found = [w for w in found if w]
    return found[1:] if found[:1] == [RESEARCH] else found


def too_long(name: str, numbered: bool = False) -> bool:
    return len(words(name, numbered)) > MAX_WORDS


def message(name: str, numbered: bool = False) -> str:
    return (f"a plan name has at most {MAX_WORDS} words (record {RULE}; a research plan's `{RESEARCH}-` does not "
            f"count): '{name}' has {len(words(name, numbered))}: shorten it and put the rest into the goal")


def refuse(title: str) -> None:
    """Raise NameTooLong for a title whose slug would have more than four words."""
    if too_long(title):
        raise NameTooLong(message(title))


def git_ok(root: Path, *args: str) -> bool:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True).returncode == 0
    except OSError:
        return False


def default_ref(root: Path) -> str | None:
    """`origin/<default branch>`, or None without such a remote-tracking branch."""
    out = subprocess.run(["git", "symbolic-ref", "-q", "refs/remotes/origin/HEAD"], cwd=root,
                         capture_output=True, text=True) if git_ok(root, "rev-parse") else None
    if out is not None and out.returncode == 0 and out.stdout.strip():
        return out.stdout.strip().removeprefix("refs/remotes/")
    for name in ("origin/main", "origin/master"):
        if git_ok(root, "rev-parse", "--verify", "-q", name):
            return name
    return None


def problems(root: Path, plans: list[Path], current: str, slug_of) -> list[str]:
    """One line per plan file in `plans` with a too long slug that has not landed: not on the default branch, or
    (no such branch) not the current plan, which is the only one known to be unlanded."""
    long = [p for p in plans if too_long(slug_of(p), True)]
    if not long:
        return []
    ref, found = default_ref(root), []
    for path in long:
        slug = slug_of(path)
        if ref is None:
            if slug != current:
                continue
        elif git_ok(root, "cat-file", "-e", f"{ref}:{path.resolve().relative_to(root.resolve()).as_posix()}"):
            continue
        found.append(f"{path.resolve().relative_to(root.resolve())}: {message(slug, True)} (rename its folder, "
                     f"plans/CURRENT_PLAN and links)")
    return found
