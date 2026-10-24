"""Where the Mac VM runner's evidence lives and how it is read, for fix-tart's evidence.py.

Every source is overridable (a flag, else an environment variable) so the tests read fixtures:

  daemon log   --daemon-log      FIX_TART_DAEMON_LOG   ~/Library/Logs/hal2-daemon.log (UTC times)
  task logs    --tasks-dir       FIX_TART_TASKS_DIR    <state>/tasks/*.log (no times inside: name + mtime)
  journal      --journal         FIX_TART_JOURNAL      <state>/ci-supervisor/power.log (the CI supervisor's)
  pmset        --pmset-log-file  FIX_TART_PMSET_LOG    `pmset -g log` (macOS)
  vms list     --vms-json        FIX_TART_VMS_JSON     `hal2-daemon vms list --json`
  tart list    --tart-list       FIX_TART_TART_LIST    `tart list`
  GitHub jobs  --gh-jobs         FIX_TART_GH_JOBS      `gh api` (the unfinished runs' jobs, TSV id/status/labels)

<state> is $HAL2_STATE_DIR, else ~/.local/state/hal2 (below $HAL2_HOME when set) (hal2-daemon's state root: the parent of its `daemon/`).
"""

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
# The names hal2_core::paths reads (HAL2_STATE_DIR, HAL2_HOME); a plugin cannot import the repository's shared helper.
STATE = Path(os.environ.get("HAL2_STATE_DIR") or Path(os.environ.get("HAL2_HOME") or HOME) / ".local/state/hal2")
VM = "hal2/ci-runner-macos"
REPO = "divramod/hal2"
# hal2-ci-supervisor's MacVm default labels (config.rs); ~/.config/hal2/ci-supervisor.toml [mac_vm] labels wins.
LABELS = ["self-hosted", "macOS", "ARM64", "hal2", "mac-vm-a"]
SUPERVISOR_TOML = HOME / ".config/hal2/ci-supervisor.toml"
# hal2-ci-supervisor's system/github.rs UNFINISHED: the run states whose jobs may be unfinished.
UNFINISHED = ["queued", "requested", "waiting", "pending", "in_progress"]
TARGETS = re.compile(r"\s(hal2_vm(?:_node)?|hal2_ci_supervisor)(?:::\w+)*:")
DAEMON_TIME = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)")
PMSET = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d [+-]\d{4}) (Sleep|Wake|DarkWake)\s+(.*)$")
UUID7 = re.compile(r"^([0-9a-f]{8})-([0-9a-f]{4})-7")


class Missing(Exception):
    """A required tool is not installed (exit 2)."""


def defaults():
    """Every source's default path or None (None: run the command)."""
    env = os.environ.get
    return {
        "daemon_log": env("FIX_TART_DAEMON_LOG", str(HOME / "Library/Logs/hal2-daemon.log")),
        "tasks_dir": env("FIX_TART_TASKS_DIR", str(STATE / "tasks")),
        "journal": env("FIX_TART_JOURNAL", str(STATE / "ci-supervisor/power.log")),
        "pmset_log_file": env("FIX_TART_PMSET_LOG"),
        "vms_json": env("FIX_TART_VMS_JSON"),
        "tart_list": env("FIX_TART_TART_LIST"),
        "gh_jobs": env("FIX_TART_GH_JOBS"),
    }


def utc(text):
    """`2026-10-16T05:55:35` (or with a Z / offset) as an aware UTC datetime."""
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC") if dt else "-"


def run(cmd, required=False, timeout=60):
    """A command's stdout; None when it is missing or fails (Missing when `required`)."""
    if shutil.which(cmd[0]) is None:
        if required:
            raise Missing(cmd[0])
        return None
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def tail_since(path, since, chunk=4 << 20):
    """The lines of a big log (UTC-stamped lines, oldest first) from about `since` on: read backwards in
    chunks until a chunk starts before `since`, so a 40 MB log costs only its tail."""
    path = Path(path)
    if not path.exists():
        return None
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        start = f.tell()
        while start > 0:
            start = max(0, start - chunk)
            f.seek(start)
            if start:
                f.readline()  # the rest of a cut line
            m = DAEMON_TIME.match(f.readline().decode("utf-8", "replace"))
            if m and utc(m.group(1)) < since:
                break
        f.seek(start)
        if start:
            f.readline()
        return f.read().decode("utf-8", "replace").splitlines()


def stamped(lines, since, until):
    """(time, line) of every UTC-stamped line within [since, until]."""
    out = []
    for line in lines or []:
        m = DAEMON_TIME.match(line)
        if m and since <= utc(m.group(1)) <= until:
            out.append((utc(m.group(1)), line))
    return out


