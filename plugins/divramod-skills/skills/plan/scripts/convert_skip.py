"""Which plans `plan.py convert` leaves alone (hal2 plan 0376, design §7 A14, §8): a masterplan (A11), a plan already
in schema 2, a folder an unmerged field branch changes (`git diff --name-only <main>...<branch> -- plans/`, every
local and remote `NN`, `farmer-*` and `tollman-*` branch), and a plan a field's `plans/CURRENT_PLAN` or `plans/LEAD`
names while it is unfinished. The field the command runs in is no other field when the plan is named explicitly:
its own branch, its remote twin and its own CURRENT_PLAN do not skip it, so a foreman converts its own plan.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import masterplan
import names
import occupied
import shape

FIELD_BRANCH = re.compile(r"^(?:[0-9]{2}|farmer-.+|tollman-.+)$")


def git(root: Path, *args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    except OSError:
        return ""
    return out.stdout if out.returncode == 0 else ""


def base_ref(root: Path) -> str | None:
    """`origin/<default>`, else a local main or master."""
    found = names.default_ref(root)
    if found:
        return found
    return next((b for b in ("main", "master") if git(root, "rev-parse", "--verify", "-q", b).strip()), None)


def field_branches(root: Path) -> list[str]:
    """Every local and remote-tracking field branch (`07`, `origin/07`, `farmer-hal2`, `origin/tollman-hal2`)."""
    out = []
    for ref in git(root, "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes").split():
        short = ref.removeprefix("refs/heads/") if ref.startswith("refs/heads/") else ref.removeprefix("refs/remotes/")
        name = short.split("/", 1)[1] if ref.startswith("refs/remotes/") and "/" in short else short
        if FIELD_BRANCH.match(name):
            out.append(short)
    return out


def worktrees(root: Path) -> list[Path]:
    return [Path(line[len("worktree "):]) for line in git(root, "worktree", "list", "--porcelain").splitlines()
            if line.startswith("worktree ")]


@dataclass
class SkipSet:
    """The repository's field state, read once per run."""
    root: Path
    branches: dict[str, set[str]] = field(default_factory=dict)  # plan slug -> branches that change it
    held: dict[str, set[str]] = field(default_factory=dict)  # plan slug -> fields whose CURRENT_PLAN/LEAD names it
    own: str = ""
    own_tree: Path | None = None

    @classmethod
    def read(cls, root: Path, plans_dir: str = "plans") -> "SkipSet":
        found = cls(root)
        if not git(root, "rev-parse", "--git-dir"):
            return found
        found.own = git(root, "branch", "--show-current").strip()
        found.own_tree = root.resolve()
        base = base_ref(root)
        for branch in field_branches(root) if base else []:
            for path in git(root, "diff", "--name-only", f"{base}...{branch}", "--", f"{plans_dir}/").splitlines():
                parts = path.split("/")
                if len(parts) > 2:
                    found.branches.setdefault(parts[1], set()).add(branch)
        for tree in worktrees(root):
            for marker in ("CURRENT_PLAN", "LEAD"):
                file = tree / "plans" / marker
                words = file.read_text(errors="replace").split() if file.is_file() else []
                slug = (words[1] if marker == "LEAD" and len(words) > 1 else words[0]) if words else ""
                if slug:
                    found.held.setdefault(slug, set()).add(f"{tree.resolve()}:{marker}")
        return found

    def is_own(self, branch: str) -> bool:
        return bool(self.own) and branch in (self.own, f"origin/{self.own}")

    def why(self, plan_md: Path, explicit: bool) -> str | None:
        """Why the plan at `plan_md` is skipped; None when it is converted."""
        folder, slug = plan_md.parent, plan_md.parent.name
        if plan_md.name != "plan.md":
            return "a flat plan file: no folder to convert"
        if masterplan.of(plan_md):
            return "a masterplan keeps its row table (design A11)"
        if shape.is_shape(folder) or masterplan.key(masterplan.read(plan_md), "schema") == 2:
            return "already in schema 2"
        others = sorted(b for b in self.branches.get(slug, ()) if not (explicit and self.is_own(b)))
        if others:
            return f"the unmerged field branch(es) {', '.join(others)} change its folder"
        holders = sorted(h for h in self.held.get(slug, ())
                         if not (explicit and self.own_tree and h.startswith(f"{self.own_tree}:")))
        if holders and occupied.status_of(plan_md) == "open":
            return f"unfinished, named by {', '.join(holders)}"
        return None
