"""Farms: every folder under the root is scanned by osv-scanner (lockfiles, manifests, SBOMs), read-only."""
from pathlib import Path

import parse_osv
from findings import Report, tilde

SKIP_NAMES = {"node_modules", ".git", "target"}
V2 = ["osv-scanner", "scan", "source", "-r", "--format", "json"]
V1 = ["osv-scanner", "--json", "-r"]
OK = (0, 1)  # 0 clean, 1 vulnerabilities found
NO_PACKAGES = 128


def discover_farms(root: Path, worktree: Path = None) -> list:
    """Folders directly under root that are checkouts (a .git folder or file), not hidden or build folders.
    With `worktree` (.../worktree/<repo>/<NN>) the repository's main checkout under root is replaced by it: the
    worktree is the code this run changes, the main checkout is the same repository."""
    root = Path(root)
    farms = []
    if root.is_dir():
        for d in sorted(root.iterdir()):
            if d.name in SKIP_NAMES or d.name.startswith(".") or not d.is_dir() or not (d / ".git").exists():
                continue
            farms.append(d)
    if worktree is not None:
        worktree = Path(worktree)
        farms = [f for f in farms if f.name != worktree.parent.name]
        farms.append(worktree)
    return farms


def _scan(runner, farm: Path, report: Report):
    rc, out, err = runner.run(V2 + [str(farm)], timeout=600)
    if rc not in OK + (NO_PACKAGES, 127):
        rc, out, err = runner.run(V1 + [str(farm)], timeout=600)
    return rc, out, err


def collect(runner, report: Report, root: Path, worktree: Path = None) -> list:
    """Scan every farm; returns the farms found (the image collector reads their Dockerfiles)."""
    farms = discover_farms(root, worktree)
    for farm in farms:
        rc, out, err = _scan(runner, farm, report)
        target = tilde(str(farm))
        if rc == 127:
            report.add_error("osv-scanner", "osv-scanner not installed")
            break
        if rc == NO_PACKAGES:
            report.add_skip(target, "no lockfiles or manifests found")
        elif rc in OK:
            try:
                report.findings.extend(parse_osv.parse(out))
            except ValueError as e:
                report.add_error(target, f"osv-scanner output is not JSON: {e}")
        else:
            report.add_error(target, f"osv-scanner failed (rc {rc}): {err.strip()[:200]}")
    return farms
