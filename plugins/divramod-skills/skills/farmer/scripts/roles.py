"""Where a role works and keeps its files (hal2's .adr/roles-folder.md, hal2 plan 0143).

A role (the farmer, lord, i, chancellor, duke, king, pope, marshall, tollman) works in the worktree and branch
`<role>-<project>` of its repository (`farmer-hal2`), so two repositories' farmers never share a session name.
`<project>` is the origin remote's repository name, else the main checkout's folder name (lowercase; other
characters than letters, digits and `-` become `-`), as hal2_git::worktree::Layout computes it. The role file is
`roles/<role>/ROLE.md` (committed) and every runtime file of the role lives beside it in the worktree's
`roles/<role>/`, ignored by the folder's own `.gitignore` (GITIGNORE). The farmer's state folder is that folder;
`FARMER_DIR` overrides it with `$FARMER_DIR/<main checkout's folder>` (tests, other machines).

The round frame (tick, wake, timer, due, acks, handoff) runs for one role, named by a `Wiring` its CLI passes down
(hal2 plan 0294, D7): `FARMER` is the farmer's and every frame function's default; another role's CLI builds its
own and passes it at every call (a call without it acts as the farmer). The duties `mtm` (the merge-to-main
boss) and `trains` are the tollman's since step 5: its skill `tollman` builds its wiring in
`tollman.py`.

`boss` names who tells a worktree to land now: the tollman's merge-to-main boss on a farm that has a working
tollman, the old line on a farm without (the farmer's sync duty, the adapt-merge-queue skill).
"""

import bounded
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

ROLES = ("farmer", "lord", "i", "chancellor", "duke", "king", "pope", "marshall", "tollman")
ROLE = "farmer"
ROLE_FILE = f"roles/{ROLE}/ROLE.md"
ROLE_IGNORE = f"roles/{ROLE}/.gitignore"
GITIGNORE = ("# The role's folder (hal2 .adr/roles-folder.md): ROLE.md is committed, every runtime file is ignored.\n"
             "*\n!.gitignore\n!ROLE.md\n")
OVERRIDE = Path(os.environ["FARMER_DIR"]) if os.environ.get("FARMER_DIR") else None
UNDER_TEST = "HAL2_ROLES_UNDER_TEST"  # set by a test's base class (test_farmer.Repo): a role's real state is off limits
LEGACY = Path.home() / "skills" / "farmer"  # the state root before plan 0143: <LEGACY>/<repo>/
BOSS = "merge-to-main boss"  # who says `land now` on a farm without a tollman
TOLLMAN_BOSS = f"tollman ({BOSS})"  # as the tollman's boss signs its messages (its boss.py)
sys.path.insert(0, next(str(_p / "scripts") for _p in Path(__file__).resolve().parents if (_p / ".claude-plugin").is_dir()))
from skillpath import sibling  # noqa: E402  (the skills unit's scripts/, plan 0360 D20)
TOLLMAN_CHECK = sibling("merge-to-main") / "scripts" / "tollman.sh"


@dataclass(frozen=True)
class Wiring:
    """What the round frame needs to know of the role it runs for. `cli` is the script the timer runs
    (`<cli> tick --repo <field>`), `skill` the folder whose instructions/ and subskills/ a woken session reads,
    `act` and `handoff` the commands typed into the role's session, `duties` the names its ROLE.md may opt in to,
    `subskills` a duty's subskill folder; `delegates`: its rounds place and follow up delegations (delegation.py);
    `carries(field)`: the role's field holds other fields' commits by design now (the tollman's while a train
    stands, hal2 plan 0294 D22), so the round neither refuses them, merges from main nor commits a role file edit;
    `session_effort`: the role's session runs at its ROLE.md's `session_effort` (default high), also after a clear
    (hal2 plan 0333 D4); `env`: the variables, besides PATH, the timer's unit passes on to the tick (plan 0311);
    `min_tick`: the shortest gap between two ticks (due.loop_cron), 5 minutes unless the role has a duty on a shorter
    cron (hal2 plan 0383 step 4: the tollman's 1-minute watch)."""
    role: str
    cli: Path
    skill: Path
    act: str
    handoff: str
    duties: tuple[str, ...]
    subskills: Mapping[str, str]
    delegates: bool = False
    carries: Callable[[str], bool] | None = None
    session_effort: bool = False
    env: tuple[str, ...] = ("FARMER_DIR",)
    min_tick: int = 5  # the shortest gap, in minutes, between two ticks the timer may run (the tollman's watch: 1)

    @property
    def role_file(self) -> str:
        return f"roles/{self.role}/ROLE.md"

    @property
    def role_files(self) -> tuple[str, str]:
        """What the role's field may change: its role file and the role folder's .gitignore."""
        return self.role_file, f"roles/{self.role}/.gitignore"


