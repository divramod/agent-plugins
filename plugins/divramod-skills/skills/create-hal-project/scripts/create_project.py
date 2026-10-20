#!/usr/bin/env python3
"""Set up a new hal project: private GitHub repo <owner>/<name>, checkout ~/a/<name>, the hal layout, smug windows.

  create_project.py <name> <alias> [--dry-run] [--json] [--owner divramod] [--smug a.yml,b.yml,...]

Plans first, then acts: every action (repo, checkout, file, commit, push, smug) is `create`, `exists` (reported,
never overwritten) or `skip`; `--dry-run` prints the plan and changes nothing; a rerun after success plans only
`exists`. The layout (templates/, the gate, pre-push, .hal/ of foundation.py, the farmer skill's templates/ROLE.md) is written and committed only into a new or
empty repo; a repo with commits keeps its files. The smug ymls in ~/.config/smug get a window named by the alias
(smug_windows.py), edited only, never committed. Ends with the next steps the skill does not run.
Exit 1 on a failed command, 2 when gh or git is missing, 3 when ~/a/<name> is a folder that is not the repo's checkout.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

import foundation
import smug_windows

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE.parent / "templates"
FARMER_ROLE = HERE.parents[2] / "roles" / "farmer" / "templates" / "ROLE.md"
SMUG = ("a.yml", "b.yml", "c1.yml", "hal9k-1.yml", "hal9k-2.yml", "sho.yml")
LAYOUT = {  # the flat files of the first commit: path in the new repo -> template (D2); foundation.py adds the rest
    "README.md": "README.md.tmpl", "CLAUDE.md": "CLAUDE.md.tmpl", "AGENTS.md": "AGENTS.md.tmpl",
    "INTENT.md": "INTENT.md.tmpl", "GLOSSARY.md": "GLOSSARY.md.tmpl", ".gitignore": "gitignore.tmpl",
    "roles/farmer/ROLE.md": None, "roles/farmer/.gitignore": "farmer.gitignore.tmpl",
}
MISSING_REPO = ("Could not resolve to a Repository", "not found")


def die(message: str, code: int = 1) -> NoReturn:
    print(f"create_project.py: {message}", file=sys.stderr)
    sys.exit(code)


def run(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    if not shutil.which(args[0]):
        die(f"{args[0]} is missing", 2)
    r = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        die(f"{' '.join(args[:4])} failed: {(r.stderr or r.stdout).strip()}")
    return r


def repo_state(slug: str) -> dict | None:
    """gh's view of the repo (sshUrl, isEmpty), None when it does not exist."""
    r = run("gh", "repo", "view", slug, "--json", "sshUrl,isEmpty", check=False)
    if r.returncode == 0:
        return json.loads(r.stdout)
    if any(m in r.stderr for m in MISSING_REPO):
        return None
    die(f"gh repo view {slug} failed: {r.stderr.strip()}")


def folder_state(folder: Path, slug: str) -> str:
    """missing, empty, checkout (a git repo whose origin is the repo) or foreign."""
    if not folder.exists():
        return "missing"
    if folder.is_dir() and not any(folder.iterdir()):
        return "empty"
    if (folder / ".git").exists():
        url = run("git", "remote", "get-url", "origin", cwd=folder, check=False).stdout.strip()
        if re.search(rf"[:/]{re.escape(slug)}(\.git)?/?$", url, re.IGNORECASE):
            return "checkout"
    return "foreign"


def has_head(folder: Path) -> bool:
    return run("git", "rev-parse", "--verify", "-q", "HEAD", cwd=folder, check=False).returncode == 0


def remote_has_main(folder: Path) -> bool:
    return bool(run("git", "ls-remote", "origin", "refs/heads/main", cwd=folder, check=False).stdout.strip())


def first_commit_paths() -> list[str]:
    """Every path of the first commit: the flat LAYOUT, then the foundation's (gate, pre-push, .hal/, .gitkeeps)."""
    return [*LAYOUT, *(p for p in foundation.paths() if p not in LAYOUT)]


def hook_state(folder: Path) -> str:
    """missing (no pre-push hook), exists (this skill's shim) or foreign (another tool's hook)."""
    hooks = run("git", "rev-parse", "--git-path", "hooks", cwd=folder, check=False).stdout.strip()
    hook = folder / hooks / "pre-push"
    if not hooks or not hook.is_file():
        return "missing"
    return "exists" if foundation.HOOK_MARK in hook.read_text(errors="replace") else "foreign"


def hook_action(folder: Path, checkout: bool, fresh: bool) -> dict:
    """The pre-push hook is linked into the checkout's .git only where the pre-push script is (or will be) there."""
    action = {"kind": "hook", "target": "pre-push", "state": "create", "detail": ""}
    script_there = checkout and (folder / foundation.INSTALL[1]).exists()
    if not fresh and not script_there:
        return {**action, "state": "skip", "detail": "the repo has commits: no pre-push script of this skill"}
    state = hook_state(folder) if checkout else "missing"
    if state == "foreign":
        return {**action, "state": "skip", "detail": "another tool's hook, left alone"}
    return {**action, "state": "create" if state == "missing" else state}