def daemon_lines(path, since, until):
    """Every daemon log line in the window; None: no log. `is_vm` picks the VM's and supervisor's."""
    lines = tail_since(path, since)
    return None if lines is None else stamped(lines, since, until)


def is_vm(line):
    """A hal2_vm, hal2_vm_node or hal2_ci_supervisor line."""
    return bool(TARGETS.search(line))


def journal_lines(path, since, until):
    """The supervisor journal's lines (`<UTC time> <decision>`) in the window; None: no journal yet."""
    path = Path(path)
    if not path.exists():
        return None
    return stamped(path.read_text(errors="replace").splitlines(), since, until)


def task_start(name):
    """A task id is a UUIDv7: its first 48 bits are the start in ms."""
    m = UUID7.match(name)
    if not m:
        return None
    return datetime.fromtimestamp(int(m.group(1) + m.group(2), 16) / 1000, timezone.utc)


def runner_tasks(folder, since, until):
    """Every runner job's task log (first line `registering <name> on <repo>`) active in the window,
    oldest first: {name, start, end (mtime), lines}."""
    found = []
    for path in Path(folder).glob("*.log") if Path(folder).is_dir() else []:
        end = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        start = task_start(path.name) or end
        if end < since or start > until:
            continue
        lines = path.read_text(errors="replace").splitlines()
        if lines and lines[0].startswith("registering "):
            found.append({"name": path.stem, "start": start, "end": end, "lines": lines})
    return sorted(found, key=lambda t: t["start"])


def pmset_events(path, since, until):
    """(time, kind, text) of pmset's Sleep, Wake and DarkWake entries in the window; None: not readable."""
    text = Path(path).read_text(errors="replace") if path else run(["pmset", "-g", "log"])
    if text is None:
        return None
    out = []
    for line in text.splitlines():
        m = PMSET.match(line.strip())
        if m:
            at = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S %z").astimezone(timezone.utc)
            if since <= at <= until:
                out.append((at, m.group(2), m.group(3).strip()))
    return out


def vm_row(path, vm=VM):
    """The VM's row of `hal2-daemon vms list --json` (state, runner_enabled, job, problem)."""
    text = Path(path).read_text() if path else run(["hal2-daemon", "vms", "list", "--json"], required=True)
    try:
        data = json.loads(text or "")
    except ValueError:
        return None
    return next((v for v in data.get("vms", []) if v.get("id") == vm), None)


def tart_list(path):
    if path:
        return Path(path).read_text()
    return run(["tart", "list"]) or "(tart list: tart missing or failed)\n"


def labels():
    """[mac_vm] labels of the supervisor's config, else hal2's default."""
    try:
        import tomllib
        return tomllib.loads(SUPERVISOR_TOML.read_text()).get("mac_vm", {}).get("labels", LABELS)
    except (OSError, ImportError, ValueError):
        return LABELS


def fits(job_labels, vm_labels):
    """GitHub routes a job to the VM when each of its labels is one of the VM's (checks.rs `fits`)."""
    return bool(job_labels) and all(label in vm_labels for label in job_labels)


def gh_jobs(path, vm_labels):
    """The unfinished runs' unfinished jobs wanting the VM's labels: [(run, id, status, labels)];
    a str when GitHub could not be asked (gh missing, 401, offline)."""
    rows = []
    if path:
        text = Path(path).read_text()
        rows = [("-", *line.split("\t")) for line in text.splitlines() if line.strip()]
    else:
        runs = []
        for status in UNFINISHED:
            out = run(["gh", "api", f"repos/{REPO}/actions/runs?status={status}&per_page=100",
                       "--jq", ".workflow_runs[].id"])
            if out is None:
                return "gh failed (missing, not logged in, or the keychain did not answer): skipped"
            runs += out.split()
        jq = '.jobs[] | [(.id|tostring), .status, (.labels|join(","))] | @tsv'
        for rid in dict.fromkeys(runs):
            out = run(["gh", "api", f"repos/{REPO}/actions/runs/{rid}/jobs?filter=latest&per_page=100",
                       "--jq", jq])
            rows += [(rid, *line.split("\t")) for line in (out or "").splitlines() if line.strip()]
    out = []
    for row in rows:
        rid, jid, status, names = (list(row) + ["", "", ""])[:4]
        names = [n for n in names.split(",") if n]
        if status != "completed" and fits(names, vm_labels):
            out.append((rid, jid, status, names))
    return out
