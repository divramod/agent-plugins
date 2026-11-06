#!/usr/bin/env python3
"""The tollman's pretest (hal2 plan 0349 step 28, D75): before a train's landing pushes the carrier, the short
gate jobs `.github/hal2-pretest.toml` lists run on the train's merged candidate, here, in the carrier's field: a
red stops the landing before anything is pushed, every red named at once (pretest_train.py: the engine's side, the
cars to blame). fix_proof.py runs it on a fix order's answer too, only the order's jobs (plan 0522 D5).
POSIX only, like engine.spawn: its processes run in groups of their own (pretest_jobs.py).

  pretest.py run [--repo <field>] [--base <ref>] [--config <file>] [--json]
      a dry pretest of the field's HEAD against the barn (`--base`, default the barn's ref): no train state is
      touched; the jobs' output goes to a temporary log, whose path and the per-job lines are printed. Its markers
      are the tollman's only when `--repo` is the tollman's own field, else temporary ones

The config: `budget` (seconds for the whole pretest, default 150), `parallel` (jobs at once, default 4) and one
`[[job]]` per job with its `name` and, optional, its `group`: the jobs of one group run one after another, never
side by side (the TypeScript jobs' `bun install` in one checkout), and `ci_env = false`: the job runs without the
runner's environment (pretest_jobs.CI_ENV, plan 0490 step 9). `median` and `local`, the measured seconds, are
only read by people. No file, or no `[[job]]`: no pretest (`none`). The switch `enabled` (default on when missing;
the repo's file says false since 2026-10-31, the user: "push to cloud as fast as possible without heavy local tests"):
false is no pretest either; `HAL2_PRETEST=on|off` overrides it for one landing.

The selection is CI's: one `gate plan` over the merge base of the barn and HEAD .. HEAD (the same
`hal2-cli-git changes --keys` call merge-to-main.yml's `changes` makes) names the jobs the range needs and each job's
content key; the one entry `lint` it folds the lint jobs into (gate/lib/lint.sh) is unfolded into its jobs, each with
its own key (plan 0522: folded, no lint job was ever selected); a configured job it does not select is `not needed`,
one `gate list` does not know is `skipped`. The gate's calls and jobs use the installed `hal2-cli-git` when it reads
the checkout's job map (HAL2_CLI_GIT): the tollman builds nothing of its own here (plan 0467 D21), and a range that
changes hal2-git made `gate plan` build it and time out (plan 0522). The plan builds nothing either way
(HAL2_GATE_NO_BUILD, plan 0490 step 17): a range that needs the checkout's own hal2-cli-git (it changes the change
detection) would build it cold in the train's new field, past the budget, so the pretest ends `skipped` at once with
that reason (NO_BUILD); the train's local phase builds nothing (plan 0467 D21, D29). A job runs as CI's gate action
runs it, but installs nothing (pretest_jobs.py). Its cache is the gate's green marker, Mac-local (pretest_markers.py):
a job whose marker is there is `cached` and not run (a local green never skips CI's job, D75); a field with changed
tracked files writes no marker.

`gate list` and `gate plan` within GATE_SECONDS; then at most `parallel` jobs at once, all within `budget`: a job
still running at the deadline is killed (its process group), it and one not yet started are cut (BUDGET); a job whose
output says a tool is missing, or that a signal from outside ended, is `skipped`; any other failure is red. A red
stops no other job: every job runs, so one result names every red, each with its first error line (`errors`, plan
0522 D14). The result: `red`; `incomplete` (a job the budget cut, or the gate did not answer: not green, the push
waits, plan 0522 D7); `skipped` (a job was not decided for the Mac's sake, the plan needs a build, or a job changed
tracked files: merge-to-main would refuse the tree); `green` (every needed job cached or green); `none`.

Exit 0 green, skipped or none; 1 red or incomplete; 2 usage.
"""

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import os
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
LINT = "lint"  # gate plan's one entry for the lint jobs (gate/lib/lint.sh): `package_keys` holds `<job>=<key>` pairs
GATE_SECONDS = 300  # `gate list` and `gate plan` together, before the jobs' budget starts
BUDGET = pretest_jobs.BUDGET
NO_BUILD = 3  # gate's exit when HAL2_GATE_NO_BUILD keeps it from building the checkout's hal2-cli-git


