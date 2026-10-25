"""planwriter: grouping, order, no-fix rows, the 40+ grouping, dry run; in a scratch git repo with its own HOME."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import fixsteps
import planwriter

TEMPLATE = """# Plan NNNN: t

## Brief

- In: <what this plan delivers>
- Out: <what it leaves alone>
- Must: <each requirement one line, the user's words quoted>
- Proof: <the command or the UAT checks that show the whole works>

## Steps

| # | Step | Done when | Model | Effort | Window | Size | Status |
|---|---|---|---|---|---|---|---|
| 1 | <step> | <a check anyone can run> | opus | medium | 1m | 150k | next |
| 2 | Write the UATs and the changelog fragment | x | sonnet | medium | 1m | 100k | |

## Notes
"""


def fd(id, pkg="lodash", target="~/a/io/pnpm-lock.yaml", kind="farm", ver="1.0.0", fixed="1.0.1", sev="HIGH", **kw):
    d = dict(id=id, target_kind=kind, target=target, package=pkg, source="osv-scanner", version=ver,
             fixed_version=fixed, severity=sev, summary=f"s {id}")
    d.update(kw)
    return d


class FakeRunner:
    def __init__(self):
        self.calls = []

    def new(self, repo, name, goal):
        self.calls.append((name, goal))
        p = Path(repo) / "plans" / f"0001-{name}" / "plan.md"
        p.parent.mkdir(parents=True)
        p.write_text(TEMPLATE)
        return {"path": str(p.relative_to(repo))}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.repo = Path(self.tmp.name) / "repo"
        (self.repo / "plans").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        old = {k: os.environ.get(k) for k in ("HOME", "HAL2_HOME")}
        os.environ.update(HOME=str(self.home), HAL2_HOME=str(self.home))
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
                                 for k, v in old.items()])

    def plan_text(self, report, runner=None):
        rel = planwriter.write_plan(report, self.repo, runner=runner or FakeRunner())
        return (self.repo / rel).read_text(), self.repo / rel


class GroupingTest(Base):
    def test_group_by_package_and_target(self):
        rep = {"findings": [fd("CVE-1"), fd("CVE-2", fixed="1.0.3"), fd("CVE-3", pkg="axios")]}
        fixes = fixsteps.build_fixes(fixsteps.items_of(rep))
        self.assertEqual(len(fixes), 2)
        lodash = next(f for f in fixes if "lodash" in f.title)
        self.assertEqual(lodash.title, "Bump lodash in ~/a/io/pnpm-lock.yaml from 1.0.0 to 1.0.3 (CVE-1, CVE-2, KEV: no)")

    def test_kev_first_then_severity(self):
        rep = {"findings": [fd("CVE-L", pkg="a", sev="LOW"), fd("CVE-C", pkg="b", sev="CRITICAL"),
                            fd("CVE-K", pkg="c", sev="MEDIUM", kev=True, kev_added="2026-01-02"),
                            fd("CVE-H", pkg="d", sev="HIGH")]}
        order = [f.ids[0] for f in fixsteps.build_fixes(fixsteps.items_of(rep))]
        self.assertEqual(order, ["CVE-K", "CVE-C", "CVE-H", "CVE-L"])

    def test_no_fix_row(self):
        rep = {"findings": [fd("CVE-9", pkg="zlib", fixed=None), fd("CVE-8", pkg="zlib", fixed="2.0")]}
        titles = [f.title for f in fixsteps.build_fixes(fixsteps.items_of(rep))]
        self.assertIn("Mitigate or remove zlib in ~/a/io/pnpm-lock.yaml (CVE-9): no fix yet", titles)
        self.assertTrue(any(t.startswith("Bump zlib") and "CVE-8" in t for t in titles))

    def test_os_one_step_per_machine(self):
        rep = {"findings": [fd("apt-security:a", kind="os", target="hz01", pkg="a", fixed=None),
                            fd("apt-security:b", kind="os", target="hz01", pkg="b", fixed="2"),
                            fd("macos-update:x", kind="os", target="macos", pkg="x", fixed=None)]}
        titles = sorted(f.title for f in fixsteps.build_fixes(fixsteps.items_of(rep)))
        self.assertEqual(len(titles), 2)
        self.assertTrue(titles[0].startswith("Install pending security updates on hz01 (apt-security:a, apt-security:b"))

    def test_image_os_cves_without_fix_become_one_rebuild_step(self):
        rep = {"findings": [fd("CVE-1", kind="image", target="node:22", pkg="libc", ecosystem="debian", fixed=None),
                            fd("CVE-2", kind="image", target="node:22", pkg="zlib", ecosystem="debian", fixed=None),
                            fd("CVE-3", kind="image", target="node:22", pkg="npm", ecosystem="node-pkg", fixed="9"),
                            fd("CVE-4", kind="image", target="alpine:3", pkg="musl", ecosystem="alpine", fixed=None)]}
        fixes = fixsteps.build_fixes(fixsteps.items_of(rep))
        titles = sorted(f.title for f in fixes)
        self.assertEqual(len(titles), 3)
        self.assertTrue(titles[0].startswith("Bump npm"))
        self.assertTrue(titles[1].startswith("Rebuild alpine:3 on a newer base (1 OS package CVEs"))
        self.assertTrue(titles[2].startswith("Rebuild node:22 on a newer base (2 OS package CVEs without a fix: CVE-1, CVE-2"))

    def test_image_os_cve_with_fix_stays_a_bump(self):
        rep = {"findings": [fd("CVE-1", kind="image", target="node:22", pkg="libc", ecosystem="debian", fixed="2")]}
        self.assertTrue(fixsteps.build_fixes(fixsteps.items_of(rep))[0].title.startswith("Bump libc"))

    def test_more_than_40_groups_per_target(self):
        rep = {"findings": [fd(f"CVE-{i}", pkg=f"p{i}", target=f"~/a/f{i % 3}/x.lock") for i in range(60)]}
        fixes = fixsteps.build_fixes(fixsteps.items_of(rep))
        self.assertEqual(len(fixes), 3)
        self.assertTrue(all(f.title.startswith("Fix 20 packages in ~/a/f") for f in fixes))
        self.assertTrue(all(len(f.title) <= 200 for f in fixes))


class WriteTest(Base):
    def test_plan_and_step_files(self):
        rep = {"findings": [fd("CVE-1", pkg="a", sev="LOW"), fd("CVE-2", pkg="b", kev=True, kev_added="2026-02-03")]}
        runner = FakeRunner()
        text, path = self.plan_text(rep, runner)
        self.assertEqual(runner.calls, [(planwriter.plan_name(__import__("datetime").date.today()),
                                         "2 vulnerabilities: fix KEV first")])
        rows = [l for l in text.splitlines() if l.startswith("| ")]
        self.assertIn("| 1 | Bump b in", rows[1])
        self.assertTrue(rows[1].endswith("| next |"))
        self.assertIn("| 2 | Bump a in", rows[2])
        self.assertTrue(rows[3].startswith("| 3 | Write the UATs"))
        self.assertIn("sonnet | medium | 1m | 100k", rows[1])
        self.assertNotIn("<what", text)
        self.assertIn("- Proof: a rescan", text)
        s1 = (path.parent / "steps" / "1.md").read_text()
        self.assertTrue(s1.startswith("# Step 1: Bump b"))
        self.assertIn("## Task", s1)
        self.assertIn("## Notes", s1)
        self.assertIn("KEV (added 2026-02-03)", s1)
        self.assertFalse((path.parent / "steps" / "3.md").exists())

    def test_empty_report_writes_nothing(self):
        out = planwriter.write_plan({"findings": []}, self.repo, runner=FakeRunner())
        self.assertIn("no plan", out)
        self.assertEqual(list((self.repo / "plans").iterdir()), [])

    def test_dry_run_changes_nothing(self):
        class Boom:
            def new(self, *a):
                raise AssertionError("must not run")
        out = planwriter.write_plan({"findings": [fd("CVE-1")]}, self.repo, dry_run=True, runner=Boom())
        self.assertIn("| 1 | Bump lodash", out)
        self.assertEqual(list((self.repo / "plans").iterdir()), [])

    def test_cli_dry_run(self):
        inp = Path(self.tmp.name) / "r.json"
        inp.write_text(json.dumps({"findings": [fd("CVE-1")]}))
        self.assertEqual(planwriter.main(["--input", str(inp), "--repo", str(self.repo), "--dry-run"]), 0)
        self.assertEqual(planwriter.main(["--input", str(inp) + "x", "--repo", str(self.repo)]), 2)
        self.assertEqual(list((self.repo / "plans").iterdir()), [])

    def test_long_plan_stays_short(self):
        rep = {"findings": [fd(f"CVE-{i}", pkg=f"p{i}", target=f"t{i}") for i in range(500)]}
        text, _ = self.plan_text(rep)
        self.assertLessEqual(len(text.splitlines()), 150)


@unittest.skipUnless(planwriter.plan_script(), "plan.py not found")
class RealPlanTest(Base):
    def test_real_plan_py(self):
        rep = {"findings": [fd("CVE-1", pkg="a", sev="LOW"), fd("CVE-2", pkg="b", kev=True),
                            fd("CVE-3", pkg="c", fixed=None)]}
        text, path = self.plan_text(rep, planwriter.PlanRunner())
        self.assertIn("fix-vulns-", str(path))
        self.assertIn("| 1 | Bump b in", text)
        self.assertIn("| 4 | Write the UATs", text)
        self.assertTrue((path.parent / "steps" / "3.md").is_file())
        self.assertFalse((self.repo / "plans" / "CURRENT_PLAN").exists())
        self.assertNotIn("<step>", text)
        self.assertTrue(path.parent.joinpath("decisions.md").is_file())


if __name__ == "__main__":
    unittest.main()
