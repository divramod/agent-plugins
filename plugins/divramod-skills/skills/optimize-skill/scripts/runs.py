"""optimize-skill's run folders (plan 0390 D3, step 4). Stdlib only.

    $OPTIMIZE_SKILL_HOME (else ~/.cache/hal2/optimize-skill)/<skill>/<run id>/
        ledger.jsonl       budget.py's ledger (caps and every model call's exact usage)
        rejected.jsonl     reflect.RejectedBuffer: the edit sets the gate rejected
        candidates/<id>/   SKILL.md, edits.json, verdicts, rollouts.jsonl, scores.json (c0 is the baseline)
        reflections/<n>.md the reflection of epoch n
        report.json        loop.py's report (written while the run goes, `state` running or done)
        best.diff          the unified diff skill -> best candidate; empty when nothing beat the baseline

A run id is the start's UTC time `YYYYMMDDTHHMMSSZ` (a `-<n>` suffix when taken), so ids sort by time. Nothing here
writes into a skill's folder: `skill_name` and `diff_target` only read it.
"""

import datetime as dt
import json
import os
from pathlib import Path

import edits

HOME_ENV = "OPTIMIZE_SKILL_HOME"
DEFAULT_HOME = Path("~/.cache/hal2/optimize-skill")
REPORT = "report.json"
DIFF = "best.diff"


def home():
    return Path(os.environ.get(HOME_ENV) or DEFAULT_HOME).expanduser()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def new_run(skill, root=None):
    """Create and return a new, empty run folder of `skill`."""
    base = Path(root or home()) / skill
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base.mkdir(parents=True, exist_ok=True)
    for n in range(1, 1000):
        folder = base / (stamp if n == 1 else f"{stamp}-{n}")
        try:
            folder.mkdir()
        except FileExistsError:
            continue
        return folder
    raise RuntimeError(f"no free run id under {base}")


def runs(skill=None, root=None):
    """Every run folder (with a report) of `skill`, or of every skill, oldest first."""
    base = Path(root or home())
    skills = [base / skill] if skill else sorted(p for p in base.glob("*") if p.is_dir())
    found = [run for folder in skills if folder.is_dir() for run in folder.iterdir() if (run / REPORT).is_file()]
    return sorted(found, key=_order)


def _order(run):
    """A run id's time order: its stamp, then its `-<n>` suffix (none is 1), then the skill."""
    stamp, _, n = run.name.partition("-")
    return stamp, int(n) if n.isdigit() else 1, run.parent.name


def find(skill=None, run_id=None, root=None):
    """The run folder `run_id` of `skill` (the last one without an id), or None."""
    found = runs(skill, root)
    if run_id:
        found = [run for run in found if run.name == run_id]
    return found[-1] if found else None


def write_json(path, obj):
    """Write JSON atomically (a reader never sees half a file)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def skill_name(skill_dir):
    """The skill's front matter `name`, else its folder's name."""
    skill_dir = Path(skill_dir)
    md = skill_dir / "SKILL.md"
    names = edits.front_names(md.read_text(encoding="utf-8")) if md.is_file() else []
    return names[0] if names else skill_dir.resolve().name


def git_root(folder):
    """The nearest folder at or above `folder` holding `.git`, or None."""
    for parent in [Path(folder).resolve()] + list(Path(folder).resolve().parents):
        if (parent / ".git").exists():
            return parent
    return None


def diff_target(skill_dir):
    """(the path best.diff names, the folder to apply it in): the git root when there is one, else the skill's
    parent; apply with `git -C <folder> apply <best.diff>` (or `patch -p1 -d <folder>`)."""
    skill_md = (Path(skill_dir) / "SKILL.md").resolve()
    root = git_root(skill_md.parent) or skill_md.parent.parent
    return skill_md.relative_to(root).as_posix(), root


def inside(path, folder):
    """True when `path` is `folder` or below it."""
    return Path(path).resolve().is_relative_to(Path(folder).resolve())
