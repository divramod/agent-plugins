"""The suite does not depend on the field it runs in (hal2 plan 0275 step 9).

plan.py refuses a servant's writes by the marker `plans/LEAD` of the `--root` checkout, else of the checkout the
current directory lies in (parallel.subservant_marker). A test that starts plan.py from this folder therefore reads
the marker of the field the suite runs in: in a servant's field (30 to 99) every write was refused ("a servant of the
foreman in field 09"). So each test starts plan.py from its scratch root, and this test holds that: it copies the
skill into a scratch checkout that holds a marker and runs the whole suite there once, each test module in its own
process, several at a time."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
COPY = "PLAN_SKILL_SUITE_IN_A_MARKED_FIELD"  # set for the suite in the copy, which does not copy itself again


@unittest.skipIf(os.environ.get(COPY), "this is the suite in the marked copy")
class FieldIndependentTest(unittest.TestCase):
    def test_the_suite_passes_in_a_field_that_holds_a_servants_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            field = Path(tmp).resolve() / "38"
            scripts = field / "code" / "skills" / "plan" / "scripts"
            shutil.copytree(SKILL, scripts.parent, ignore=shutil.ignore_patterns("__pycache__"))
            subprocess.run(["git", "init", "-q", "-b", "38", str(field)], check=True)
            (field / "plans").mkdir()
            (field / "plans" / "LEAD").write_text("09 0001-masterplan-farm 2\n")

            modules = sorted(p.stem for p in scripts.glob("test_*.py") if p.stem != Path(__file__).stem)

            def suite(module: str) -> subprocess.CompletedProcess:
                return subprocess.run([sys.executable, "-m", "unittest", "-q", module], cwd=scripts,
                                      env={**os.environ, COPY: "1"}, capture_output=True, text=True)

            with ThreadPoolExecutor(max_workers=min(len(modules), os.cpu_count() or 2, 8)) as pool:
                runs = dict(zip(modules, pool.map(suite, modules)))
            ran = 0
            for module, out in runs.items():
                self.assertEqual(out.returncode, 0, f"{module}: {out.stderr[-4000:]}")
                self.assertNotIn("a servant of the foreman", out.stderr, module)
                count = re.search(r"^Ran (\d+) tests?", out.stderr, re.M)
                self.assertIsNotNone(count, f"{module}: {out.stderr[-4000:]}")
                ran += int(count.group(1))
            self.assertGreaterEqual(ran, 100)


if __name__ == "__main__":
    unittest.main()