class NoBuild(RuntimeError):
    """`gate plan` needs a build the pretest does not make: no verdict, at once."""


def read_config(path: Path, switch: bool = True) -> tuple[dict | None, str]:
    """The pretest's config, or None and why there is no pretest; `switch` False reads it whatever `enabled` says."""
    if not path.is_file():
        return None, f"no {CONFIG}"
    try:
        raw = tomllib.loads(path.read_text())
        on = {"on": True, "off": False}.get(os.environ.get("HAL2_PRETEST", ""), raw.get("enabled", True) is True)
        if switch and not on:
            return None, f"the pretest is off (`enabled = false` in {path.name}; HAL2_PRETEST=on runs it)"
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


def installed_cli(top: str) -> str:
    """The installed hal2-cli-git when it reads the field's job map (gate/main.sh's choose_cli probe), else "" (the
    gate chooses: it may build the checkout's own)."""
    cli = shutil.which("hal2-cli-git")
    try:
        ok = cli and subprocess.run([cli, "changes", "--base", "HEAD", "--head", "HEAD", "--repo", top], cwd=top,
                                    capture_output=True, timeout=120).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    return cli if ok else ""


def gate_env(cli: str) -> dict | None:
    return {**os.environ, "HAL2_CLI_GIT": cli} if cli else None


def gate_jobs(top: str, gate: Path, timeout: float, cli: str = "") -> set[str]:
    """The gate's job names (`gate list`); a list that does not answer raises RuntimeError."""
    code, out, err = pretest_jobs.call(["bash", str(gate), "list"], top, timeout, gate_env(cli))
    if code or not out.split():
        raise RuntimeError(f"gate list ended {code}: {(err or out).strip()[-300:]}")
    return set(out.split())


def plan(top: str, gate: Path, base: str, head: str, timeout: float, salt: str = "", cli: str = "") -> dict[str, dict]:
    """The jobs `gate plan` selects for base..head, each its entry ({job, key, packages, targets, ...}); the entry
    `lint` as its jobs; NoBuild when the plan would build the checkout's hal2-cli-git (the module doc)."""
    code, out, err = pretest_jobs.call(["bash", str(gate), "plan", "--base", base, "--head", head, "--salt", salt],
                                       top, timeout, {**(gate_env(cli) or {}), "HAL2_GATE_NO_BUILD": "1"})
    if code == NO_BUILD:
        said = next((x for x in err.splitlines() if "HAL2_GATE_NO_BUILD" in x), "").removeprefix("gate: ")
        raise NoBuild(f"{said or 'gate plan needs a build'}: the train's local phase builds nothing, CI's plan decides")
    if code:
        raise RuntimeError(f"gate plan ended {code}: {(err or out).strip()[-300:]}")
    chosen = {}
    for line in out.splitlines():
        name, _, value = line.partition("=")
        if name in LANES and value:
            for e in json.loads(value):
                chosen.update(unfold(e) if e["job"] == LINT else {e["job"]: e})
    return chosen


def unfold(entry: dict) -> dict[str, dict]:
    """The folded entry `lint` as one entry per lint job, each with its own key (none: no marker is used)."""
    jobs = {}
    for pair in str(entry.get("package_keys") or "").split():
        job, _, key = pair.partition("=")
        jobs[job] = {"job": job, "key": key or None, "package_keys": "", "packages": "*", "targets": "*",
                     "timeout": entry.get("timeout")}
    return jobs


