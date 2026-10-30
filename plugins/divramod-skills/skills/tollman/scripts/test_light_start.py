"""Hal2 plan 0480 step 03.01 (D3): a minute pass starts light. Every module of the tollman and farmer scripts imports
(a deferred import that is wrong is caught here, not at 03:00 by the timer), and a whole quiet pass, run as the timer
runs it (`python3 tollman.py tick`, a fresh interpreter), loads at most BOUND skill modules (stdlib not counted)."""
# enforces .adr/deterministic-first.md and .adr/tollman.md

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import mtm_scan
import test_minute
import tollman

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[3]  # code/agents/apps/skills/
FARMER = farmer_frame.SCRIPTS
BOUND = 40  # skill modules a quiet pass may load (D3); the lowest honest bound is argued in the step's Notes

IMPORT_ALL = """
import importlib, sys
sys.path[:0] = sys.argv[1:]
bad = []
for folder in sys.argv[1:]:
    from pathlib import Path
    for f in sorted(Path(folder).glob("*.py")):
        if f.stem.startswith("test_") or not f.stem.isidentifier() or f.stem in ("tollman", "farmer"):
            continue
        try:
            importlib.import_module(f.stem)
        except BaseException as e:
            bad.append(f"{f.name}: {type(e).__name__}: {e}")
print("\\n".join(bad))
"""

DRIVER = """
import json, runpy, sys
script, repo, skills = sys.argv[1:4]
sys.path.insert(0, str(__import__("pathlib").Path(script).parent))
sys.argv = [script, "tick", "--repo", repo]
try:
    runpy.run_path(script, run_name="__main__")
except SystemExit as e:
    code = e.code
mods = sorted(m for m, v in sys.modules.items() if str(getattr(v, "__file__", None) or "").startswith(skills))
print(json.dumps({"code": code, "mods": mods}), file=sys.stderr)
"""


class EagerImports(unittest.TestCase):
    def test_every_module_of_the_tollman_and_farmer_scripts_imports(self):
        """In a fresh interpreter (the modules the tests import first cannot hide an import a handler needs)."""
        p = subprocess.run([sys.executable, "-c", IMPORT_ALL, str(HERE), str(FARMER)], capture_output=True, text=True,
                           timeout=300)
        self.assertEqual((p.returncode, p.stdout.strip()), (0, ""), p.stderr)


class Deferred(unittest.TestCase):
    """The imports inside functions (plan 0480 D3) are not run by importing the module: check each one by name."""

    def test_every_import_inside_a_function_resolves_to_a_module_and_its_names(self):
        import ast
        import importlib
        own = {f.stem for folder in (HERE, FARMER) for f in folder.glob("*.py") if f.stem.isidentifier()}
        for folder in (HERE, FARMER):
            for f in sorted(folder.glob("*.py")):
                if f.stem.startswith("test_"):
                    continue
                for fn in (n for n in ast.walk(ast.parse(f.read_text())) if isinstance(n, ast.FunctionDef)):
                    for node in (n for n in ast.walk(fn) if isinstance(n, (ast.Import, ast.ImportFrom))):
                        for mod, names in ([(a.name, ()) for a in node.names] if isinstance(node, ast.Import)
                                           else [(node.module, [a.name for a in node.names])]):
                            if mod not in own:  # stdlib and other skills' modules are not this test's
                                continue
                            m = importlib.import_module(mod)
                            for name in names:
                                self.assertTrue(hasattr(m, name), f"{f.name}:{node.lineno}: {mod}.{name}")

    def test_the_lazy_handlers_are_the_real_ones(self):
        import boss
        import checks
        import learn
        import mainred
        import minute
        import prune
        import trains
        want = {"duty:mtm": boss.handler, "duty:trains": trains.handler, "duty:checks": checks.handler,
                "duty:learn": learn.handler, "duty:prune": prune.handler, "duty:mainred": mainred.handler,
                "duty:watch": minute.handler}
        self.assertEqual(set(tollman.HANDLERS), set(want))
        for item, handler in want.items():
            self.assertIs(tollman.HANDLERS[item], handler, item)
            self.assertIs(tollman.HANDLERS.get(item), handler, item)
        self.assertIsNone(tollman.HANDLERS.get("duty:nothing"))

    def test_the_words_copied_to_stay_light_match_their_sources(self):
        import duties
        import modes
        import queue_mode
        import switch
        import trains
        self.assertEqual(modes.VERBS, ("seen-mode", "barn", *switch.VERBS))
        self.assertEqual(queue_mode.LEAD, duties.LEAD)
        self.assertEqual(trains.QUEUE, mtm_scan.QUEUE)

    def test_the_wiring_carries_through_own_fix(self):
        import own_fix
        self.assertIs(tollman.WIRING.carries, tollman.carries)
        with mock.patch.object(own_fix, "carries", return_value=True) as m:
            self.assertTrue(tollman.carries("/x"))
        m.assert_called_once_with("/x")

    def test_tick_is_parsed_without_the_other_commands(self):
        args = tollman.parser(True).parse_args(["tick", "--dry-run", "--repo", "/x"])
        self.assertEqual((args.cmd, args.dry_run, args.json, args.all_due, args.repo), ("tick", True, False, False, "/x"))
        self.assertEqual(vars(tollman.parser().parse_args(["tick", "--dry-run", "--repo", "/x"])),
                         vars(args), "the full parser reads tick the same way")


class QuietPass(test_minute.Pass):
    def shims(self, tmp: str) -> dict:
        """`gh`, `hal2-cli-git` and `hal2-cli-agents` that answer an empty list or object and touch nothing."""
        for name, out in (("gh", "[]"), ("hal2-cli-git", '{"queue": []}'), ("hal2-cli-agents", "[]")):
            f = Path(tmp) / name
            f.write_text(f"#!/bin/sh\necho '{out}'\n")
            f.chmod(f.stat().st_mode | stat.S_IXUSR)
        return {**os.environ, "PATH": f"{tmp}{os.pathsep}{os.environ['PATH']}", "HOME": str(self.tmp),
                "FARMER_DIR": str(self.data), "HAL2_ROLES_UNDER_TEST": "1"}

    def test_a_quiet_pass_loads_few_skill_modules(self):
        with tempfile.TemporaryDirectory() as shim:
            p = subprocess.run([sys.executable, "-c", DRIVER, str(HERE / "tollman.py"), str(self.wm), str(SKILLS)],
                               capture_output=True, text=True, env=self.shims(shim), timeout=120)
        self.assertEqual(p.stdout, "", p.stderr)
        got = json.loads(p.stderr.strip().splitlines()[-1])
        self.assertEqual(got["code"], 0, p.stderr)
        self.assertFalse((self.wm_state / "summaries").exists(), "a pass, not a round")
        self.assertTrue((self.wm_state / "pass-timing.jsonl").exists(), "it ran as a pass")
        self.assertLessEqual(len(got["mods"]), BOUND, "\n".join(got["mods"]))


if __name__ == "__main__":
    unittest.main()
