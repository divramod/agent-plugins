"""A test farm of numbered worktrees (once test_prune.py's, which moved to the tollman with the prune duty in plan
0360 step 7 and to /prune's own tests in plan 0377): the farmer's tests of mtm_scan and lead_scan and /prune's build
on it. No test here."""

import os

from test_farmer import NOW, Repo, git

NOW_MS = NOW.timestamp() * 1000


class Slots(Repo):
    """The main checkout with landed worktrees 03, 13, 14 and others holding work, plus names prune never touches."""

    def setUp(self):
        super().setUp()
        self.base = self.tmp / ".hal/git/worktree/hal2"

    def grow(self):
        super().grow()
        self.base = self.tmp / ".hal/git/worktree/hal2"
        for name in ("03", "04", "05", "06", "07", "13", "14", "00-train-wt", "owner"):
            git(self.main, "worktree", "add", "-q", "-b", name, str(self.base / name), "origin/main")
        (self.base / "04/new.txt").write_text("x")
        (self.base / "05/plans").mkdir()
        (self.base / "05/plans/CURRENT_PLAN").write_text("0001-x\n")
        git(self.base / "06", "commit", "-q", "--allow-empty", "-m", "work")
        git(self.base / "07", "branch", "07-ui")
        git(self.base / "07", "switch", "-q", "07-ui")
        git(self.base / "07", "commit", "-q", "--allow-empty", "-m", "side")
        git(self.base / "07", "switch", "-q", "07")


class MarkedSlots(Slots):
    """Skills plan 0013: a foreman in worktree 02 and its servants' worktrees marked plans/LEAD, beside the unmarked ones.
    31 and 33: their step merged into origin/02; 32: a commit origin/02 lacks; 12: a servant below 30."""

    def setUp(self):
        super().setUp()
        self.lead = self.base / "02"

    def grow(self):
        super().grow()
        self.lead = self.base / "02"
        git(self.main, "worktree", "add", "-q", "-b", "02", str(self.lead), "origin/main")
        git(self.lead, "commit", "-q", "--allow-empty", "-m", "the lead's plan")
        git(self.lead, "push", "-q", "origin", "02")
        for name in ("31", "32", "33", "12"):
            path = self.base / name
            git(self.main, "worktree", "add", "-q", "-b", name, str(path), "origin/02")
            git(path, "commit", "-q", "--allow-empty", "-m", f"step of {name}")
            git(path, "push", "-q", "-u", "origin", name)
            self.mark(name)
        for name in ("31", "33", "12"):
            git(self.lead, "merge", "-q", "--no-ff", "-m", f"merge {name}", f"origin/{name}")
        git(self.lead, "push", "-q", "origin", "02")

    def mark(self, name, lead="02", age=2 * 3600):
        """plans/LEAD and CURRENT_PLAN as create.py writes them (here not ignored), written `age` seconds before NOW."""
        plans = self.base / name / "plans"
        plans.mkdir(exist_ok=True)
        (plans / "LEAD").write_text(f"{lead} 0013-parallel-plans 4\n")
        (plans / "CURRENT_PLAN").write_text("0013-parallel-plans\n")
        os.utime(plans / "LEAD", (NOW.timestamp() - age,) * 2)

    def agent(self, name, minutes_ago):
        return {"pane_id": f"%{name}", "checkout": str(self.base / name), "state": "idle",
                "since": NOW_MS - minutes_ago * 60_000}
