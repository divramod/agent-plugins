#!/usr/bin/env python3
"""A car's proof before it rides (hal2 plan 0333 step 4, cause A of its analysis.md): 4 of 9 red trains failed on a
check that runs in seconds in the car's own field. `trains.draft` asks `verdict` after a car's clean trial merge;
red lets it ride with the finding lines (`proof_red`), fixed in the train by its fix order (proof_orders.py; the
user, 2026-11-04: never unhitched), wait lets it ride with `proof_unknown` (plan 0610 E16: the pretest and the gate
run the checks), green lets it ride. A red line the barn's own head shows too is the barn's (`barn_red`, barn_side).

The light checks, run read-only in the field on its hitched head, as the gate runs them:
  names    the field's own `code/python/scripts/names-inventory/main.py check --branch <barn> --root <field>`
           (gate job python-lint): no old word in the prose lines the crop added
  records  `hal2-cli-records check --repo <field>` (gate job records-check; the candidate's own build when the
           field's `.hal/own-cli.sh` names one, own_cli.py), when the crop touches `plans/`,
           `.adr/`, `docs/` or a `*.md` file
  lanes    proof_lanes.check, when the crop changes a `.github/workflows/` file (plan 0490 step 7, L70): a job routed
           to runs-on labels the barn's runner list lacks rides only when a runner with them is online on GitHub
  keys, skills, env-readers, state-roots-count, nodes, state
           proof_light (plan 0490 step 8: L61, L100, L102, L119, L126), each only when the crop touches its inputs

  - A records check that refuses (exit 10: the installed checker is older than the head's `checker`, L54) is no
    proof: the car waits with the refusal line, never rides green; the verdict is not cached.

  - A field whose checkout moved on from the hitched head is proven on the hitched sha itself in a detached scratch
    worktree (proof_scratch, plan 0490 step 23, D24), with no uncommitted work; the field's checkout is never
    changed. A scratch that cannot be made: `wait` with the reason, never red, never cached. A field at its hitched
    head is proven in place (the fast path, D9).
  - A check that cannot run (its script or CLI missing, an exit other than 0 or 1, a timeout) is skipped: it never
    makes a car red, the landing's gate still runs it.
  - A finding counts only for a path the crop changed (`<barn>...<head>`) that is clean in the field: what the
    foreman did not commit is not the car's, and a red barn is not the car's either.
  - A field that is gone or cannot be read is proven on its hitched sha in the scratch made from the main checkout
    (plan 0610 E13); only without a main checkout it is `wait`.
  - The verdict is cached per `<field>:<head>` (a red one with the barn's sha: proven again once the barn moved, plan
    0610 E30) in the tollman's state folder, `cache/proof/` (the role-folder
    record's cache class: never checked, may go at any time; files older than KEEP are pruned); a verdict that left
    findings out for uncommitted work is not cached, the next round looks again.
"""

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import own_cli
import proof_lanes
import proof_light
import proof_scratch

ROLE = "tollman"
NAMES = "code/python/scripts/names-inventory/main.py"
RECORDS = ["hal2-cli-records", "check"]
DOCS = re.compile(r"^(plans/|\.adr/|docs/)|\.md$")
TIMEOUT = 300
REFUSED = 10  # hal2-cli-records: this binary is older than the repository's `checker` requirement (L54)
KEEP = 7 * 24 * 3600
SHOWN = 5  # finding lines a verdict keeps


def sh(argv: list[str], cwd: str, timeout: int = TIMEOUT) -> tuple[int, str]:
    """A command's exit and its output (stdout, then stderr); 127 when it cannot start, 124 on a timeout. No
    `__pycache__` is written into the field."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    except FileNotFoundError:
        return 127, ""
    except subprocess.TimeoutExpired:
        return 124, ""
    return p.returncode, (p.stdout + p.stderr).rstrip()  # a status line may start with a blank


def git(field: str, *args: str, run=sh) -> str:
    code, text = run(["git", *args], field)
    return text if code == 0 else ""


def changed(field: str, barn: str, head: str, run=sh) -> list[str]:
    """The paths the crop changed since it left the barn."""
    return [f for f in git(field, "diff", "--name-only", "--no-renames", f"{barn}...{head}", run=run).splitlines() if f]


def dirty(field: str, run=sh) -> set[str]:
    """The field's paths with uncommitted work: changed, staged or untracked."""
    text = git(field, "-c", "core.quotepath=false", "status", "--porcelain", "--untracked-files=all", run=run)
    return {line[3:].split(" -> ")[-1] for line in text.splitlines() if len(line) > 3}


