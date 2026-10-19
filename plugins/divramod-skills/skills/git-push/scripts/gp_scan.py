"""The deterministic half of `/gp scan`: what is uncommitted, in which unit, and of which class (hal2 plan 0364, D12).

A file is `secret` (never committed), `ignore-candidate` (untracked build output, a cache, a log, an editor file, a large
binary: asked about, never committed unasked) or `commit`. `commit` files are grouped by unit; a unit is the scope the
model words the commit's subject for.
"""
import fnmatch
import os
import re
import subprocess
from pathlib import Path, PurePosixPath

LARGE_BYTES = 10 * 1024 * 1024
KINDS = ("apps", "libs", "scripts")
CONFLICTS = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}

# matched on the lower-cased name, so every pattern here is lower case (`.ENV`, `ID_RSA`, `Credentials.JSON` are secrets too)
SECRET_NAMES = (".env", ".env.*", ".envrc", ".netrc", ".npmrc", ".pypirc", ".pgpass", ".git-credentials", "id_rsa*", "id_dsa*",
                "id_ecdsa*", "id_ed25519*", "*.pem", "*.key", "*.p12", "*.pfx", "*.keystore", "*.jks", "*_sec", "*.tfvars",
                "*.tfvars.json", "credentials", "credentials.json", "credentials.yaml", "credentials.yml", "credentials.toml",
                "credentials.txt", "*.credentials", "*password*.txt", "*password*.json", "*passwords*", "service-account*.json")
SECRET_OK = (".env.example", ".env.sample", ".env.template", ".env.dist", "*_sec.secret", "*.pub", "*.tfvars.example",
             "*.tfvars.sample", ".npmrc.example", ".envrc.example")

IGNORE_DIRS_BARE = ("node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv", "venv", ".idea",
                    ".vscode", ".gradle", "DerivedData")
IGNORE_DIRS_ANCHORED = ("target", "build", "dist", ".build", ".next", "coverage", ".cache", ".terraform")
IGNORE_FILES = {".DS_Store": "macOS folder metadata", "Thumbs.db": "Windows folder metadata"}
IGNORE_GLOBS = {"*.log": "log file", "*.pyc": "compiled Python", "*.pyo": "compiled Python", "*.swp": "editor swap file",
                "*.swo": "editor swap file", "*~": "editor backup", "*.tmp": "temporary file", "*.bak": "backup copy",
                "*.o": "object file", "*.class": "compiled Java", "*.orig": "merge leftover", "*.rej": "patch leftover"}
DIR_REASON = {"node_modules": "installed dependencies", "__pycache__": "Python bytecode cache", ".venv": "virtual environment",
              "venv": "virtual environment", ".idea": "editor settings", ".vscode": "editor settings",
              "target": "build output", "build": "build output", "dist": "build output", ".build": "build output",
              ".next": "build output", "coverage": "coverage report", "DerivedData": "Xcode build output"}


def run(args: list[str], cwd: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=check)


def toplevel(repo: str) -> str:
    return run(["git", "rev-parse", "--show-toplevel"], repo).stdout.strip()


def unit_of(path: str) -> str:
    """The unit a path belongs to: `code/<lang>/<kind>/<name>`, `plans/<plan>`, `research/<x>`, `docs`, a top folder, `root`."""
    parts = PurePosixPath(path).parts
    if len(parts) == 1:
        return "root"
    if parts[0] == "code" and len(parts) >= 5 and parts[2] in KINDS:
        return "/".join(parts[:4])
    if parts[0] == "code" and len(parts) >= 3:
        return "/".join(parts[:2])
    if parts[0] in ("plans", "research") and len(parts) >= 3:
        return "/".join(parts[:2])
    return parts[0]


def scope_of(unit: str) -> str:
    """The suggested Conventional Commits scope of a unit: the unit's name, `plans`, `docs`, the folder without its dot."""
    if unit == "root":
        return ""
    parts = unit.split("/")
    if parts[0] == "code":
        return parts[-1]
    return parts[0].lstrip(".") or parts[0]


PLAN = re.compile(r"^\d{4}-[a-z0-9][a-z0-9-]*$")


def current_plan(root: str) -> str:
    """`plans/CURRENT_PLAN` when it names a plan folder (`<NNNN>-<slug>` with plans/<it>/), else an empty string."""
    marker = Path(root, "plans", "CURRENT_PLAN")
    text = marker.read_text().strip() if marker.is_file() else ""
    name = text.splitlines()[0].strip() if text else ""
    return name if PLAN.match(name) and Path(root, "plans", name).is_dir() else ""


