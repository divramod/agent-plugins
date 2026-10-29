#!/usr/bin/env python3
"""Shotfile work for /digest-todolist: where shots can go, which numbers they get, and writing them.

  shots.py repos [--root DIR]                   the git repositories an item could belong to (default ~/a), as JSON
  shots.py targets [--repo DIR] [--no-global]   the shotfiles (next number, open shots) as JSON
  shots.py preview < items.json                 the items with the shot number each would get, in order
  shots.py write   < items.json                 write the items as open shots, in order

An item is {"shotfile": "<name>", "title": "...", "body": "...", "global": false, "repo": "<dir>"} ("repo" and
"global" optional: the current repository by default; a missing shotfile is created). A farm whose home is the plan
store (plan 0409: no shotfiles/ folder) is read and written only through `hal2-cli-shooter` (`home`, `shots files`,
`shots show`, `shots create`); its paths read `store:farm/<name>.md`. `write` uses
`hal2-cli-shooter shots create` when it is installed and otherwise writes the same format itself
(hal2-shooter's insert_shot: `## shot <n> <title>` above the first shot, one above the highest number).
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

CLI = "hal2-cli-shooter"
DEFAULT_REPOS_ROOT = Path("~/a").expanduser()
DEFAULT_GLOBAL_ROOT = Path("~/Documents/hal2/shotfiles").expanduser()
HEADER = re.compile(r"^##\s+(?:x\s+)?shot\s+(\S+)(?:\s+(.*))?$")
STAMP = re.compile(r"\s*\(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\).*$")
NUMBER = re.compile(r"^(\?|-?\d+(?:\.\d+)?)$")


def die(message: str, code: int = 1) -> None:
    print(f"shots.py: {message}", file=sys.stderr)
    sys.exit(code)


def is_fence(line: str) -> bool:
    return line.lstrip().startswith("```") and line.count("```") == 1


def headers(lines: list[str]):
    """(index, number, title, done) of every shot header outside fenced code blocks."""
    in_fence = False
    for i, line in enumerate(lines):
        if is_fence(line):
            in_fence = not in_fence
            continue
        m = None if in_fence else HEADER.match(line)
        if m and NUMBER.match(m.group(1)):
            done = re.match(r"^##\s+x\s", line) is not None
            title = STAMP.sub("", (m.group(2) or "").strip()).strip()
            title = re.sub(r"\s+@\S+$", "", title)
            yield i, m.group(1), title, done


def next_number(text: str) -> int:
    whole = [int(n.split(".")[0]) for _, n, _, _ in headers(text.splitlines()) if re.match(r"^\d", n)]
    return max(whole, default=0) + 1


def insert_shot(text: str, title: str, body: str) -> tuple[str, int, int]:
    """The text with a new open shot, its number and 1-based header line (hal2-shooter's insert_shot)."""
    title = " ".join(title.split())
    body_lines = [line.rstrip() for line in body.splitlines()]
    while body_lines and not body_lines[0]:
        body_lines.pop(0)
    while body_lines and not body_lines[-1]:
        body_lines.pop()
    if not title and not body_lines:
        raise ValueError("a shot needs a title or a body")
    if any(True for _ in headers(body_lines)):
        raise ValueError("the text holds a `## shot` header line")
    number = next_number(text)
    lines = text.splitlines()
    first = next((i for i, *_ in headers(lines)), None)
    if first is None:
        last = max((i for i, line in enumerate(lines) if line.strip()), default=-1)
        at = last + 1
    else:
        at = first
    before, after = lines[:at], lines[at:]
    if all(not line.strip() for line in after):
        after = []
    out = list(before)
    if out and out[-1].strip():
        out.append("")
    line = len(out) + 1
    out.append(f"## shot {number} {title}" if title else f"## shot {number}")
    out += body_lines
    if after:
        out += [""] + after
    return "\n".join(out) + "\n", number, line


def git(*args: str, cwd: Path) -> str:
    if not shutil.which("git"):
        die("git is missing: install it (brew install git / apt-get install git)", 2)
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def repo_shotfiles(repo: Path) -> Path | None:
    """The main checkout's shotfiles/ (as hal2-cli-shooter reads it), else the checkout's own."""
    top = git("rev-parse", "--show-toplevel", cwd=repo)
    if not top:
        return None
    worktrees = git("worktree", "list", "--porcelain", cwd=repo).splitlines()
    main = Path(worktrees[0].split(" ", 1)[1]) if worktrees and worktrees[0].startswith("worktree ") else Path(top)
    for root in (main, Path(top)):
        if (root / "shotfiles").is_dir():
            return root / "shotfiles"
    return Path(top) / "shotfiles"


def global_root() -> Path | None:
    if shutil.which(CLI):
        r = subprocess.run([CLI, "settings", "--json"], capture_output=True, text=True)
        if r.returncode == 0:
            return Path(json.loads(r.stdout)["root"]).expanduser()
    return DEFAULT_GLOBAL_ROOT if DEFAULT_GLOBAL_ROOT.is_dir() else None


def cli_json(*args: str) -> dict | None:
    """`hal2-cli-shooter <args> --json` parsed; None when the CLI is missing, too old for the command, or fails."""
    if not shutil.which(CLI):
        return None
    r = subprocess.run([CLI, *args, "--json"], capture_output=True, text=True)
    try:
        return json.loads(r.stdout) if r.returncode == 0 else None
    except ValueError:
        return None


def store_scope(item: dict) -> list[str]:
    """The scope arguments of the CLI for an item or a target: the global shotfiles or a repository's."""
    if item.get("global"):
        return ["--global"]
    return ["--repo", str(item.get("repo") or Path.cwd())]


def in_store(scope: list[str]) -> bool:
    """Whether the shotfiles of `scope` live in the plan store (plan 0409: the farm's home is `store`, no
    shotfiles/ folder); only the CLI knows."""
    home = cli_json("home", *scope)
    return bool(home) and home.get("home") == "store"


def describe_store(scope: list[str]) -> list[dict]:
    """The shotfiles of a store-home scope, in `describe`'s shape (from `shots files`)."""
    listed = cli_json("shots", "files", *scope) or {"files": []}
    return [{"name": f["name"], "path": f["path"], "next": int(f["next"]), "open": f["open"]}
            for f in listed["files"]]


def describe(folder: Path) -> list[dict]:
    files = []
    for path in sorted(folder.rglob("*.md")) if folder.is_dir() else []:
        text = path.read_text()
        files.append({
            "name": str(path.relative_to(folder).with_suffix("")),
            "path": str(path),
            "next": next_number(text),
            "open": [{"number": n, "title": t} for _, n, t, done in headers(text.splitlines()) if not done and t],
        })
    return files


def cmd_targets(argv: list[str]) -> dict:
    repo = Path(argv[argv.index("--repo") + 1]).expanduser() if "--repo" in argv else Path.cwd()
    folder = repo_shotfiles(repo)
    groot = None if "--no-global" in argv else global_root()
    repo_scope, global_scope = ["--repo", str(repo)], ["--global"]
    repo_store = bool(folder) and not folder.is_dir() and in_store(repo_scope)
    global_store = bool(groot) and not groot.is_dir() and in_store(global_scope)
    return {
        "cli": shutil.which(CLI) is not None,
        "repo": {"dir": str(folder.parent), "shotfiles": "store:farm" if repo_store else str(folder),
                 "files": describe_store(repo_scope) if repo_store else describe(folder)} if folder else None,
        "global": {"shotfiles": "store:global" if global_store else str(groot),
                   "files": describe_store(global_scope) if global_store else describe(groot)} if groot else None,
    }


def farm_marked(repo: Path) -> bool:
    """Whether the repository has a farm id (`hal.farm` in its git config), read as a file: only such a repository
    can keep its shotfiles in the plan store, so only it is asked."""
    try:
        config = (repo / ".git" / "config").read_text()
    except OSError:
        return False
    return re.search(r"^\s*farm\s*=", config, re.M) is not None and "[hal]" in config


def cmd_repos(argv: list[str]) -> dict:
    """The repositories below the root (default ~/a): name, dir, whether it has shotfiles, which one is current."""
    root = Path(argv[argv.index("--root") + 1]).expanduser() if "--root" in argv else DEFAULT_REPOS_ROOT
    current = git("rev-parse", "--show-toplevel", cwd=Path.cwd())
    current_main = repo_shotfiles(Path.cwd()) if current else None
    repos = []
    for d in sorted(root.iterdir()) if root.is_dir() else []:
        if d.is_dir() and (d / ".git").exists():
            folder = d / "shotfiles"
            has = folder.is_dir() or (farm_marked(d) and in_store(["--repo", str(d)]))
            repos.append({"name": d.name, "dir": str(d), "shotfiles": has,
                          "current": current_main is not None and current_main.parent.resolve() == d.resolve()})
    return {"root": str(root), "current": str(current_main.parent) if current_main else None, "repos": repos}


def item_path(item: dict) -> Path:
    name = item["shotfile"].removesuffix(".md")
    if item.get("global"):
        root = global_root()
        if root is None:
            die("no global shotfiles folder here (hal2 is not installed)")
    else:
        root = repo_shotfiles(Path(item.get("repo") or Path.cwd()).expanduser())
        if root is None:
            die(f"not a git repository: {item.get('repo') or Path.cwd()}")
    return root / f"{name}.md"


def stored_text(item: dict) -> tuple[str, str | None] | None:
    """(virtual path, text or None when the shotfile is new) of an item whose shotfiles live in the plan store;
    None for the files home."""
    scope = store_scope(item)
    if not in_store(scope):
        return None
    name = item["shotfile"].removesuffix(".md")
    shown = cli_json("shots", "show", name, *scope)
    where = "global" if item.get("global") else "farm"
    return (shown["path"] if shown else f"store:{where}/{name}.md"), (shown["text"] if shown else None)


def cmd_preview(items: list[dict]) -> list[dict]:
    texts: dict[str, str] = {}
    out = []
    for item in items:
        stored = stored_text(item)
        if stored:
            path_s, current = stored
        else:
            path = item_path(item)
            path_s, current = str(path), (path.read_text() if path.exists() else None)
        new_file = current is None and path_s not in texts
        text = texts.get(path_s, current if current is not None else f"# {item['shotfile'].removesuffix('.md')}\n")
        texts[path_s], number, _ = insert_shot(text, item.get("title", ""), item.get("body", ""))
        out.append({**item, "path": path_s, "number": number, "new_file": new_file,
                    "header": f"## shot {number} {' '.join(item.get('title', '').split())}".rstrip()})
    return out


def write_one(item: dict) -> dict:
    title, body = item.get("title", ""), item.get("body", "")
    if shutil.which(CLI) and in_store(store_scope(item)):
        path = Path(f"store:{'global' if item.get('global') else 'farm'}/{item['shotfile'].removesuffix('.md')}.md")
    else:
        path = item_path(item)
    if shutil.which(CLI):
        args = [CLI, "shots", "create", item["shotfile"].removesuffix(".md"), "--body", "-", "--create-file", "--json"]
        if title:
            args += ["--title", title]
        args += ["--global"] if item.get("global") else ["--repo", str(item.get("repo") or Path.cwd())]
        r = subprocess.run(args, input=body, capture_output=True, text=True)
        if r.returncode != 0:
            die(f"{CLI} shots create failed: {r.stderr.strip()}")
        made = json.loads(r.stdout)
        return {**item, "path": made.get("path", str(path)), "number": int(made["number"]), "line": made.get("line"),
                "via": CLI}
    created = not path.exists()
    if created:
        path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text() if path.exists() else f"# {item['shotfile'].removesuffix('.md')}\n"
    new, number, line = insert_shot(text, title, body)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(new)
    tmp.replace(path)
    return {**item, "path": str(path), "number": number, "line": line, "via": "shots.py", "new_file": created}


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd == "repos":
        result = cmd_repos(argv[1:])
    elif cmd == "targets":
        result = cmd_targets(argv[1:])
    elif cmd in ("preview", "write"):
        items = json.loads(sys.stdin.read() or "[]")
        try:
            if cmd == "preview":
                result = cmd_preview(items)
            else:
                result = []
                for item in items:
                    written = write_one(item)
                    if "number" in item and item["number"] != written["number"]:
                        written["previewed"] = item["number"]  # someone wrote to that shotfile meanwhile
                    result.append(written)
        except ValueError as e:
            die(str(e))
    else:
        die(f"unknown command {cmd!r} (repos, targets, preview, write)")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
