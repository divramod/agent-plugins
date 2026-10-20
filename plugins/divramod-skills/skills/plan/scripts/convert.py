"""`plan.py convert <plan>... | --all [--dry-run] [--json]`: every old plan into the one plan shape (hal2 plan 0376,
design §7, §8, A11, A12, A14; D16), idempotent, one line per plan: `converted`, `skipped <why>` (convert_skip.py),
or `failed <why>`: a plan whose conversion or check fails is put back exactly and nothing of it is staged.

Per plan: plan.md (convert_plan.py), the step table into sub-plan 01 (convert_steps.py), uat.md and its results
into 99-uat (convert_uat.py), the plan folder's other Markdown re-pointed at the moved files, the overview and the
derived statuses written (shape.write_overview), `finished` and the ledgers' `closed` set when the plan is `uat` or
`done`; then `plan.py check`'s schema 2 rules (shape_check.py) and, when the installed hal2-cli-records is 0.7.0 or
newer, its findings on the folder. The result is staged (`git add -A -- <folder>`, so the moves show as renames).
`--dry-run` converts a copy in a temp folder and reports what would happen. `plan.py -g convert --all` first writes
a tar backup of the global plans folder into hal2's state root (`$HAL2_STATE_DIR`, `$XDG_STATE_HOME/hal2`,
`~/.local/state/hal2`).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

import checker
import convert_plan
import convert_skip
import convert_steps
import convert_text as text
import convert_uat
import envelope
import folder as plan_folder
import shape
import shape_check
import shape_new
from shape_names import ShapeError

ERRORS = (ShapeError, envelope.FormatError, ValueError, KeyError, OSError)


def add_parser(sub) -> None:
    p = sub.add_parser("convert", help="old plans into the one plan shape (schema 2), idempotent")
    p.add_argument("plans", nargs="*", help="plans by slug or number")
    p.add_argument("--all", action="store_true", help="every plan of the plans folder")
    p.add_argument("--dry-run", action="store_true", help="convert copies in a temp folder; write nothing")
    p.add_argument("--json", action="store_true")


def repoint(folder: Path, steps: dict[str, str], moves: dict[str, str]) -> None:
    """The plan folder's Markdown outside `subplans/`: `steps/<id>.md` mentions and links to moved files."""
    for path in sorted(folder.rglob("*.md")):
        rel = path.relative_to(folder).as_posix()
        if rel.startswith(f"{shape.SUBPLANS}/"):
            continue
        here = Path(rel).parent.as_posix()
        here = "" if here == "." else here
        old = path.read_text()
        new = text.rewrite_links(text.rewrite_mentions(old, here, steps), here, here, moves)
        if new != old:
            path.write_text(new)


def stamp(root: Path, folder: Path, finished: str | None) -> str:
    """`finished` exactly while the plan is `uat` or `done` (then its open ledgers `closed`); the status."""
    path = folder / "plan.md"
    status = str(envelope.get(path.read_text(), "status"))
    if status in ("uat", "done"):
        if not envelope.get(path.read_text(), "finished"):
            date = finished or convert_plan.git_date(root, path, False) or dt.date.today().isoformat()
            plan_folder.write_key(path, "finished", date[:10])
        for name in plan_folder.SIBLINGS:
            other = folder / name
            if other.is_file() and envelope.get(other.read_text(), "status") == "open":
                plan_folder.write_key(other, "status", "closed")
    elif status == "open" and envelope.get(path.read_text(), "finished"):
        plan_folder.write_key(path, "finished", None)
    return status


def convert_folder(root: Path, folder: Path) -> dict:
    """Convert the plan `folder` in place; its result without the check."""
    original = (folder / "plan.md").read_text()
    plan = convert_plan.convert(root, folder)
    number = int(folder.name[:4])
    steps = convert_steps.convert(folder, number, plan["title"], plan["goal"], original, shape_new.run_words(folder))
    uat = convert_uat.convert(folder, number, plan["title"])
    repoint(folder, steps["steps"], {**steps["moves"], convert_uat.UAT: f"{convert_uat.HOME}/subplan.md"})
    overview = shape.write_overview(root, folder)
    status = stamp(root, folder, plan["finished"])
    return {"from": "record" if plan["record"] else "legacy", "status": status, "subplan": steps["subplan"],
            "steps": len(steps["steps"]), "moved": len(steps["moves"]), "checks": uat["checks"],
            "verdicts": uat["verdicts"], "legacy_md": bool(plan.get("legacy")), "scaffolded": plan["scaffolded"],
            "overview": overview, "notes": steps["notes"]}


