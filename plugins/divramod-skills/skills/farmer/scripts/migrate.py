"""`farmer.py migrate`: a role's slot `<role>` becomes `<role>-<project>`, its files `roles/<role>/` (hal2 plan 0143).

hal2's .adr/roles-folder.md: a role works in the slot and branch `<role>-<project>` and keeps its role file
(`roles/<role>/ROLE.md`) and every runtime file in `roles/<role>/` of that slot. This moves a repository there:

1. refuses while the role's timer is installed or an agent session sits in the slot (the farmer's handoff and
   `farmer.py timer remove` come first; only the user starts the new session);
2. in the old slot: merges the default branch (it may carry the role file's move already), else moves the legacy
   `<ROLE>-ROLE.md` to `roles/<role>/ROLE.md` with the folder's .gitignore, and commits;
3. `git worktree move` to `<role>-<project>`, `git branch -m`, pushes the new branch;
4. the farmer's state from `~/skills/farmer/<repo>/` and the round summaries from `<main>/plans/farmer/` into the
   slot's `roles/farmer/` (`summaries/`); a name already there is kept and reported, never overwritten.

Every step checks the state first, so a second run does what is left and nothing else. --dry-run prints the steps.
"""

import json
import shutil
import subprocess
from pathlib import Path

import deliver
import roles
import timer

GONE = {"ended"}  # agent states that hold no slot


def git(cwd: Path, *args: str) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=300)
    return p.returncode, (p.stdout + p.stderr).strip()


def sessions_in(paths: list[Path]) -> list[str]:
    """Live agent sessions whose checkout is one of `paths`."""
    try:
        data = json.loads(deliver.cli("list", "--json")[1] or "[]")
    except json.JSONDecodeError:
        return []
    rows = data.get("list", []) if isinstance(data, dict) else data
    want = {str(p) for p in paths}
    return [f"{r.get('pane_id')} ({r.get('state')})" for r in rows
            if r.get("checkout") in want and r.get("state") not in GONE]