def plan(name: str, alias: str, owner: str, smug: list[str], home: Path) -> list[dict]:
    slug, folder = f"{owner}/{name}", home / "a" / name
    repo, where = repo_state(slug), folder_state(folder, slug)
    if where == "foreign":
        die(f"{folder} is not empty and not a checkout of {slug}: move it away or pick another name", 3)
    actions = [{"kind": "repo", "target": slug, "state": "exists" if repo else "create",
                "detail": "private" if not repo else ("empty" if repo.get("isEmpty") else "has commits")}]
    checkout = where == "checkout"
    actions.append({"kind": "checkout", "target": str(folder), "state": "exists" if checkout else "create",
                    "detail": "origin " + slug if checkout else "clone " + slug})
    local_head = checkout and has_head(folder)
    fresh = not local_head and (repo is None or repo.get("isEmpty"))
    for path in first_commit_paths():
        there = checkout and (folder / path).exists()
        state = "exists" if there else ("create" if fresh else "skip")
        actions.append({"kind": "file", "target": path, "state": state,
                        "detail": "" if state != "skip" else "the repo has commits: never added by this skill"})
    actions.append({"kind": "commit", "target": f"chore: init {name} as a hal project",
                    "state": "create" if fresh else "exists", "detail": "" if fresh else "the repo has commits"})
    pushed = not fresh and (not local_head or remote_has_main(folder))
    actions.append({"kind": "push", "target": "origin main", "state": "exists" if pushed else "create", "detail": ""})
    actions.append(hook_action(folder, checkout, fresh))
    for file in smug:
        actions.append(smug_windows.plan(home / ".config" / "smug" / file, name, alias, home))
    return actions


def render(path: str, name: str, alias: str) -> str:
    if path not in LAYOUT:
        return foundation.render(path, name, alias)
    template = LAYOUT[path]
    if template is None:
        return FARMER_ROLE.read_text().replace("<repo>", name)
    if not template:
        return ""
    return (TEMPLATES / template).read_text().replace("{name}", name).replace("{alias}", alias)


def apply(actions: list[dict], name: str, alias: str, owner: str, home: Path) -> None:
    slug, folder = f"{owner}/{name}", home / "a" / name
    todo = {(a["kind"], a["target"]) for a in actions if a["state"] == "create"}
    if ("repo", slug) in todo:
        run("gh", "repo", "create", slug, "--private")
    if ("checkout", str(folder)) in todo:
        url = (repo_state(slug) or die(f"{slug} not found after creating it"))["sshUrl"]
        folder.parent.mkdir(parents=True, exist_ok=True)
        run("git", "clone", "-q", url, str(folder))
    files = [a["target"] for a in actions if a["kind"] == "file" and a["state"] == "create"]
    for path in files:
        target = folder / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render(path, name, alias))
        target.chmod(0o755 if path in foundation.EXECUTABLE else 0o644)
    commit = next(a for a in actions if a["kind"] == "commit")
    if commit["state"] == "create":
        run("git", "symbolic-ref", "HEAD", "refs/heads/main", cwd=folder)
        run("git", "add", "--", *(p for p in first_commit_paths() if (folder / p).exists()), cwd=folder)
        run("git", "commit", "-q", "-m", commit["target"], cwd=folder)
    if ("push", "origin main") in todo:
        run("git", "push", "-q", "-u", "origin", "main", cwd=folder)
    if ("hook", "pre-push") in todo:  # after the push: the first push is the one the hook cannot gate
        run(*foundation.INSTALL, cwd=folder)
    for a in actions:
        if a["kind"] == "smug" and a["state"] == "create":
            smug_windows.append(Path(a["target"]), name, alias)


def next_steps(name: str) -> list[str]:
    return [
        f"Create the fields 00-09: hal2-cli-git worktree run <NN> --agent claude, from ~/a/{name}.",
        f"Start the farmer only in its field: hal2-cli-git worktree run farmer-{name} --agent claude, "
        "then /farmer start there (the user's word).",
        f"{name} has no tollman and no merge-to-main workflow yet: landings run /mtm locally until it has.",
        "Secrets only by hal2-cli-secrets set from a field, never plaintext in a commit.",
        "Check the repo: bash code/bash/scripts/gate/main.sh all (the pre-push hook runs its lint jobs on every push).",
        "Before going public: choose the LICENSE (the file says all rights reserved until then), see README.md's "
        "\"Making it public\".",
        "Fill INTENT.md's purpose and roles/farmer/ROLE.md's priorities and rules.",
    ]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("name")
    p.add_argument("alias")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--owner", default="divramod")
    p.add_argument("--smug", default=",".join(SMUG), help="comma-separated ymls in ~/.config/smug")
    a = p.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", a.name) or not re.fullmatch(r"[A-Za-z0-9_-]+", a.alias):
        die("name: letters, digits, . _ -; alias: letters, digits, _ -")
    home = Path.home()
    smug = [f for f in a.smug.split(",") if f]
    actions = plan(a.name, a.alias, a.owner, smug, home)
    if not a.dry_run:
        apply(actions, a.name, a.alias, a.owner, home)
    steps = next_steps(a.name)
    if a.json:
        print(json.dumps({"name": a.name, "alias": a.alias, "owner": a.owner, "dry_run": a.dry_run,
                          "actions": actions, "next": steps}, indent=2))
        return
    print(("Plan (dry run, nothing changed)" if a.dry_run else "Done") + f": {a.owner}/{a.name} in ~/a/{a.name}")
    for x in actions:
        detail = f"  ({x['detail']})" if x["detail"] else ""
        print(f"  {x['state']:<7} {x['kind']:<8} {x['target']}{detail}")
    print("Next steps (not run by this skill):")
    for step in steps:
        print(f"  - {step}")


if __name__ == "__main__":
    main()
