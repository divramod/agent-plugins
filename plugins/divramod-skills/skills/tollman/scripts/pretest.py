#!/usr/bin/env python3
"""The tollman's pretest (hal2 plan 0349 step 28, D75): before a train's landing pushes the carrier, the short
gate jobs `.github/hal2-pretest.toml` lists run on the train's merged candidate, here, in the carrier's field: the
first red stops the landing before anything is pushed (pretest_train.py: the engine's side, the cars to blame).
POSIX only, like engine.spawn: its processes run in groups of their own (pretest_jobs.py).

  pretest.py run [--repo <field>] [--base <ref>] [--config <file>] [--json]
      a dry pretest of the field's HEAD against the barn (`--base`, default the barn's ref): no train state is
      touched; the jobs' output goes to a temporary log, whose path and the per-job lines are printed. Its markers
      are the tollman's only when `--repo` is the tollman's own field, else temporary ones

The config: `budget` (seconds for the whole pretest, default 150), `parallel` (jobs at once, default 4) and one
`[[job]]` per job with its `name` and, optional, its `group`: the jobs of one group run one after another, never
side by side (the TypeScript jobs' `bun install` in one checkout), and `ci_env = false`: the job runs without the
runner's environment (pretest_jobs.CI_ENV, plan 0490 step 9). `median` and `local`, the measured seconds, are
only read by people. No file, or no `[[job]]`: no pretest (`none`).

The selection is CI's: one `gate plan` over the merge base of the barn and HEAD .. HEAD (the same
`hal2-cli-git changes --keys` call merge-to-main.yml's `changes` makes) names the jobs the range needs and each job's
content key; a configured job it does not select is `not needed`, one `gate list` does not know is `skipped`. The plan
builds nothing (HAL2_GATE_NO_BUILD, plan 0490 step 17): a range that needs the checkout's own hal2-cli-git (it
changes the change detection) would build it cold in the train's new field, past the budget, so the pretest ends
`skipped` at once with that reason (NO_BUILD); the train's local phase builds nothing (plan 0467 D21, D29). A job
runs as CI's gate action runs it, but installs nothing (pretest_jobs.py). Its cache is the gate's green marker,
Mac-local (pretest_markers.py): a job whose marker is there is `cached` and not run (a local green never skips CI's
job, D75); a field with changed tracked files writes no marker.

At most `parallel` jobs at once; the whole pretest within `budget`: a job still running at the deadline is killed
(its process group) and `skipped`, as is one not yet started; a job whose output says a tool is missing, or that a
signal from outside ended, is `skipped`; any other failure is red. The first red stops: no job starts after it, the
running ones are killed (`skipped`). The result: `red`; `skipped` (a job was not decided, `gate list` or `plan` did
not answer, the plan needs a build, or a job changed tracked files: merge-to-main would refuse the tree); `green` (every needed job cached or
green); `none`.

Exit 0 green, skipped or none; 1 red; 2 usage.
"""

import argparse
import contextlib
import hashlib
import json
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import bounded
import mtm_scan
import pretest_jobs
import pretest_markers as markers
import train_state
from tick import default_ref

CONFIG = ".github/hal2-pretest.toml"
GATE = "code/bash/scripts/gate/main.sh"
LANES = ("linux", "stack", "macos")  # gate plan's full lists; the others are cuts of them
NO_BUILD = 3  # gate's exit when HAL2_GATE_NO_BUILD keeps it from building the checkout's hal2-cli-git


class NoBuild(RuntimeError):
    """`gate plan` needs a build the pretest does not make: no verdict, at once."""


def read_config(path: Path) -> tuple[dict | None, str]:
    """The pretest's config, or None and why there is no pretest."""
    if not path.is_file():
        return None, f"no {CONFIG}"
    try:
        raw = tomllib.loads(path.read_text())
        jobs = [str(j["name"]) for j in raw.get("job", [])]
        groups = {str(j["name"]): str(j["group"]) for j in raw.get("job", []) if j.get("group")}
        plain = {str(j["name"]) for j in raw.get("job", []) if j.get("ci_env", True) is False}
        if not jobs:
            return None, f"no [[job]] in {path.name}"
        budget, parallel = float(raw.get("budget", 150)), max(1, int(raw.get("parallel", 4)))
        return {"budget": budget, "parallel": parallel, "jobs": jobs, "groups": groups, "plain": plain}, ""
    except (tomllib.TOMLDecodeError, KeyError, TypeError, ValueError) as e:
        return None, f"{path.name} does not read: {e}"


