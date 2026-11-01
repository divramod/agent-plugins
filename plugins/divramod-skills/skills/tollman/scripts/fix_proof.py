#!/usr/bin/env python3
"""A fix order's answer proven green (hal2 plan 0522 step 3, D5): `orders.fixed` takes a `fixed <sha>` only when the
order's red jobs are green on that sha; the foreman's word alone let records-check go red four times (train 32).

- the jobs: the order line's `jobs`, given by `order --job` or named in its `why`, else in the train's red (`named`):
  gate job names, a CI job's display name bared (stack_red.bare: `c2-03-lint`, `linux / rust-test`), CI's folded
  `lint` as the light lint jobs (gate/lint-jobs.txt)
- light (a job of `.github/hal2-pretest.toml`): the tollman runs it itself on the sha, pretest.py's run with only
  those jobs, in the proof worktree `cache/proof/.proof-tree` of its role folder (detached at the sha; its build
  output stays warm for the next proof), the result in `cache/proof/<id>-<sha12>.json`, the jobs' output beside it
  (`.log`). The round starts a proof detached (`start`, one at a time: busy exits OFFLINE, so the next round tries
  again) and accepts on a later round; the manual `tollman.py fixed` runs it at once. Green (a job the range does not
  select is green: CI runs it neither) accepts; red refuses with the job's first error line; incomplete starts it
  again, up to TRIES times, then refuses; skipped (a tool missing, a job that changed tracked files) refuses: the
  session decides
- heavy (every other job): the answer carries the gate's line `gate: <job> green at <sha>` (gate/main.sh prints it
  after a green job) for that job, on the sha or a commit of its tree; an order that names no job needs such a line
  for some job
- `fixed --unproven <why>`: the session's word without proof (a red that is another car's, a red of the Mac's)

  fix_proof.py start --repo <carrier> <order id> <sha>    the proof, detached (the round's action)
  fix_proof.py run --repo <carrier> [--try <n>] <order id> <sha>   the proof, in the foreground
"""

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import bounded
import mtm_scan
import pretest
import stack_red
import train_state
from tick import OFFLINE, default_ref

CLI = Path(__file__).resolve()
FOLDER = Path("cache/proof")
TREE = ".proof-tree"  # a dot name: worktree listings leave it out (mtm_scan.py, as .deliver and .bench)
TRIES = 3  # incomplete proofs of one answer before it is refused
KEEP_DAYS = 14
LINT_JOBS = "code/bash/scripts/gate/lint-jobs.txt"
GREEN = re.compile(r"gate: ([a-z0-9][a-z0-9-]*) green at ([0-9a-f]{7,40})")
TOKEN = re.compile(r"[a-z0-9][a-z0-9-]*")
LIGHT_OK = ("green", "none")


def light_jobs(top: str) -> tuple[dict | None, list[str]]:
    cfg, _ = pretest.read_config(Path(top) / pretest.CONFIG)
    return cfg, list(cfg["jobs"]) if cfg else []


def known_jobs(top: str) -> set[str]:
    """The gate's jobs (`gate list`), else the pretest config's (no gate here)."""
    with contextlib.suppress(OSError, RuntimeError, subprocess.SubprocessError):
        return pretest.gate_jobs(top, Path(top) / pretest.GATE, 60)
    return set(light_jobs(top)[1])


def named(top: str, *texts: str) -> list[str]:
    """The gate jobs the first of `texts` names that names any (CI's `lint`: the light lint jobs), in order."""
    known, light = known_jobs(top), light_jobs(top)[1]
    try:
        lint = [x.strip() for x in (Path(top) / LINT_JOBS).read_text().splitlines() if x.strip()[:1] not in ("", "#")]
    except OSError:
        lint = []
    for text in texts:
        found: list[str] = []
        for token in TOKEN.findall(str(text or "").lower()):
            job = stack_red.bare(token)
            found += [j for j in lint if j in light] if job == pretest.LINT else [job] * (job in known)
        if found:
            return list(dict.fromkeys(found))
    return []


def path(main: str, oid: str, sha: str, ending: str = ".json") -> Path:
    return train_state.folder(main) / FOLDER / f"{oid}-{sha[:12]}{ending}"


def read(main: str, oid: str, sha: str) -> dict | None:
    try:
        return json.loads(path(main, oid, sha).read_text())
    except (OSError, ValueError):
        return None


def write(main: str, oid: str, sha: str, doc: dict) -> None:
    p = path(main, oid, sha)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"schema": 1, **doc}) + "\n")
    os.replace(tmp, p)


