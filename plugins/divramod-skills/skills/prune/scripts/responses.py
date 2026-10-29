"""The disk watermark's safe responses (hal2 plan 0472 step 2, D2), after the build-folder trims: what /prune frees
when the disk is still above its goal and no train builds.

Only two things, each named, never a pattern: `tart prune --entries caches` (Tart's OCI and IPSW caches; never `vms`,
never `~/.tart/vms`) and the folders `.hal/prune.toml` lists under `[caches] paths` (their contents go, the folder
stays; none by default). A candidate is `{field, action, target, why, bytes, lower_bound}` (`field` is the step's name,
`tart-cache` or `cache <path>`) or `{field, action: "missing", why}` when the tool is not there (said, skipped).
Tart is macOS-only by nature, so elsewhere it is skipped; the disk reading (`shutil.disk_usage`) works on all three.
"""

import os
import shutil
import sys
from pathlib import Path

import sizes

TART = "tart-cache"
SHORT_PATH = 3  # a listed cache sits at least this deep: never `/`, `/Users` or a home folder by slip


def tool() -> str | None:
    """The `tart` program, None where there is none (Linux, Windows, not installed)."""
    return shutil.which("tart") if sys.platform == "darwin" else None


def tart_home() -> Path:
    return Path(os.environ.get("TART_HOME") or Path.home() / ".tart")


def expand(path: str) -> Path:
    return Path(os.path.expanduser(path))


def real(path: str | Path) -> Path:
    """The path with links resolved (macOS: /var is /private/var), so a field is found under any spelling."""
    return Path(os.path.realpath(os.path.expanduser(str(path))))


def refusal(path: str, protected: list[str]) -> str | None:
    """Why a listed cache is not touched (a field, the main checkout or a parent of one, the home, a VM folder), else None."""
    raw = expand(path)
    p, home = real(raw), real(Path.home())
    if not raw.is_absolute() or len(p.parts) < SHORT_PATH or p == home or home.is_relative_to(p):
        return "too broad or not absolute"
    if raw.is_symlink() or any(c in str(raw) for c in "*?[]"):
        return "a link or a pattern"
    if p.is_relative_to(real(tart_home() / "vms")) or ".git" in p.parts:
        return "holds VMs or git data"
    for root in protected:
        r = real(root)
        if p == r or p.is_relative_to(r) or r.is_relative_to(p):
            return f"holds or is inside {root}"
    return None


def measure(walk, path: Path) -> dict:
    size = walk(path) if path.is_dir() else {"bytes": 0, "lower_bound": False}
    return {"bytes": size["bytes"], "lower_bound": bool(size.get("lower_bound"))}


def candidates(main: str, cfg: dict, protected: list[str], measured: bool = True, walk=sizes.walk) -> list[dict]:
    """The responses this farm could use, with their measured size (`measured` False: no walk, size 0 and unknown)."""
    out = []
    days = cfg.get("caches", {}).get("tart_older_than_days", 7)
    cache = tart_home() / "cache"
    if cache.is_dir():
        if tool():
            size = measure(walk, cache) if measured else {"bytes": 0, "lower_bound": True}
            out.append({"field": TART, "action": "tart-prune", "target": str(cache), **size,
                        "older_than_days": days, "why": f"Tart's OCI and IPSW caches unused for {days} days "
                                                         "(`tart prune --entries caches`), no local VM"})
        else:
            out.append({"field": TART, "action": "missing", "why": "tart is not installed here: skipped"})
    for path in cfg.get("caches", {}).get("paths", []):
        p = expand(path)
        why = refusal(path, protected)
        if why:
            out.append({"field": f"cache {path}", "action": "missing", "why": f"{path} not touched: {why}"})
        elif p.is_dir():
            size = measure(walk, p) if measured else {"bytes": 0, "lower_bound": True}
            out.append({"field": f"cache {path}", "action": "cache-clear", "target": str(p), **size,
                        "why": f"cache listed in .hal/prune.toml ({path})"})
    return out


def clear(path: str) -> tuple[str, str]:
    """The contents of one listed cache removed, the folder kept; a link is never followed."""
    p = Path(path)
    if p.is_symlink() or not p.is_dir():
        return "skipped", f"{path} is no folder any more"
    failed = 0
    for entry in list(p.iterdir()):
        try:
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        except OSError:
            failed += 1
    return ("failure", f"{failed} entries of {path} could not be removed") if failed else ("success", f"cleared {path}")


def run_one(a: dict, protected: list[str], run, main: str) -> tuple[str, str]:
    """One planned response carried out, its precondition asked again; `run(argv, cwd)` is prune_act.run (no timeout)."""
    if a["action"] == "cache-clear":
        why = refusal(a["target"], protected)
        return ("skipped", f"{a['target']} not touched: {why}") if why else clear(a["target"])
    program = tool()
    if a["action"] != "tart-prune" or not program:
        return "skipped", "tart is not installed here"
    older = f"--older-than={a['older_than_days']}"  # tart wants a criterion; entries caches: never a local VM
    code, text = run([program, "prune", "--entries", "caches", older], main)
    return ("success" if code == 0 else "failure"), text