def checks_for(files: list[str]) -> list[str]:
    """The light checks a crop's paths call for: the names check always, the records check for docs and records, the
    lanes check for a workflow, proof_light's for their inputs (the ceilings, which need the files' text: prove)."""
    return (["names"] + (["records"] if any(DOCS.search(f) for f in files) else [])
            + (["lanes"] if any(proof_lanes.WORKFLOW.match(f) for f in files) else []) + proof_light.by_path(files))


def build_run(run):
    """`run` for the own-CLI hook, which may build: the real `sh` with the longer limit, a test's fake as it is."""
    return (lambda argv, cwd: sh(argv, cwd, timeout=own_cli.BUILD)) if run is sh else run


def argv_of(check: str, field: str, barn: str, head: str = "", run=sh) -> list[str] | None:
    """The check's command in the field; None when the field has no such check (another farm) or its CLI cannot be
    had (the repository's `.hal/own-cli.sh` fails: plan 0431 D6), so the check is skipped."""
    if check == "records":
        cli = own_cli.resolve(field, RECORDS[0], barn, head, build_run(run))
        return [cli, *RECORDS[1:], "--repo", field] if cli else None
    script = Path(field) / NAMES
    return ["python3", str(script), "check", "--branch", barn, "--root", field] if script.is_file() else None


def findings(text: str, files: set[str], unclean: set[str]) -> tuple[list[str], int]:
    """The output's finding lines (`<path>:...`) for the crop's clean paths, and how many were left out for
    uncommitted work."""
    kept, dropped = [], 0
    for line in text.splitlines():
        path = line.split(":", 1)[0].strip()
        if ":" not in line or path not in files:
            continue
        if path in unclean:
            dropped += 1
        else:
            kept.append(line.strip())
    return kept, dropped


def one(check: str, field: str, barn: str, head: str, files: list[str], run, grew=None) -> tuple[int, str]:
    """One check's (exit, output) in the field."""
    if check == "lanes":
        return proof_lanes.check(field, barn, head, files, run)
    if check not in ("names", "records"):
        return proof_light.check(check, field, barn, head, files, run, build_run(run), grew)
    argv = argv_of(check, field, barn, head, run=run)
    return run(argv, field) if argv else (127, "")


def prove(field: str, head: str, barn: str, run=sh, clean: bool = False) -> dict:
    """The checks on a checkout at the hitched head (the field, or a `clean` scratch with no uncommitted work, so no
    status is read), uncached: {state, lines, checks, skipped, dropped}."""
    files = changed(field, barn, head, run=run)
    names, unclean = set(files), set() if clean else dirty(field, run=run)
    out = {"state": "green", "lines": [], "checks": [], "skipped": [], "dropped": 0}
    grew, refused = proof_light.ceilings(field, barn, head, files, run), []
    for check in checks_for(files) + list(grew):
        code, text = one(check, field, barn, head, files, run, grew.get(check))
        if check == "records" and code == REFUSED:
            first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
            refused.append(f"no proof yet: the records check refused (exit {REFUSED}, the installed checker is older "
                           f"than the head's `checker`; install the newer hal2-cli-records): {first}"[:400])
            continue
        if code not in (0, 1):
            out["skipped"].append(check)
            continue
        out["checks"].append(check)
        kept, dropped = findings(text, names, unclean) if code == 1 else ([], 0)
        out["lines"] += [f"{check}: {line}" for line in kept]
        out["dropped"] += dropped
    out["state"] = "red" if out["lines"] else "wait" if refused else "green"
    out["lines"] = (out["lines"] or refused)[:SHOWN]
    out["files"] = files  # what barn_side compares against the barn's own head
    return out


def cache_dir(main: str) -> Path:
    return mtm_scan.state_dir(main, ROLE) / "cache" / "proof"


def cache_file(cache: Path, field: str, head: str) -> Path:
    key = f"{field}:{head}"
    return cache / (hashlib.sha256(key.encode()).hexdigest()[:24] + ".json")