def pretest(top: str, state: Path, base_ref: str, log: Path, config: Path | None = None, gate: Path | None = None,
            progress: dict | None = None, scale: float = 1.0) -> dict:
    """The pretest of the field `top`'s HEAD (the module doc), its markers below `state`: {result, seconds, jobs, why,
    errors, log, base, head}; the jobs' output in `log`, rewritten. `progress["red"]` names a red job as soon as one
    is.
    `scale` multiplies the gate's wait (GATE_SECONDS) and the jobs' budget: the one retry runs with 2 (plan 0623 D3)."""
    began, gate = time.monotonic(), gate or Path(top) / GATE
    cfg, why = read_config(config or Path(top) / CONFIG)
    head = git(top, "rev-parse", "HEAD")
    base = git(top, "merge-base", base_ref, "HEAD") or base_ref
    done, jobs = {"result": "none", "seconds": 0, "jobs": [], "why": why, "log": str(log), "base": base,
                  "head": head, "errors": {}}, []
    if cfg:
        asked, cli = time.monotonic() + GATE_SECONDS * scale, installed_cli(top)
        try:
            known = gate_jobs(top, gate, max(1.0, asked - time.monotonic()), cli)
            chosen = plan(top, gate, base, head, max(1.0, asked - time.monotonic()), salt(), cli)
        except NoBuild as e:
            done.update(result="skipped", why=str(e)[:300])
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
            done.update(result="incomplete", why=f"the gate did not answer: {e}"[:300])
        else:
            deadline = time.monotonic() + cfg["budget"] * scale
            done.update(judge(top, gate, state, cfg, known, chosen, base, head, deadline, progress, cli))
            jobs = done.pop("rows")
    with contextlib.suppress(OSError):
        write_log(log, done, jobs)
    return {**done, "seconds": round(time.monotonic() - began, 1)}


def judge(top: str, gate: Path, state: Path, cfg: dict, known: set[str], chosen: dict, base: str, head: str,
          deadline: float, progress: dict | None, cli: str = "") -> dict:
    """The jobs run and judged (the module doc): {result, why, jobs, rows}; the green ones marked when the field was
    clean before and after them."""
    clean = not markers.dirty(top)
    green = markers.folder(state) if clean else None
    rows = run_needed(top, gate, cfg, known, chosen, green, base, head, deadline, progress, cli)
    red = any(r["result"] == "red" for r in rows)
    changed = markers.dirty(top) if clean and not red else []
    for r in rows if clean and not changed else []:
        if r["state"] == "run" and r["result"] == "green":
            markers.mark(green, r["job"], r["key"])
    cut = [r["job"] for r in rows if r["state"] == "skipped" and str(r["why"]).startswith(BUDGET)]
    mac = next((f"{r['job']}: {r['why']}" for r in rows if (r["why"] or "").startswith(pretest_jobs.MAC)), "")
    why = (f"a job changed tracked files ({', '.join(changed[:5])}): merge-to-main would refuse the tree"
           if changed else f"the budget cut {', '.join(cut)}: not green, the push waits" if cut and not red else
           f"the budget cut {', '.join(cut)}: not known" if cut else mac)
    skipped = changed or any(r["state"] == "skipped" for r in rows)
    result = "red" if red else "incomplete" if cut else "skipped" if skipped else "green"
    errors = {r["job"]: first_error(r.get("text") or "") for r in rows if r["result"] == "red"}
    return {"rows": rows, "why": why, "jobs": [{k: v for k, v in r.items() if k != "text"} for r in rows],
            "result": result, "errors": errors}


ERROR = re.compile(r"error|fail|not ok|✗|panic|^\S+:\d+:", re.IGNORECASE)  # also a `path:line:` finding


def first_error(text: str) -> str:
    """A red job's first line that reads as an error or a `path:line:` finding (else its last line), at most 200
    characters."""
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("gate: unit ")]
    return (next((x for x in lines if ERROR.search(x)), None) or (lines[-1] if lines else "no output"))[:200]


def run_needed(top: str, gate: Path, cfg: dict, known: set[str], chosen: dict, green: Path | None, base: str,
               head: str, deadline: float, progress: dict | None = None, cli: str = "") -> list[dict]:
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
                                         cfg.get("groups"), progress, cli):
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
    return 1 if r["result"] in ("red", "incomplete") else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
