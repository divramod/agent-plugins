"""A red test's name to its test file, its unit and the car that touched them (hal2 plan 0714 step 1, D2-D4; tollman
learning L262, train 56-5): a train's bash, agents and python reds name their failing test only by its name, no path
(bats `not ok 3 abort keeps the queue`, unittest `FAIL: test_x (test_main.TestY.test_x)`), so early_order.py found no
car for them and every one went to the session.

- `failing`: the red text's failing tests, bats `not ok <n> <name>` (a `# skip` is no failure) and unittest
  `FAIL|ERROR: <test> (<dotted id>)`, read as early_order.red_lines reads a log (stamps and colours stripped)
- the test's file: the bats names of a red are looked up in the `.bats` files by one `git grep -nF` with a pattern per
  name (`@test "<name>"`) over the train's base and the heads of the cars that touched a `.bats` file, one process per
  red whatever its number of names and failures (D7, `prefetch`; nothing for a name no car or base holds); a
  unittest id's module (`pkg.mod.Class.test_x` is `pkg/mod.py`) is a path suffix among the cars' files, else among
  the files of the train's base (one `git ls-tree` per train); several files of that name are narrowed by the paths
  the red text names, and left alone when still several (`test_main.py` is in every python unit)
- the unit: the test file's folder `code/<lang>/<apps|libs|scripts>/<name>/`, a skill's `.../skills/<group>/<name>/`
- `owners`: the car slots whose files hold the test file, else any file of its unit (D3); early_order.cars_named adds
  them to the cars whose files the log names itself. No `repo` (no checkout given): the cars' files alone resolve
- `clues` and `mentions` (step 2, D5): what names a failing test in an order's text (the test's name or id, its test
  file, its unit folder) and whether a text does; early_order.linked uses them to join a red to the open order that
  already names its cause, even when no car's files hold the test
"""

import re
import subprocess

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import bounded
import job_error

BATS = re.compile(r"^not ok \d+ (.+?)\s*$")
SKIPPED = re.compile(r"\s#\s*(?:skip|todo)\b", re.I)
UNITTEST = re.compile(r"^(?:FAIL|ERROR): \w+ \(([\w.]+)\)")
UNIT = re.compile(r"^(code/[^/]+/(?:apps|libs|scripts)/[^/]+/)(skills/[^/]+/[^/]+/)?")
PATH = re.compile(r"[\w.@+-]+(?:/[\w.@+-]+)+\.\w+")
LIMIT = 30  # seconds for one git call: a stalled one ends the mapping, never the train
SEEN: dict = {}  # per process: (checkout, refs, what) -> answer; a ref is a commit, so an answer never goes stale


class Repo:
    """The checkout `main` and the commits a lookup reads: the train's base and the heads of cars with `.bats` files."""

    def __init__(self, main: str, base: str | None, heads: dict[str, str]):
        self.main, self.base, self.heads = main, base, heads

    def git(self, *args: str) -> list[str]:
        try:
            p = bounded.run(["git", *args], cwd=self.main, timeout=LIMIT, retry=False)
        except (OSError, subprocess.TimeoutExpired):
            return []
        return p.stdout.splitlines() if p.returncode == 0 else []

    def grep(self, names: list[str], refs: list[str]) -> dict[str, list[str]]:
        """The `.bats` files of `refs` holding each test of `names`: one `git grep -nF` for all the names not yet
        known (both quote forms of each), the hit lines telling which name a file holds; an answer is cached."""
        todo = [n for n in dict.fromkeys(names) if (self.main, tuple(refs), n) not in SEEN]
        hits: dict[str, set[str]] = {n: set() for n in todo}
        if todo and refs:
            pats = [p for n in todo for p in (f'@test "{n}"', f"@test '{n}'")]
            lines = self.git("grep", "-nF", *[x for p in pats for x in ("-e", p)], *refs, "--", "*.bats")
            for line in lines:  # <ref>:<file>:<line number>:<text>
                parts = line.split(":", 3)
                for n in todo if len(parts) == 4 else []:
                    if f'@test "{n}"' in parts[3] or f"@test '{n}'" in parts[3]:
                        hits[n].add(parts[1])
        for n in todo:
            SEEN[(self.main, tuple(refs), n)] = sorted(hits[n]) if refs else []
        return {n: SEEN[(self.main, tuple(refs), n)] for n in names}

    def tree(self) -> list[str]:
        """The files of the train's base: one `git ls-tree`."""
        key = (self.main, self.base, "tree")
        if key not in SEEN:
            SEEN[key] = self.git("ls-tree", "-r", "--name-only", self.base) if self.base else []
        return SEEN[key]


def repo(main: str | None, train: dict) -> Repo | None:
    """The lookup for `train` in the checkout `main`, or None without one."""
    if not main:
        return None
    return Repo(main, train.get("base"), {c["field"]: c["head"] for c in train.get("cars") or [] if c.get("head")})