def git(top: str, *args: str) -> str:
    p = bounded.run(["git", *args], cwd=top)
    return p.stdout.strip() if p.returncode == 0 else ""


def salt() -> str:
    """merge-to-main.yml's salt without the runner's file: the toolchain in every key, so an update runs again."""
    try:
        rustc = subprocess.run(["rustc", "--version"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        rustc = ""
    return "mac-" + hashlib.sha256(rustc.encode()).hexdigest()[:16]


def gate_jobs(top: str, gate: Path, timeout: float) -> set[str]:
    """The gate's job names (`gate list`); a list that does not answer raises RuntimeError."""
    code, out, err = pretest_jobs.call(["bash", str(gate), "list"], top, timeout)
    if code or not out.split():
        raise RuntimeError(f"gate list ended {code}: {(err or out).strip()[-300:]}")
    return set(out.split())


def plan(top: str, gate: Path, base: str, head: str, timeout: float, salt: str = "") -> dict[str, dict]:
    """The jobs `gate plan` selects for base..head, each its entry ({job, key, packages, targets, ...}); NoBuild when
    the plan would build the checkout's hal2-cli-git (the module doc)."""
    code, out, err = pretest_jobs.call(["bash", str(gate), "plan", "--base", base, "--head", head, "--salt", salt],
                                       top, timeout, {"HAL2_GATE_NO_BUILD": "1"})
    if code == NO_BUILD:
        said = next((x for x in err.splitlines() if "HAL2_GATE_NO_BUILD" in x), "").removeprefix("gate: ")
        raise NoBuild(f"{said or 'gate plan needs a build'}: the train's local phase builds nothing, CI's plan decides")
    if code:
        raise RuntimeError(f"gate plan ended {code}: {(err or out).strip()[-300:]}")
    chosen = {}
    for line in out.splitlines():
        name, _, value = line.partition("=")
        if name in LANES and value:
            chosen.update({e["job"]: e for e in json.loads(value)})
    return chosen


def pretest(top: str, state: Path, base_ref: str, log: Path, config: Path | None = None, gate: Path | None = None,
            progress: dict | None = None, only: set[str] | None = None) -> dict:
    """The pretest of the field `top`'s HEAD (the module doc), its markers below `state`: {result, seconds, jobs, why,
    log, base, head}; the jobs' output in `log`, rewritten. `progress["red"]` names a red job as soon as one is.
    `only`: the jobs that may run, the others `not needed` (a car that joined an open train: open_train.check)."""
    began, gate = time.monotonic(), gate or Path(top) / GATE
    cfg, why = read_config(config or Path(top) / CONFIG)
    head = git(top, "rev-parse", "HEAD")
    base = git(top, "merge-base", base_ref, "HEAD") or base_ref
    done, jobs = {"result": "none", "seconds": 0, "jobs": [], "why": why, "log": str(log), "base": base,
                  "head": head}, []
    if cfg:
        deadline = began + cfg["budget"]
        try:
            known = gate_jobs(top, gate, max(1.0, deadline - time.monotonic()))
            chosen = plan(top, gate, base, head, max(1.0, deadline - time.monotonic()), salt())
            chosen = {j: e for j, e in chosen.items() if only is None or j in only}
        except NoBuild as e:
            done.update(result="skipped", why=str(e)[:300])
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
            done.update(result="skipped", why=f"the gate did not answer: {e}"[:300])
        else:
            done.update(judge(top, gate, state, cfg, known, chosen, base, head, deadline, progress))
            jobs = done.pop("rows")
    with contextlib.suppress(OSError):
        write_log(log, done, jobs)
    return {**done, "seconds": round(time.monotonic() - began, 1)}


def judge(top: str, gate: Path, state: Path, cfg: dict, known: set[str], chosen: dict, base: str, head: str,
          deadline: float, progress: dict | None) -> dict:
    """The jobs run and judged (the module doc): {result, why, jobs, rows}; the green ones marked when the field was
    clean before and after them."""
    clean = not markers.dirty(top)
    green = markers.folder(state) if clean else None
    rows = run_needed(top, gate, cfg, known, chosen, green, base, head, deadline, progress)
    red = any(r["result"] == "red" for r in rows)
    changed = markers.dirty(top) if clean and not red else []
    for r in rows if clean and not changed else []:
        if r["state"] == "run" and r["result"] == "green":
            markers.mark(green, r["job"], r["key"])
    mac = next((f"{r['job']}: {r['why']}" for r in rows if (r["why"] or "").startswith(pretest_jobs.MAC)), "")
    why = (f"a job changed tracked files ({', '.join(changed[:5])}): merge-to-main would refuse the tree"
           if changed else mac)
    return {"rows": rows, "why": why, "jobs": [{k: v for k, v in r.items() if k != "text"} for r in rows],
            "result": "red" if red else "skipped" if changed or any(r["state"] == "skipped" for r in rows) else "green"}


def run_needed(top: str, gate: Path, cfg: dict, known: set[str], chosen: dict, green: Path | None, base: str,
               head: str, deadline: float, progress: dict | None = None) -> list[dict]:
    """Every configured job's row in the config's order: skipped (no such gate job), not needed, cached, or run
    (pretest_jobs.run_jobs). A row of a job that ran carries its output (`text`)."""
    rows, todo = {}, []
    for job in cfg["jobs"]:
        entry = chosen.get(job)
        if job not in known or not entry:
            rows[job] = {"job": job, "key": None, "state": "skipped" if job not in known else "not needed",
                         "seconds": 0, "result": None,
                         "why": "no such gate job" if job not in known else "the range does not select it"}
        elif markers.cached(green, job, entry.get("key")):
            rows[job] = {"job": job, "key": entry["key"], "state": "cached", "seconds": 0, "result": "green",
                         "why": "green before with this content"}
        else:
            todo.append({**entry, "plain": True} if job in cfg.get("plain", ()) else entry)
    with tempfile.TemporaryDirectory(prefix="pretest-") as scratch:
        for row in pretest_jobs.run_jobs(top, gate, todo, base, head, deadline, cfg["parallel"], Path(scratch),
                                         cfg.get("groups"), progress):
            row["text"] = pretest_jobs.output(row)
            del row["out"]
            rows[row["job"]] = row
    return [rows[j] for j in cfg["jobs"]]


def write_log(log: Path, done: dict, jobs: list[dict]) -> None:
    """The result, every job's line, then the output of each that ran, in the config's order."""
    log.parent.mkdir(parents=True, exist_ok=True)
    parts = [f"pretest of {done['head'][:12]} against {done['base'][:12]}: {done['result']}"
             + (f" ({done['why']})" if done["why"] else "")] + [line(r) for r in jobs] + [""]
    for r in jobs:
        if r.get("text"):
            parts += [f"== {r['job']} ({r['state']}, {r['seconds']} s, {r['result'] or 'no result'}) ==", r["text"]]
    log.write_text("\n".join(parts) + "\n")


def line(r: dict) -> str:
    return (f"{r['job']}: {r['state']}" + (f", {r['result']}" if r["result"] and r["state"] == "run" else "")
            + (f", {r['seconds']} s" if r["seconds"] else "") + (f" ({r['why']})" if r["why"] else ""))


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="verb", required=True)
    run = sub.add_parser("run")
    for flag in ("--repo", "--base", "--config"):
        run.add_argument(flag)
    run.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    top = git(a.repo or ".", "rev-parse", "--show-toplevel") or (a.repo or ".")
    main_dir, scratch = mtm_scan.main_checkout(top), Path(tempfile.mkdtemp(prefix="pretest-"))
    own = Path(top).resolve() == Path(mtm_scan.roles.slot_dir(main_dir, train_state.ROLE)).resolve()
    state = train_state.folder(main_dir) if own and train_state.folder(main_dir).is_dir() else scratch
    log = scratch / "pretest.log"
    r = pretest(top, state, a.base or default_ref(top), log, Path(a.config) if a.config else None)
    if a.json:
        print(json.dumps(r))
    else:
        print("\n".join([f"pretest: {r['result']} in {r['seconds']} s" + (f" ({r['why']})" if r["why"] else "")]
                        + [line(j) for j in r["jobs"]] + [f"log: {log}", f"markers: {state / markers.MARKERS}"]))
    return 1 if r["result"] == "red" else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
