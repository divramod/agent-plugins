"""The pretest's test fixtures (hal2 plan 0349 step 28; test_pretest*.py): a stub gate in a folder of its own (`list`,
`plan` and the jobs as small shell files) and a temporary field with two commits and a tracked file. No real gate
job ever runs."""

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import pretest

STUB = r"""#!/usr/bin/env bash
here=$(cd "$(dirname "$0")" && pwd)
case "$1" in
  list) [[ ! -f "$here/list-fails" ]] || exit 3; cat "$here/list" ;;
  plan) shift; head=
    while [[ $# -gt 0 ]]; do [[ $1 != --head ]] || head=$2; shift 2; done
    echo "plan $head" >>"$here/calls"
    if [[ -f "$here/plan-hangs" ]]; then sleep 30 & echo $! >"$here/plan-child"; wait; fi
    f="$here/plan-$head"; [[ -f $f ]] || f="$here/plan"
    printf 'linux=%s\nlinux-a=[]\nstack=[]\nmacos=[]\n' "$(cat "$f")" ;;
  *) job=$1; echo "run $job" >>"$here/calls"; echo $$ >"$here/pid-$job"
    mkdir -p "$here/running"; touch "$here/running/$job"; ls "$here/running" | wc -l >>"$here/counts"
    echo "$HAL_CHANGED_PACKAGES|$HAL_GATE_BASE|$HAL_GATE_HEAD|$HAL2_GATE_NO_INSTALL" >"$here/env-$job"
    code=0; [[ ! -f "$here/job-$job" ]] || source "$here/job-$job"
    rm -f "$here/running/$job"; echo "$job done"; exit "$code" ;;
esac
"""


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def gone(pid: int, within: float = 3.0) -> bool:
    """The process `pid` has ended (reaped) within `within` seconds."""
    end = time.monotonic() + within
    while time.monotonic() < end:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


class Stub:
    """A stub gate: the jobs it knows, what `plan` selects (per head, else for every range) and each job's body (a
    shell snippet: `sleep 30`, `code=1`)."""

    def __init__(self, folder: Path, jobs=("python-lint", "bash-lint", "records-check", "lua-lint")):
        self.dir = folder
        folder.mkdir(parents=True, exist_ok=True)
        self.main = folder / "main.sh"
        self.main.write_text(STUB)
        (folder / "list").write_text("\n".join(jobs) + "\n")
        self.selects(jobs)

    def selects(self, jobs, head=None, packages="*"):
        entries = [{"job": j, "key": f"k-{j}", "packages": packages, "targets": "*", "timeout": 10} for j in jobs]
        (self.dir / (f"plan-{head}" if head else "plan")).write_text(json.dumps(entries))

    def job(self, name, body):
        (self.dir / f"job-{name}").write_text(body + "\n")

    def calls(self):
        f = self.dir / "calls"
        return f.read_text().splitlines() if f.exists() else []

    def ran(self):
        return [c.split()[1] for c in self.calls() if c.startswith("run ")]


def config(path: Path, jobs, budget=60, parallel=4, groups=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"budget = {budget}\nparallel = {parallel}\n" + "".join(
        f'\n[[job]]\nname = "{j}"\nmedian = 20\nlocal = 18\n'
        + (f'group = "{(groups or {})[j]}"\n' if j in (groups or {}) else "") for j in jobs))
    return path


class FieldCase(unittest.TestCase):
    """A field (two commits, the tracked file `a.txt`), the stub gate, a state folder and a log."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pretest-test-"))
        self.top = self.tmp / "field"
        self.top.mkdir()
        sh(self.top, "git", "init", "-q", "-b", "main")
        (self.top / "a.txt").write_text("a\n")
        sh(self.top, "git", "add", "a.txt")
        for message in ("barn", "car"):
            sh(self.top, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m",
               message)
        self.stub, self.state, self.log = Stub(self.tmp / "gate"), self.tmp / "state", self.tmp / "pretest.log"
        mock.patch.object(pretest, "salt", return_value="s").start()
        self.addCleanup(mock.patch.stopall)

    def run_it(self, jobs, **kw):
        cfg = config(self.tmp / "hal2-pretest.toml", jobs, **kw)
        return pretest.pretest(str(self.top), self.state, "HEAD~1", self.log, cfg, self.stub.main)

    def states(self, r):
        return [(j["job"], j["state"], j["result"]) for j in r["jobs"]]

    def marked(self):
        folder = self.state / "cache/pretest"
        return sorted(f.name for f in folder.iterdir()) if folder.is_dir() else []