def found(text: str | None) -> list[tuple[str, str, str]]:
    """[(kind, name, label)] of the failing tests `text` names, in order: ("bats", name, name) or
    ("module", path-without-.py, the dotted id)."""
    out = []
    for line in (text or "").splitlines():
        line = job_error.STAMP.sub("", job_error.ANSI.sub("", line.split("\t", 2)[-1]).strip())
        if (m := BATS.match(line)) and not SKIPPED.search(m.group(1)):
            out.append(("bats", m.group(1), m.group(1)))
        elif m := UNITTEST.match(line):
            parts = m.group(1).split(".")
            out.append(("module", "/".join(parts[:-2] if len(parts) > 2 else parts[:1]), m.group(1)))
    return list(dict.fromkeys(out))


def failing(text: str | None) -> list[tuple[str, str]]:
    """[("bats", name) | ("module", path-without-.py)] of the failing tests `text` names, in order."""
    return list(dict.fromkeys((kind, name) for kind, name, _ in found(text)))


def unit_of(path: str) -> str | None:
    """The unit folder of `path` (see the module doc), None for a file in no unit."""
    m = UNIT.match(path)
    return (m.group(1) + (m.group(2) or "")) if m else None


def bats_refs(rows: list[dict], repo_: Repo) -> list[str]:
    """The commits a bats name is looked up in: the base and the heads of the cars that touched a `.bats` file."""
    heads = [repo_.heads[r["slot"]] for r in rows if r["slot"] in repo_.heads
             and any(f.endswith(".bats") for f in r["files"])]
    return [x for x in [repo_.base, *heads] if x]


def module_files(module: str, rows: list[dict], repo_: Repo | None, text: str) -> list[str]:
    """The files `<module>.py` among the cars' files, else the base's, narrowed by the paths `text` names."""
    def fits(files):
        return sorted({f for f in files if f == module + ".py" or f.endswith("/" + module + ".py")})
    found = fits(f for r in rows for f in r["files"]) or (fits(repo_.tree()) if repo_ else [])
    named = {"/" + p for p in PATH.findall(text)}
    narrowed = [f for f in found if any(("/" + f).endswith(p) or p.endswith("/" + f) for p in named)]
    return narrowed or found


def prefetch(text: str | None, rows: list[dict], repo_: Repo | None) -> None:
    """Look up every bats name of the whole red `text` at once (one git process), so the per-failure lookups of a
    caller that splits the red (early_order.split) are cache hits, plan 0714 D7."""
    if repo_:
        repo_.grep([n for k, n in failing(text) if k == "bats"], bats_refs(rows, repo_))


def test_files(text: str, rows: list[dict], repo_: Repo | None) -> list[list[str]]:
    """Per failing test of `text`, the files that can hold it (see the module doc); the bats names none of the cars'
    files hold are looked up together, in one git process (none without `repo_`)."""
    tests = failing(text)
    bats = repo_.grep([n for k, n in tests if k == "bats"], bats_refs(rows, repo_)) if repo_ else {}
    return [bats.get(name, []) if kind == "bats" else module_files(name, rows, repo_, text) for kind, name in tests]


def clues(text: str | None, rows: list[dict], repo_: Repo | None = None) -> list[str]:
    """What names the failing tests of `text` in another text (see the module doc): each test's name or dotted id,
    its test files and, when it has exactly one, that file's unit folder."""
    out = [label for _, _, label in found(text)]
    for files in test_files(text or "", rows, repo_):
        out += files + ([u] if len(files) == 1 and (u := unit_of(files[0])) else [])
    return list(dict.fromkeys(out))


def mentions(why: str, clues_: list[str]) -> bool:
    """Whether `why` holds one of `clues_`: as written, or a file path the way a test runner names it (a suffix of
    the clue, `gate/test-abort.bats` for `code/bash/scripts/gate/test-abort.bats`)."""
    tails = {"/" + t for t in PATH.findall(why)}
    return any(c in why or (not c.endswith("/") and "/" in c and any(("/" + c).endswith(t) for t in tails))
               for c in clues_)


def owners(rows: list[dict], text: str | None, repo_: Repo | None = None) -> set[str]:
    """The slots of `rows` ([{slot, files}]) that own the failing tests `text` names: the cars whose files hold the
    test file, else any file of its unit (see the module doc); a test whose file is not one, or whose several files
    no car holds, owns nobody."""
    out: set[str] = set()
    for files in test_files(text or "", rows, repo_):
        held = {r["slot"] for r in rows if set(r["files"]) & set(files)}
        units = {u for f in files if (u := unit_of(f))} if len(files) == 1 else set()
        out |= held or {r["slot"] for r in rows if any(f.startswith(u) for f in r["files"] for u in units)}
    return out