def running(doc: dict | None) -> bool:
    return bool(doc and doc.get("state") == "running" and mtm_scan.pid_alive(doc.get("pid")))


def busy(main: str) -> bool:
    """Whether a proof runs now (one at a time: they share the proof worktree)."""
    folder = train_state.folder(main) / FOLDER
    for f in folder.glob("*.json") if folder.is_dir() else []:
        with contextlib.suppress(OSError, ValueError):
            if running(json.loads(f.read_text())):
                return True
    return False


def tree_of(top: str, rev: str) -> str:
    return pretest.git(top, "rev-parse", f"{rev}^{{tree}}")


def lines_for(top: str, sha: str, note: str) -> set[str]:
    """The jobs whose green line in `note` is on `sha` (or a commit of its tree)."""
    tree = tree_of(top, sha)
    return {job for job, at in GREEN.findall(note or "") if sha.startswith(at) or (tree and tree_of(top, at) == tree)}


def heavy_why(top: str, sha: str, heavy: list[str], note: str, any_job: bool) -> str:
    """What the answer's lines lack for the heavy jobs (`any_job`: the order names none), or ""."""
    green = lines_for(top, sha, note)
    if any_job:
        return "" if green else (f"no proof: the answer carries no `gate: <job> green at {sha[:12]}` line; run the red "
                                 "job on the fix (`code/bash/scripts/gate/main.sh <job> --branch origin/main`) and "
                                 f"answer `done fixed {sha[:12]}: <that line>`")
    missing = [j for j in heavy if j not in green]
    return "" if not missing else (
        f"no proof for {', '.join(missing)}: run {'each' if len(missing) > 1 else 'it'} on the fix "
        f"(`code/bash/scripts/gate/main.sh <job> --branch origin/main`) and answer `done fixed {sha[:12]}: "
        f"gate: {missing[0]} green at {sha[:12]}` (the line the gate prints)")


def verdict(top: str, main: str, o: dict, sha: str, note: str = "") -> tuple[str, str]:
    """`ok`, `no` (why), `wait` (the proof runs) or `start` (no proof yet, or one to start again) for `sha` answering
    the order `o`; the heavy lines first, then the light proof."""
    jobs, light = o.get("jobs") or [], light_jobs(top)[1]
    mine = [j for j in jobs if j in light]
    if why := heavy_why(top, sha, [j for j in jobs if j not in light], note, not jobs):
        return "no", why
    if not mine:
        return "ok", ""
    doc = read(main, o["id"], sha)
    if running(doc):
        return "wait", f"the proof of {', '.join(mine)} on {sha[:12]} runs"
    state = (doc or {}).get("state")
    if state in LIGHT_OK:
        return "ok", ""
    if state == "red":
        errors = doc.get("errors") or {}
        reds = [f"{j}: {errors.get(j) or 'red'}" for j in mine if j in errors] or [doc.get("why") or "red"]
        return "no", f"red on {sha[:12]} in the tollman's own run: {'; '.join(reds)}"[:600]
    if state == "refused":
        return "no", doc.get("why") or "refused"
    if state == "skipped":
        why = doc.get("why") or "a job was skipped"
        return "no", f"not proven on {sha[:12]}: {why} (the tollman's session decides)"
    if state in ("incomplete", "running", "broken") and doc.get("attempt", 0) >= TRIES:
        return "no", f"not proven on {sha[:12]}: {doc.get('why') or state} ({TRIES} tries)"
    return "start", f"the proof of {', '.join(mine)} on {sha[:12]} starts"


def attempt(main: str, oid: str, sha: str) -> int:
    return (read(main, oid, sha) or {}).get("attempt", 0)


def order_of(main: str, oid: str) -> dict | None:
    train = train_state.standing(train_state.lines(main)) or {}
    return next((o for o in train.get("orders", []) + train.get("post", []) if o["id"] == oid), None)


def spawn(argv: list[str], out: Path, cwd: str) -> int:
    """`argv` in a session of its own (no parent waits), its output in `out`: its pid."""
    with out.open("w") as f:
        return subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT,
                                start_new_session=True).pid


def start(top: str, main: str, oid: str, sha: str) -> int:
    """The proof started detached; OFFLINE while another one runs (the next round tries again). The result says
    `running` before the child starts (this pid), the child's own pid once it runs (`run`), never after it ended."""
    if busy(main):
        print(f"a proof runs: {oid} {sha[:12]} waits for the next round")
        return OFFLINE
    n = attempt(main, oid, sha) + 1
    write(main, oid, sha, {"state": "running", "attempt": n, "pid": os.getpid(), "at": train_state.utc()})
    pid = spawn([sys.executable, str(CLI), "run", "--repo", top, "--try", str(n), oid, sha],
                path(main, oid, sha, ".out"), top)
    print(f"the proof of {oid} on {sha[:12]} runs (pid {pid}, try {n})")
    return 0