def records_problems(root: Path, folder: Path, where: str) -> tuple[list[str], str | None]:
    """hal2-cli-records' findings on the folder when it is 0.7.0 or newer; else why they are not run. `where`:
    `repo`, `global` (no repository) or `dry` (a temp copy)."""
    skip = shape_check.records_skip([folder])
    if checker.binary() is None:
        return [], checker.NOT_INSTALLED
    if skip or where != "repo":
        return [], skip or f"records unchecked: {'a dry run' if where == 'dry' else 'the global folder'}"
    result = checker.check(repo=root.resolve())
    prefix = f"{folder.resolve().relative_to(root.resolve()).as_posix()}/"
    return [checker.line(p) for p in (result or {}).get("problems", []) if p["path"].startswith(prefix)], None


def checked(root: Path, folder: Path, where: str) -> tuple[dict | None, list[str], str | None]:
    try:
        result = convert_folder(root, folder)
    except ERRORS as error:
        return None, [f"{type(error).__name__}: {error}"], None
    problems = shape_check.problems(root, folder)
    found, note = records_problems(root, folder, where) if not problems else ([], None)
    return result, problems + found, note


def dry(root: Path, plan_md: Path, use_git: bool) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "plans" / plan_md.parent.name
        shutil.copytree(plan_md.parent, copy)
        result, problems, note = checked(Path(tmp), copy, "dry")
    out = {"result": "would fail" if problems else "would convert", **(result or {}), "records": note}
    return {**out, "problems": problems} if problems else out


def one(root: Path, plan_md: Path, use_git: bool) -> dict:
    """Convert one plan in place; put it back exactly when it fails."""
    folder = plan_md.parent
    with tempfile.TemporaryDirectory() as tmp:
        backup = Path(tmp) / folder.name
        shutil.copytree(folder, backup, symlinks=True)
        result, problems, note = checked(root, folder, "repo" if use_git else "global")
        if problems:
            shutil.rmtree(folder)
            shutil.copytree(backup, folder, symlinks=True)
            return {"result": "failed", "problems": problems, "put_back": True}
    if use_git:
        subprocess.run(["git", "add", "-A", "--", str(folder)], cwd=root, capture_output=True)
    return {"result": "converted", **result, "records": note}


def state_root() -> Path:
    if os.environ.get("HAL2_STATE_DIR"):
        return Path(os.environ["HAL2_STATE_DIR"])
    if os.environ.get("XDG_STATE_HOME"):
        return Path(os.environ["XDG_STATE_HOME"]) / "hal2"
    return Path.home() / ".local" / "state" / "hal2"


def backup(plans: Path) -> Path:
    """A tar.gz of the global plans folder in `<state root>/plans-backup/`."""
    out = state_root() / "plans-backup" / f"{plans.name}-{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}.tar.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out, "w:gz") as tar:
        tar.add(plans, arcname=plans.name)
    return out


def line(entry: dict) -> str:
    why = entry.get("why") or "; ".join(entry.get("problems", []))
    tail = " (put back)" if entry.get("put_back") else ""
    return f"{entry['result']} {entry['plan']}" + (f": {why}" if why else "") + tail


def run(root: Path, args, plan_files, resolve, use_git: bool = True, plans_dir: Path | None = None) -> int:
    """The command: `plan_files(root)` every plan.md, `resolve(root, ref)` one; `plans_dir` the global folder."""
    if bool(args.all) == bool(args.plans):
        raise ShapeError("convert takes plans by slug or number, or --all (not both)")
    targets = plan_files(root) if args.all else [resolve(root, ref) for ref in args.plans]
    skips = convert_skip.SkipSet.read(root) if use_git else convert_skip.SkipSet(root)
    out = {"plans": [], "backup": None}
    if plans_dir is not None and not args.dry_run:
        out["backup"] = str(backup(plans_dir))
    for plan_md in targets:
        entry = {"plan": plan_md.parent.name if plan_md.name == "plan.md" else plan_md.stem}
        why = skips.why(plan_md, explicit=not args.all)
        if why:
            entry.update(result="skipped", why=why)
        else:
            entry.update(dry(root, plan_md, use_git) if args.dry_run else one(root, plan_md, use_git))
        out["plans"].append(entry)
    for word in ("converted", "skipped", "failed", "would convert", "would fail"):
        out[word.replace(" ", "_")] = sum(1 for e in out["plans"] if e["result"] == word)
    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print("\n".join([line(e) for e in out["plans"]] + ([f"backup: {out['backup']}"] if out["backup"] else [])))
    return 1 if out["failed"] or out["would_fail"] else 0