def cached(cache: Path, field: str, head: str, base: str | None = None) -> dict | None:
    """The kept verdict of `field:head`; a red one, or one with `barn_red`, only while the barn is at `base` still
    (plan 0610 E30: a red the barn fixed later is proven again; the barn's own red is the barn's of that head only)."""
    try:
        got = json.loads(cache_file(cache, field, head).read_text())
    except (OSError, ValueError):
        return None
    if got.get("key") != f"{field}:{head}" or ((got.get("state") == "red" or got.get("barn_red"))
                                                and got.get("base") != base):
        return None
    return got


def keep(cache: Path, field: str, head: str, v: dict, now: float | None = None) -> None:
    """The verdict written through a temp file and a rename; old ones pruned. A cache never fails a round."""
    try:
        cache.mkdir(parents=True, exist_ok=True)
        tag = cache.parent / "CACHEDIR.TAG"
        if not tag.exists():
            tag.write_text("Signature: 8a477f597d28d172789f06886806bc55\n# the tollman's cache (proof.py)\n")
        now = now or time.time()
        for f in cache.glob("*.json"):
            if now - f.stat().st_mtime > KEEP:
                f.unlink()
        target = cache_file(cache, field, head)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps({"schema": 1, "key": f"{field}:{head}", **v}) + "\n")
        tmp.replace(target)
    except OSError:
        pass


def verdict(main: str, field: str, head: str, barn: str, run=sh, cache: Path | None = None) -> dict:
    """Whether the car `field` (its worktree) may ride with its hitched `head`: {state: green | red | wait, lines,
    checks, barn_red, ...}. `run` and `cache` are the commands and the state folder's cache unless a test says
    otherwise. A field that is gone or unreadable is proven on its hitched sha in the scratch made from the main
    checkout (plan 0610 E13); a red is checked against the barn's own head (`barn_side`)."""
    at = git(field, "rev-parse", "HEAD", run=run) if Path(field).is_dir() else ""
    repo = field if at else main if main and Path(main).is_dir() else ""
    if not repo:
        return {"state": "wait", "lines": [f"no proof yet: the field is not readable, its hitched head {head[:12]}"],
                "checks": []}
    cache = cache or cache_dir(main)
    name, base = Path(field).name, git(repo, "rev-parse", barn, run=run)
    if (hit := cached(cache, name, head, base)) is not None:
        return hit
    if at == head:
        v = prove(field, head, barn, run=run)
    else:  # the foreman committed on after the hitch, or the field is gone: the hitched sha in a scratch (D24)
        v = proof_scratch.prove(repo, head, barn, cache.parent / "scratch",
                                lambda root, h, b: prove(root, h, b, run=run, clean=True))
    if v["state"] == "red" and base:
        v = barn_side(repo, base, v, cache, run)
    if v["state"] == "red" or (v["state"] == "green" and not v.get("dropped")):  # a refusal is looked at again
        keep(cache, name, head, {**v, "base": base})
    return v


def barn_side(repo: str, base: str, v: dict, cache: Path, run=sh) -> dict:
    """Field 79 row 13 (plan 0610 D18): the car's red lines that the barn's own head `base` shows too (the same
    finding, e.g. a key clash the barn holds on all six cars) are the barn's, `barn_red`, never the car's: its fix is
    the barn's own order (trains.train_actions). The red checks run again in the scratch at the barn's head over the
    crop's paths; a check that reads only what the crop added (`names`, the ceilings) is the car's. A car with no
    line left is green."""
    checks = sorted({ln.split(":", 1)[0] for ln in v["lines"]} - {"names", *proof_light.CEILINGS})
    files = v.get("files") or []
    if not checks or not files:
        return v
    tag = "barn-" + hashlib.sha256(json.dumps([checks, files]).encode()).hexdigest()[:16]
    if (got := cached(cache, tag, base, base)) is None:
        def at_barn(root: str, sha: str, _barn: str) -> dict:
            lines = []
            for check in checks:
                code, text = one(check, root, sha, sha, files, run)
                lines += [f"{check}: {ln}" for ln in findings(text, set(files), set())[0]] if code == 1 else []
            return {"state": "red" if lines else "green", "lines": lines}
        got = proof_scratch.prove(repo, base, base, cache.parent / "scratch", at_barn)
        if got["state"] != "wait":
            keep(cache, tag, base, {**got, "base": base})
    seen = set(got["lines"]) if got["state"] != "wait" else set()
    if not (theirs := [ln for ln in v["lines"] if ln in seen]):
        return v
    mine = [ln for ln in v["lines"] if ln not in seen]
    return {**v, "state": "red" if mine else "green", "lines": mine, "barn_red": theirs}