def ok(cwd: str, *args: str) -> bool:
    try:
        return bounded.run(["git", *args], cwd=cwd).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def checkout(top: str, tree: Path, sha: str) -> str:
    """The proof worktree detached at `sha` (made, or made again when it does not switch), or why not. It holds only
    a commit the order's check found on origin or on the tollman's own branch, never work of its own."""
    want = pretest.git(top, "rev-parse", f"{sha}^{{commit}}")
    if (tree / ".git").exists() and ok(str(tree), "checkout", "-q", "--detach", "--force", sha):
        return ""
    ok(top, "worktree", "remove", "--force", str(tree))
    ok(top, "worktree", "prune")
    tree.parent.mkdir(parents=True, exist_ok=True)
    ok(top, "worktree", "add", "-q", "--detach", "--force", str(tree), sha)
    return "" if want and pretest.git(str(tree), "rev-parse", "HEAD") == want else \
        f"the proof worktree {tree} does not check out {sha[:12]}"


def prove(top: str, main: str, jobs: list[str], sha: str, log: Path) -> dict:
    """pretest.pretest of `jobs` on `sha` in the proof worktree: its result (the state its `result`)."""
    cfg, _ = light_jobs(top)
    tree = train_state.folder(main) / FOLDER / TREE
    if why := checkout(top, tree, sha):
        return {"result": "broken", "why": why, "jobs": [], "errors": {}}
    with tempfile.TemporaryDirectory(prefix="proof-") as scratch:
        config = Path(scratch) / "hal2-pretest.toml"
        groups = cfg.get("groups") or {}
        config.write_text(f"budget = {cfg['budget']}\nparallel = {cfg['parallel']}\n" + "".join(
            f'\n[[job]]\nname = "{j}"\n' + (f'group = "{groups[j]}"\n' if j in groups else "") for j in jobs))
        return pretest.pretest(str(tree), train_state.folder(main), default_ref(top), log, config)


def run(top: str, main: str, oid: str, sha: str, n: int | None = None) -> int:
    """The proof in the foreground (`n`: its try, else the next): its result written; 0 green."""
    prune(train_state.folder(main) / FOLDER)
    o, n = order_of(main, oid), n or attempt(main, oid, sha) + 1
    if not o:
        write(main, oid, sha, {"state": "broken", "attempt": n, "why": f"no open fix order {oid}"})
        return 1
    import orders  # (orders imports this module)

    if why := orders.check(top, o, sha):  # fetched, on the order's branch, from its base: else nothing to prove
        write(main, oid, sha, {"state": "refused", "attempt": n, "why": why, "at": train_state.utc()})
        return 1
    light = light_jobs(top)[1]
    jobs = [j for j in o.get("jobs") or [] if j in light]
    write(main, oid, sha, {"state": "running", "attempt": n, "pid": os.getpid(), "at": train_state.utc()})
    try:
        r = prove(top, main, jobs, sha, path(main, oid, sha, ".log"))
    except Exception as e:  # noqa: BLE001  (a broken proof is no green: it starts again, then refuses)
        r = {"result": "broken", "why": f"the proof broke: {e}"[:300], "jobs": [], "errors": {}}
    write(main, oid, sha, {"state": r["result"], "attempt": n, "why": r.get("why") or "", "jobs": r.get("jobs") or [],
                           "errors": r.get("errors") or {}, "at": train_state.utc()})
    print(f"the proof of {oid} on {sha[:12]}: {r['result']}" + (f" ({r['why']})" if r.get("why") else ""))
    return 0 if r["result"] in LIGHT_OK else 1


def prune(folder: Path, now: float | None = None) -> None:
    """Results and logs older than KEEP_DAYS go (the proof worktree stays)."""
    cut = (now or time.time()) - KEEP_DAYS * 86400
    for f in folder.glob("*-*.*") if folder.is_dir() else []:
        with contextlib.suppress(OSError):
            if f.is_file() and f.stat().st_mtime < cut:
                f.unlink()


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("verb", choices=("start", "run"))
    p.add_argument("--repo", required=True)
    p.add_argument("--try", dest="n", type=int)
    p.add_argument("id")
    p.add_argument("sha")
    a = p.parse_args(argv)
    main_dir = mtm_scan.main_checkout(a.repo)
    return start(a.repo, main_dir, a.id, a.sha) if a.verb == "start" else run(a.repo, main_dir, a.id, a.sha, a.n)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