def _match(name: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def is_secret(path: str) -> str:
    """The reason a path is a secret (never committed), else an empty string."""
    parts = PurePosixPath(path).parts
    name = parts[-1].lower()
    if ".secrets" in parts[:-1] and not name.endswith(".secret"):
        return "plain file in .secrets/"
    if _match(name, SECRET_OK):
        return ""
    if _match(name, SECRET_NAMES):
        return "secret by name"
    return ""


def ignore_candidate(path: str, root: str, untracked: bool) -> tuple[str, str]:
    """(reason, gitignore pattern) of an untracked path that is probably no source, else ("", "")."""
    if not untracked:
        return "", ""
    parts = PurePosixPath(path).parts
    for index, part in enumerate(parts[:-1]):
        if part in IGNORE_DIRS_BARE:
            return DIR_REASON.get(part, "cache or tool folder"), part + "/"
        if part in IGNORE_DIRS_ANCHORED:
            return DIR_REASON.get(part, "build output"), "/".join(parts[:index + 1]) + "/"
    name = parts[-1]
    if name in IGNORE_FILES:
        return IGNORE_FILES[name], name
    for glob, reason in IGNORE_GLOBS.items():
        if fnmatch.fnmatchcase(name, glob):
            return reason, glob
    full = os.path.join(root, path)
    try:
        if os.path.isfile(full) and os.path.getsize(full) > LARGE_BYTES:
            return f"large file ({os.path.getsize(full) // (1024 * 1024)} MB)", path
    except OSError:
        pass
    return "", ""


def parse_status(raw: str) -> list[dict]:
    """`git status --porcelain=v1 -z` entries: {state, path, orig}; a rename or copy carries its old path."""
    entries, fields, i = [], raw.split("\0"), 0
    while i < len(fields):
        field = fields[i]
        i += 1
        if len(field) < 4:
            continue
        state, path, orig = field[:2], field[3:], ""
        if "R" in state or "C" in state:
            orig = fields[i] if i < len(fields) else ""
            i += 1
        entries.append({"state": state, "path": path, "orig": orig})
    return entries


def scan(repo: str) -> dict:
    """The uncommitted files with unit, scope and class, grouped; `groups` hold only the `commit` files."""
    root = toplevel(repo)
    plan = current_plan(root)[:4]  # a plan's work is scoped by its number (hal2 plan 0391, D22), a step's `|<step>`
    raw = run(["git", "status", "--porcelain=v1", "-z", "-uall"], root).stdout
    files, conflicts = [], []
    for entry in parse_status(raw):
        path, state = entry["path"], entry["state"]
        unit = unit_of(path)
        item = {"path": path, "state": state, "unit": unit, "scope": plan or scope_of(unit), "class": "commit", "reason": "",
                "pattern": "", "orig": entry["orig"]}
        if state in CONFLICTS:
            conflicts.append(path)
        reason = is_secret(path)
        if reason:
            item.update({"class": "secret", "reason": reason, "pattern": path})
        else:
            reason, pattern = ignore_candidate(path, root, state == "??")
            if reason:
                item.update({"class": "ignore-candidate", "reason": reason, "pattern": pattern})
        files.append(item)
    groups: dict[str, dict] = {}
    for item in files:
        if item["class"] != "commit":
            continue
        group = groups.setdefault(item["unit"], {"unit": item["unit"], "scope": item["scope"], "files": []})
        group["files"].append(item["path"])
        if item["orig"]:
            group["files"].append(item["orig"])
    candidates: dict[str, dict] = {}
    for item in files:
        if item["class"] == "ignore-candidate":
            c = candidates.setdefault(item["pattern"], {"pattern": item["pattern"], "reason": item["reason"], "files": []})
            c["files"].append(item["path"])
    branch = run(["git", "branch", "--show-current"], root).stdout.strip()
    return {"root": root, "branch": branch, "clean": not files, "conflicts": conflicts, "files": files,
            "groups": list(groups.values()), "secrets": [f["path"] for f in files if f["class"] == "secret"],
            "ignore_candidates": list(candidates.values())}


def render(result: dict) -> str:
    """The scan as text for the terminal."""
    if result["clean"]:
        return f"clean: nothing to commit on {result['branch'] or '(detached)'}"
    out = [f"branch {result['branch'] or '(detached)'}: {len(result['files'])} uncommitted files"]
    if result["conflicts"]:
        out.append("CONFLICTS (resolve first): " + ", ".join(result["conflicts"]))
    for group in result["groups"]:
        out.append(f"group {group['unit']} (scope {group['scope'] or '-'}): {len(group['files'])} files")
        out.extend(f"  {path}" for path in group["files"])
    for cand in result["ignore_candidates"]:
        out.append(f"ignore-candidate {cand['pattern']} ({cand['reason']}): {len(cand['files'])} files")
    for path in result["secrets"]:
        out.append(f"secret (never committed) {path}")
    return "\n".join(out)
