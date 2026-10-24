"""The job map's selection for `units.py run checks` (hal2 plan 0420 step 2, shot 13 of skill-mtm).

A repository with `.github/hal2-changes.toml` says which gate jobs a change runs: one `hal2-cli-git changes --keys
--json` call names them (a crate's dependents included, `jobs[].packages` the changed packages for HAL_CHANGED_PACKAGES)
and their content keys. Each selected job runs as `gate/main.sh <job> --branch <base>`, one after the other; a job whose
key was green before (`gate green check`, the store and salt of code/bash/scripts/smuggle/green.sh) is skipped, a job
green on a clean tree is marked (`gate green mark`). `select()` returns None when it cannot say: the caller falls back
to the units' own `checks`; it also lists the run jobs the gate does not know (`unmapped`), which the caller covers
with the units' `checks` (plan 0427).
"""

import json
import os
import subprocess
import time

import runsteps

MAP = ".github/hal2-changes.toml"
GATE = "code/bash/scripts/gate/main.sh"
GREEN = "code/bash/scripts/smuggle/green.sh"


def sh(repo, *argv, env=None):
    return subprocess.run(argv, cwd=repo, env=env, capture_output=True, text=True, check=False)


def gate_path(repo):
    return os.environ.get("SMUGGLE_GATE") or os.path.join(repo, GATE)


def salt(repo):
    """The Mac toolchain salt of green.sh (SMUGGLE_SALT replaces it); None when green.sh is missing."""
    if "SMUGGLE_SALT" in os.environ:
        return os.environ["SMUGGLE_SALT"]
    path = os.path.join(repo, GREEN)
    if not os.path.exists(path):
        return None
    out = sh(repo, "bash", "-c", 'source "$1" && smuggle_green_salt', "salt", path)
    return out.stdout if out.returncode == 0 else None


def select(repo, base, rev):
    """{"jobs": [{name, key, packages(list or None), keys(map)}], "unmapped": [run jobs the gate does not know],
    "salt", "gate"} or None. A caller whose map leaves jobs unmapped or runnable ones empty also runs the units' checks."""
    gate = gate_path(repo)
    if not (os.path.exists(os.path.join(repo, MAP)) and os.path.exists(gate)):
        return None
    cmd = [os.environ.get("HAL2_CLI_GIT", "hal2-cli-git"), "changes", "--base", base, "--head", rev, "--keys"]
    salt_value = salt(repo)
    if salt_value is not None:
        cmd += ["--salt", salt_value]
    try:
        out = sh(repo, *cmd, "--json", "--repo", repo)
        data = json.loads(out.stdout)
        jobs, keys = data["jobs"], {k["name"]: k for k in data["keys"]}
    except (OSError, ValueError, KeyError, TypeError):
        return None
    known = set(sh(repo, "bash", gate, "list").stdout.split())
    picked, unmapped = [], []
    for job in jobs:
        name = job.get("name")
        if not job.get("run"):
            continue
        if name not in known:
            unmapped.append(name)
            continue
        key = keys.get(name, {})
        picked.append({"name": name, "key": key.get("key"), "packages": job.get("packages"),
                       "keys": key.get("packages") or {}})
    return {"jobs": picked, "unmapped": unmapped, "salt": salt_value, "gate": gate}


def green_hit(repo, gate, job):
    if not job["key"]:
        return False
    return sh(repo, "bash", gate, "green", "check", job["name"], job["key"]).stdout.strip() == "hit"


def run_job(repo, gate, base, job, env, lane):
    """Runs one gate job as the smuggle's lanes do, a step of <lane> (runsteps); its exit code. Package keys: the set
    restored and saved."""
    env = dict(env)
    # What the job map did not say never comes from the caller's environment (CI sets both).
    env.pop("HAL_CHANGED_PACKAGES", None)
    env.pop("HAL_PACKAGE_KEYS", None)
    argv = ["bash", gate, job["name"], "--branch", base]
    pairs = " ".join(f"{pkg}={key}" for pkg, key in job["keys"].items())
    if job["packages"] is not None:
        env["HAL_CHANGED_PACKAGES"] = " ".join(job["packages"])
    if pairs:
        env["HAL_PACKAGE_KEYS"] = pairs
        argv += ["--green", f".gate/green-{job['name']}"]
        subprocess.run(["bash", gate, "green", "restore", job["name"]], cwd=repo, env=env, check=False)
    code = lane.run(job["name"], argv, repo, env, key=job["key"], rust=job["name"].startswith("rust-"))
    if pairs:
        subprocess.run(["bash", gate, "green", "save", job["name"]], cwd=repo, env=env, check=False)
    return code


def mark(repo, gate, rev, job):
    """Marks <job> green, only on a clean tree (nothing uncommitted or untracked)."""
    if not job["key"]:
        return
    if sh(repo, "git", "status", "--porcelain").stdout.strip():
        print(f"smuggle-checks: {job['name']} not marked green (the candidate is not clean)", flush=True)
        return
    sha = sh(repo, "git", "rev-parse", rev).stdout.strip() or rev
    sh(repo, "bash", gate, "green", "mark", job["name"], job["key"], sha)


def run_selection(repo, sel, base, rev, env, dry):
    """Runs the selection; the report line {lane, status, seconds, jobs, skipped}. Stops at the first red job."""
    start, status, ran, skipped = time.monotonic(), "ok", [], []
    lane = runsteps.Lane("checks", {} if dry else env)
    for job in sel["jobs"]:
        name = job["name"]
        if green_hit(repo, sel["gate"], job):
            print(f"{'would skip' if dry else '=='} {name}: green before ({job['key']})", flush=True)
            skipped.append({"job": name, "key": job["key"]})
            lane.skipped(name, job["key"])
            continue
        ran.append(name)
        if dry:
            print(f"would run: {name}", flush=True)
            continue
        print(f"== {name}", flush=True)
        if run_job(repo, sel["gate"], base, job, env, lane) != 0:
            print(f"== {name}: red", flush=True)
            status = "red"
            break
        mark(repo, sel["gate"], rev, job)
    notes = [f"{s['job']} skipped (green before {s['key']})" for s in skipped]
    return {"lane": "checks", "status": status, "seconds": round(time.monotonic() - start),
            "jobs": ran + notes, "skipped": skipped}