class Migration:
    def __init__(self, repo: str | Path, role: str = roles.ROLE, home: Path | None = None):
        self.main = roles.main_checkout(repo)
        self.role, self.home = role, home or Path.home()
        base = self.home / ".hal/git/worktree" / self.main.name
        self.branch = roles.slot_name(self.main, role)
        self.old, self.new = base / role, base / self.branch
        self.steps: list[str] = []
        self.notes: list[str] = []

    def problems(self) -> list[str]:
        out = []
        if self.old.is_dir() and self.new.is_dir():
            out.append(f"both {self.old} and {self.new} exist: move what {self.old} holds by hand")
        if self.role == roles.ROLE:
            legacy = roles.LEGACY / self.main.name
            t = timer.status(self.main.name, legacy if legacy.is_dir() else roles.state_dir(self.main))
            if t.get("loaded") or t.get("files"):
                out.append(f"the timer {t['label']} is installed: `farmer.py timer remove` first")
        busy = sessions_in([self.old, self.new])
        if busy:
            out.append(f"an agent session sits in the slot: {', '.join(busy)}; stop it first (after its handoff)")
        return out

    def step(self, text: str, dry: bool, fn=None) -> None:
        self.steps.append(text)
        if not dry and fn:
            fn()

    def must(self, cwd: Path, *args: str) -> str:
        code, out = git(cwd, *args)
        if code:
            raise RuntimeError(f"git {' '.join(args)} in {cwd}: {out}")
        return out

    def role_file(self, dry: bool) -> None:
        """Merge the default branch into the old slot, then move a legacy role file that is still there."""
        ref = self.default_ref()
        if git(self.old, "remote")[1]:
            self.step(f"git fetch origin in {self.old}", dry, lambda: git(self.old, "fetch", "-q", "origin"))
        self.step(f"merge {ref} into {self.old}", dry, lambda: self.merge(ref))
        legacy = f"{self.role.upper()}-ROLE.md"
        if dry:
            self.steps.append(f"if {legacy} is still there: git mv it to roles/{self.role}/ROLE.md, commit")
            return
        rel = Path("roles") / self.role
        if (self.old / legacy).exists() and not (self.old / rel / "ROLE.md").exists():
            (self.old / rel).mkdir(parents=True, exist_ok=True)
            self.must(self.old, "mv", legacy, str(rel / "ROLE.md"))
            self.steps.append(f"git mv {legacy} {rel}/ROLE.md")
        if (self.old / rel).is_dir() and not (self.old / rel / ".gitignore").exists():
            (self.old / rel / ".gitignore").write_text(roles.GITIGNORE)
        if (self.old / rel).is_dir():
            self.must(self.old, "add", "--", str(rel))
        if git(self.old, "diff", "--cached", "--quiet")[0]:
            self.must(self.old, "commit", "-q", "-m", f"roles: {self.role}'s role file into {rel}/ (farmer.py migrate)")
            self.steps.append(f"committed {rel}/ in {self.old}")

    def default_ref(self) -> str:
        """origin's HEAD, else origin/main, else main (a clone without origin/HEAD set)."""
        code, out = git(self.old, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
        if code == 0 and out:
            return out
        return "origin/main" if git(self.old, "rev-parse", "--verify", "--quiet", "origin/main")[0] == 0 else "main"

    def merge(self, ref: str) -> None:
        code, out = git(self.old, "merge", "--no-edit", ref)
        if code:
            git(self.old, "merge", "--abort")
            raise RuntimeError(f"merging {ref} into {self.old} failed, aborted: {out}")

    def slot(self, dry: bool) -> None:
        if self.old.is_dir() and not self.new.exists():
            self.role_file(dry)
            self.step(f"git worktree move {self.old} {self.new}", dry,
                      lambda: self.must(self.main, "worktree", "move", str(self.old), str(self.new)))
        has = lambda b: git(self.main, "rev-parse", "--verify", "--quiet", f"refs/heads/{b}")[0] == 0  # noqa: E731
        if has(self.role) and not has(self.branch):
            self.step(f"git branch -m {self.role} {self.branch}", dry,
                      lambda: self.must(self.main, "branch", "-m", self.role, self.branch))
        if git(self.main, "remote")[1] and (dry or has(self.branch)):
            self.step(f"git push -u origin {self.branch}", dry,
                      lambda: self.must(self.new, "push", "-q", "-u", "origin", self.branch))

    def move_all(self, src: Path, dst: Path, dry: bool, skip: tuple[str, ...] = ()) -> None:
        if not src.is_dir():
            return
        for f in sorted(src.iterdir()):
            if f.name in skip:
                continue
            if (dst / f.name).exists():
                self.notes.append(f"kept {f}: {dst / f.name} exists")
                continue
            self.step(f"move {f} -> {dst / f.name}", dry, lambda f=f: (dst.mkdir(parents=True, exist_ok=True),
                                                                      shutil.move(str(f), str(dst / f.name))))
        if not dry and not [f for f in src.iterdir() if f.name not in skip]:
            shutil.rmtree(src)
            self.steps.append(f"removed {src}")

    def state(self, dry: bool) -> None:
        if self.role != roles.ROLE:
            return
        if roles.OVERRIDE is not None:
            self.notes.append(f"FARMER_DIR is set: the state stays in {roles.OVERRIDE}")
            return
        dst = self.new / "roles" / self.role
        if not dry and self.new.is_dir():
            roles.state_dir(self.main)  # the folder and its .gitignore
        self.move_all(roles.LEGACY / self.main.name, dst, dry)
        self.move_all(self.main / "plans/farmer", dst / "summaries", dry, skip=(".gitignore",))

    def run(self, dry: bool) -> tuple[int, dict]:
        problems = self.problems()
        result = {"repo": str(self.main), "old": str(self.old), "new": str(self.new), "branch": self.branch,
                  "dry": dry, "problems": problems}
        if problems and not dry:
            return 1, result
        try:
            self.slot(dry)
            self.state(dry)
        except RuntimeError as e:
            result["problems"] = problems + [str(e)]
            return 1, result | {"steps": self.steps, "notes": self.notes}
        if not self.old.exists() and not self.new.exists():
            self.notes.append(f"no slot {self.old} or {self.new}: nothing to migrate")
        return (1 if problems else 0), result | {"steps": self.steps, "notes": self.notes}


def run(args) -> int:
    code, r = Migration(args.repo, args.role).run(args.dry_run)
    if args.json:
        print(json.dumps(r, indent=1))
        return code
    print(f"{'would migrate' if r['dry'] else 'migrate'} {r['old']} -> {r['new']} (branch {r['branch']})")
    for s in r.get("steps", []):
        print(f"  {s}")
    for n in r.get("notes", []):
        print(f"  note: {n}")
    for p in r["problems"]:
        print(f"  problem: {p}")
    return code