FARMER = Wiring(
    role=ROLE, cli=Path(__file__).resolve().parent / "farmer.py", skill=Path(__file__).resolve().parents[1],
    act="/farmer act", handoff="/farmer handoff",
    duties=("lead", "ci", "prs", "sync", "watch", "autoclear"),
    subskills={"lead": "development-lead", "ci": "ci", "watch": "sanity-watch", "autoclear": "fix-autoclear"},
    delegates=True)


def git(repo: str | Path, *args: str) -> str:
    try:
        p = bounded.run(["git", *args], cwd=repo)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return p.stdout.strip() if p.returncode == 0 else ""


_COMMON: dict[str, str] = {}  # a folder -> its repository's common git dir, while the folder exists
_TOP: dict[str, str] = {}  # a folder -> its checkout's top folder, while the folder exists
_ORIGIN: dict[str, str] = {}  # a main checkout -> its origin's url, while the folder exists


def folder_fact(table: dict[str, str], repo: str | Path, ask: Callable[[], str]) -> str:
    """What `ask()` (a `git rev-parse` of the folder `repo`'s place: its common git dir, its top folder) answers, ""
    outside git: asked once per folder and process while the folder exists. A round asks it for every state file it
    touches, a `git` spawn each."""
    if not repo:
        return ask()
    key = os.path.abspath(repo)
    found = table.get(key) if os.path.isdir(key) else None
    if found is None:
        found = ask()
        if found:
            table[key] = found
        else:
            table.pop(key, None)
    return found


def common_dir(repo: str | Path, ask: Callable[[], str]) -> str:
    """The absolute common git dir of the repository holding `repo` ("" outside git), `ask()` once (folder_fact)."""
    return folder_fact(_COMMON, repo, ask)


def toplevel(repo: str | Path, ask: Callable[[], str]) -> str:
    """The top folder of the checkout holding `repo` ("" outside git), `ask()` once (folder_fact)."""
    return folder_fact(_TOP, repo, ask)


