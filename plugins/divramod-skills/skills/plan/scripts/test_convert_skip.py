"""`plan.py convert`'s skip set, idempotence, put-back, `--dry-run` and the global folder (hal2 plan 0376, row 10;
design §7 A14): a masterplan, a plan of schema 2 (a second run), a folder an unmerged field branch changes and a plan
another field's CURRENT_PLAN names while unfinished are skipped, this field's own branch and CURRENT_PLAN only with
`--all`; a plan whose check fails is put back exactly and nothing staged; `--dry-run` writes nothing; `-g convert
--all` on a temp HOME writes its tar backup into hal2's state root first."""
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import envelope
from shape_testing import SCRIPT, TempPlan
from test_convert import RECORD, legacy_files, legacy_plan, write

MASTER = ("---\ntype: Plan\nschema: 1\nid: 10\ntitle: \"farm\"\ndescription: \"A season.\"\nstatus: open\n"
          "landing: manual\ncreated: 2026-10-01\n---\n\n# Plan 0010: farm\n\n## Goal\n\nA season.\n")


def snapshot(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


class ConvertSkipTest(TempPlan):
    def setUp(self):
        super().setUp()
        write(self.root, "0001-legacy-sample", legacy_files())
        write(self.root, "0002-record-sample", {"plan.md": RECORD})
        write(self.root, "0010-masterplan-farm", {"plan.md": MASTER})
        self.commit_all("plans")
        self.git("branch", "main")

    def lines(self, *args) -> list[str]:
        result = self.run_plan("convert", *args)
        return result.stdout.splitlines()

    def field(self, name: str) -> Path:
        tree = self.root.parent / name
        self.git("worktree", "add", "-q", "-b", name, str(tree), "main")
        return tree

    def test_masterplan_and_schema_2_are_skipped_and_a_second_run_converts_nothing(self):
        self.assertEqual(self.lines("0010", "0001")[0],
                         "skipped 0010-masterplan-farm: a masterplan keeps its row table (design A11)")
        self.commit_all("converted")
        self.assertEqual(self.lines("0001"), ["skipped 0001-legacy-sample: already in schema 2"])
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_a_field_branch_changing_the_folder(self):
        tree = self.field("31")
        (tree / "plans/0001-legacy-sample/plan.md").write_text(legacy_plan("Changed there"))
        subprocess.run(["git", "commit", "-qam", "there"], cwd=tree, check=True)
        self.assertEqual(self.lines("0001", "0002")[0],
                         "skipped 0001-legacy-sample: the unmerged field branch(es) 31 change its folder")

    def test_another_fields_current_plan_while_unfinished(self):
        (self.field("08") / "plans/CURRENT_PLAN").write_text("0002-record-sample\n")
        self.assertRegex(self.lines("0002")[0], r"^skipped 0002-record-sample: unfinished, named by .*/08:CURRENT_PLAN$")

    def test_this_fields_own_plan_only_when_named(self):
        (self.root / "plans/CURRENT_PLAN").write_text("0002-record-sample\n")
        (self.root / "plans/0002-record-sample/plan.md").write_text(RECORD.replace("none.", "this field's."))
        self.commit_all("own work")
        found = self.lines("--all", "--dry-run")
        self.assertIn("skipped 0002-record-sample: the unmerged field branch(es) 07 change its folder", found)
        self.assertEqual(self.lines("0002"), ["converted 0002-record-sample"])

    def test_a_failing_check_puts_the_plan_back(self):
        long = "".join(f"- line {n}\n" for n in range(160))
        folder = write(self.root, "0004-long-sample", {"plan.md": legacy_plan("Long sample", extra=long),
                                                       "steps/1.md": "# Step 1: First\n\n## Task\n\nIt.\n"})
        self.commit_all("long")
        before = snapshot(folder)
        result = self.run_plan("convert", "0004")
        self.assertEqual(result.returncode, 1)
        self.assertRegex(result.stdout, r"^failed 0004-long-sample: .*over 150 \(spec:budgets\) \(put back\)$")
        self.assertEqual(snapshot(folder), before)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_dry_run_writes_nothing(self):
        before = snapshot(self.root / "plans")
        self.assertEqual(self.lines("0001", "0002", "--dry-run"),
                         ["would convert 0001-legacy-sample", "would convert 0002-record-sample"])
        self.assertEqual(snapshot(self.root / "plans"), before)

    def test_a_servant_may_not_convert(self):
        (self.root / "plans/LEAD").write_text("07 0002-record-sample 01-record-sample\n")
        self.assertIn("`convert` writes the foreman's files", self.refused("convert", "0002"))

    def test_the_global_folder_after_its_backup(self):
        home = self.root.parent / "home"
        plans = write(home, "0001-legacy-sample", legacy_files()).parent
        env = {k: v for k, v in self.env.items() if k not in ("HAL2_STATE_DIR", "XDG_STATE_HOME")}
        result = subprocess.run([sys.executable, str(SCRIPT), "--global-root", str(plans), "convert", "--all"],
                                capture_output=True, text=True, cwd=home, env={**env, "HOME": str(home)})
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(result.stdout.splitlines()[0], "converted 0001-legacy-sample")
        backups = list((home / ".local/state/hal2/plans-backup").glob("plans-*.tar.gz"))
        self.assertEqual(len(backups), 1)
        with tarfile.open(backups[0]) as tar:
            old = tar.extractfile("plans/0001-legacy-sample/plan.md").read().decode()
        self.assertTrue(old.startswith("# Plan 0001: Legacy sample"))
        self.assertEqual(envelope.get((plans / "0001-legacy-sample/plan.md").read_text(), "schema"), 2)
        self.assertFalse(os.path.exists(plans / ".git"))


if __name__ == "__main__":
    import unittest
    unittest.main()
