"""The interrupt's source "host runners" (plan 0585 D4, D8, D9): every repo's GitHub host runners on this Mac.

Repos come from the folders `<root>/divramod-<repo>-<letter>` (root: $HAL2_HOST_RUNNER_ROOT, else
~/.local/share/hal2/host-runner; a repo name may hold dashes, the letter is the last segment), the state from one
`hal2-cli-ci --json runner status`. Each repo's pool runners that are not stopped yet get
`runner stop --repo divramod/<repo> --all`, never `--force` (D8): a runner busy with a job is refused, reported and
left to `retry` (the rescan loop of step 3). A busy runner makes the repo's stop go per letter, so the idle ones
still stop. One record row per runner this stop stopped (kind host-runner), undo `runner start --repo ... --letter`;
a runner stopped before stays stopped (done does not start it). Same shape as sources.py: `fn(d, dry) -> {source,
kinds, note}`, every call under a timeout (D6), a missing CLI or a failing call is one line, never raised.
"""
import os
import re
import shutil
from pathlib import Path

from sources import load, result, why

NAME = "hal2-cli-ci"
OWNER = "divramod"
KIND = "host-runner"
FOLDER = re.compile(rf"^{OWNER}-(.+)-([a-z])$")
PROBE = 45
CALL = 60
BUSY = 5  # the CLI's exit code of a runner that runs a job
GONE = (124, 127)  # timed out, not installed: a retry per letter would only repeat it


def find_cli() -> str | None:
    """$HAL2_CLI_CI (a path or a name), else hal2-cli-ci on PATH; None when not installed."""
    return shutil.which(os.environ.get("HAL2_CLI_CI") or NAME)


def root() -> Path:
    return Path(os.environ.get("HAL2_HOST_RUNNER_ROOT") or Path.home() / ".local" / "share" / "hal2" / "host-runner")


def discover(base: Path | None = None) -> dict:
    """{ "divramod/<repo>": [letters] } from the runner folders; {} when the root is not there."""
    found: dict = {}
    try:
        names = sorted(p.name for p in (base or root()).iterdir() if p.is_dir())
    except OSError:
        return found
    for name in names:
        m = FOLDER.match(name)
        if m:
            found.setdefault(f"{OWNER}/{m.group(1)}", []).append(m.group(2))
    return found


def status(d, cli: str, repos: dict) -> list | None:
    """The runners of the discovered repos from `runner status --json`; None when unreadable or timed out."""
    code, out, err = d.sys.run([cli, "--json", "runner", "status"], timeout=PROBE)
    data = load(out) if code == 0 else None
    if data is None or not isinstance(data.get("runners"), list):
        d.out(f"host runner status not readable ({why(code, err) if code else 'no JSON'}): stopping by the folders")
        return None
    return [r for r in data["runners"] if isinstance(r, dict) and r.get("repo") in repos and r.get("letter")]


def guess(repos: dict) -> list:
    """Runners from the folders alone (status unreadable): every letter counts as running, none as busy."""
    return [{"name": f"mac-host-{repo.split('/', 1)[1]}-{letter}", "repo": repo, "letter": letter,
             "listed": True, "enabled": True, "stopped": False, "busy": False}
            for repo, letters in repos.items() for letter in letters]


def to_stop(r: dict) -> bool:
    return bool(r.get("listed") and r.get("enabled") and not r.get("stopped"))


def busy(r: dict) -> bool:
    return bool(r.get("busy") or r.get("current_job"))


def row(cli: str, r: dict, do: list) -> dict:
    return {"text": f"stop host runner {r['name']}", "kind": KIND, "do": do,
            "undo": [cli, "runner", "start", "--repo", r["repo"], "--letter", r["letter"]]}


def stop_repo(d, cli: str, repo: str, runners: list) -> tuple:
    """(rows of the runners stopped, names refused as busy) for one repo; failures are printed."""
    base = [cli, "--json", "runner", "stop", "--repo", repo]
    if not any(busy(r) for r in runners):
        code, _, err = d.sys.run(base + ["--all"], timeout=CALL)
        if code == 0:
            return [row(cli, r, base + ["--all"]) for r in runners], []
        d.out(f"runner stop --all {repo} failed ({why(code, err)})" + ("" if code in GONE else ": per runner"))
        if code in GONE:
            return [], []
    rows, left = [], []
    for r in runners:
        if busy(r):
            left.append(r["name"])
            d.out(f"host runner {r['name']} runs a job: not stopped (no --force), retried")
            continue
        do = base + ["--letter", r["letter"]]
        code, _, err = d.sys.run(do, timeout=CALL)
        if code == 0:
            rows.append(row(cli, r, do))
        elif code == BUSY:
            left.append(r["name"])
            d.out(f"host runner {r['name']} runs a job: not stopped (no --force), retried")
        else:
            d.out(f"runner stop {r['name']} failed ({why(code, err)})")
    return rows, left


def stop_all(d, cli: str, dry: bool) -> tuple:
    """(kinds of what was or would be stopped, note); the work of host_runners and retry."""
    repos = discover()
    note: dict = {"cli": cli, "repos": len(repos), "stopped": [], "busy": [], "already": 0}
    if not repos:
        d.out(f"no host runner folders under {root()}: no host runners to stop")
        return [], note
    runners = status(d, cli, repos)
    if runners is None:
        runners, note["status"] = guess(repos), "unreadable"
        d.out("done starts every runner of those folders, also one stopped before this interrupt")
    note["already"] = sum(1 for r in runners if not to_stop(r))
    if note["already"]:
        d.out(f"{note['already']} host runner(s) already stopped or disabled: left as they are (done does not "
              "start them)")
    kinds: list = []
    for repo in repos:
        mine = [r for r in runners if r["repo"] == repo and to_stop(r)]
        if not mine:
            continue
        if dry:
            for r in mine:
                refused = " (busy: would be refused, no --force)" if busy(r) else ""
                d.out(f"would stop host runner {r['name']}: {cli} runner stop --repo {repo} --all; undo "
                      f"{cli} runner start --repo {repo} --letter {r['letter']}{refused}")
            kinds += [KIND] * sum(1 for r in mine if not busy(r))
            note["busy"] += [r["name"] for r in mine if busy(r)]
            continue
        rows, left = stop_repo(d, cli, repo, mine)
        if rows:
            d.rec.add_actions(rows)
            d.out(f"stopped {len(rows)} host runner(s) of {repo}: done runs runner start per runner")
        kinds += [KIND] * len(rows)
        note["stopped"] += [x["text"].removeprefix("stop host runner ") for x in rows]
        note["busy"] += left
    return kinds, note


def host_runners(d, dry: bool) -> dict:
    """Source 4: every repo's host runners stopped (undo runner start), the busy ones left to retry."""
    cli = find_cli()
    if cli is None:
        d.out(f"{NAME} not found: no host runners stopped (the machine is quieted without it)")
        return result("host runners", [], {"cli": None})
    kinds, note = stop_all(d, cli, dry)
    return result("host runners", kinds, note)


def retry(d, dry: bool = False) -> tuple:
    """The rescan's pass: (kinds stopped now, names still busy); a runner that has finished its job stops now."""
    cli = find_cli()
    if cli is None:
        return [], []
    kinds, note = stop_all(d, cli, dry)
    return kinds, note["busy"]


SOURCES = (("host runners", host_runners),)