def main_checkout(repo: str | Path) -> Path:
    """The main checkout of the repository containing `repo` (`repo` itself outside git)."""
    common = common_dir(repo, lambda: git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    return Path(common).parent if common else Path(repo)


def project_of(text: str) -> str | None:
    """A project name from a remote URL or a folder name: its last segment without `.git`, made a worktree name part."""
    last = re.split(r"[/:]", text.strip().rstrip("/"))[-1]
    last = last[:-4] if last.endswith(".git") else last
    name = re.sub(r"[^a-z0-9-]", "-", last.lower()).strip("-")
    return name or None


def project(repo: str | Path) -> str:
    """The repository's project name: origin's repository name, else the main checkout's folder."""
    main = main_checkout(repo)
    key = str(main)
    url = _ORIGIN.get(key) if main.is_dir() else None
    if url is None:
        url = git(main, "remote", "get-url", "origin")
        if url:
            _ORIGIN[key] = url
    return project_of(url) or project_of(main.name) or main.name


def slot_name(repo: str | Path, role: str = ROLE) -> str:
    return f"{role}-{project(repo)}"


def slot_dir(repo: str | Path, role: str = ROLE, home: Path | None = None) -> Path:
    """`~/.hal/git/worktree/<main checkout's folder>/<role>-<project>` (it may not exist)."""
    return (home or Path.home()) / ".hal/git/worktree" / main_checkout(repo).name / slot_name(repo, role)


def is_slot(top: str | Path, role: str = ROLE) -> bool:
    """Whether the checkout `top` is the repository's worktree of `role`."""
    return Path(top).name == slot_name(top, role)


class RealStateRefused(RuntimeError):
    """A test asked for a role's real state folder (hal2 plan 0412 D4)."""


def refuse_real_state(d: Path, role: str, env: Mapping[str, str] | None = None) -> None:
    """Under a test (`$HAL2_ROLES_UNDER_TEST`, inherited by the child processes a test starts) a role's state folder
    must lie under the temp dir; any other, the live `roles/<role>/` included, is refused before anything is
    created or written: a test that reaches it is a bug, never a quiet write into the live train."""
    if not (env if env is not None else os.environ).get(UNDER_TEST):
        return
    import tempfile  # only under a test: a minute pass does not load it
    temp = {Path(t).resolve() for t in (tempfile.gettempdir(), "/tmp")}
    real = d.resolve()
    if not any(t == real or t in real.parents for t in temp):
        raise RealStateRefused(f"refusing the {role} state folder {d} under a test: it is not under the temp dir "
                               f"({UNDER_TEST} is set); a test keeps its own ($FARMER_DIR, test_farmer.Repo)")


def state_dir(repo: str | Path, override: Path | None = None, role: str = ROLE) -> Path:
    """The role's state folder: `$FARMER_DIR/<repo>` with an override (another role than the farmer:
    `$FARMER_DIR/<repo>/<role>`, so two roles never share a folder), else `roles/<role>/` of the role's worktree.
    The worktree folder itself is never created here (it would block `git worktree add`): without a worktree the path is
    returned as it is, reading it finds nothing. A new role folder gets the GITIGNORE."""
    if override is not None:
        d = override / main_checkout(repo).name / ("" if role == ROLE else role)
        refuse_real_state(d, role)
        d.mkdir(parents=True, exist_ok=True)
        return d
    slot = slot_dir(repo, role)
    d = slot / "roles" / role
    refuse_real_state(d, role)
    if slot.is_dir():
        d.mkdir(parents=True, exist_ok=True)
        if not (d / ".gitignore").exists():
            (d / ".gitignore").write_text(GITIGNORE)
    return d


def boss(repo: str | Path, check: Path = TOLLMAN_CHECK) -> str:
    """Who tells a worktree of `repo` to land now (`<boss>: land now`): the tollman's boss where the farm has
    a working tollman (the mtm skill's tollman.sh prints `yes`: hal2 plan 0294, D13; the worktree's /mtm
    then reports its work ready and the tollman's train lands it), else the line every /mtm knows. Every doubt
    (no check, a failure, a slow answer) is that old line."""
    try:
        p = subprocess.run(["bash", str(check), str(repo)], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return BOSS
    return TOLLMAN_BOSS if p.returncode == 0 and p.stdout.strip() == "yes" else BOSS


def is_role_label(slot: str, role: str = ROLE) -> bool:
    """Whether an action's or the agents list's worktree label is the role's own worktree (`<role>-<project>`, or the
    unmigrated `<role>`)."""
    return slot == role or slot.startswith(role + "-")


def role_of(slot: str) -> str | None:
    """The role whose field a worktree's folder name is (`farmer-hal2`, or the unmigrated `farmer`): the longest
    role name that fits, as hal2-git's `role_of_slot`; None for every other field."""
    return max((r for r in ROLES if is_role_label(slot, r)), key=len, default=None)


def is_farmer_label(slot: str) -> bool:
    """`is_role_label` for the farmer."""
    return is_role_label(slot)
