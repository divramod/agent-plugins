"""prune.py run's order and speed (hal2 plan 0534 step 5, D13): removals before stale pointers, one step per pointer
also when an agent's scratch worktree carries a field's name, a re-check that never re-gathers the farm, and a farm
lock its TERMed holder leaves behind taken over. On a scratch farm behind fake CLIs (fake_clis.py), tmp only."""

import os
import signal
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import fake_clis
import facts
import responses
import sizes
from fake_clis import parse
from test_farmer import git

class Order(fake_clis.Farm):
    def stale(self, slot: str, root: Path | None = None) -> Path:
        path = root or self.add(slot)
        (path / "plans").mkdir(exist_ok=True)
        (path / "plans/CURRENT_PLAN").write_text("0149-x\n")
        return path

    def test_a_free_field_is_removed_before_any_pointer_is_cleared(self):
        self.add("23")
        self.stale("13")
        self.feed(plans={"0149-x": {"state": "done"}})
        code, lines = self.prune()
        self.assertEqual(code, 0, lines)
        out = parse(lines)
        self.assertLess(list(out).index("phase-1"), list(out).index("stale-pointers"))
        self.assertEqual([(s[0], s[1]) for s in out["phase-1"]], [("field 23", "success")])
        clear, removal = out["stale-pointers"]
        self.assertEqual((clear[2][0], removal[0], removal[1]), ("cleared CURRENT_PLAN 0149-x (finished)", "field 13",
                                                                 "success"))
        self.assertEqual([c[2] for c in self.calls()], ["23", "13"], "23 went first, 13 in the same round")

    def test_one_step_per_pointer_though_a_scratch_worktree_has_the_fields_name(self):
        """Step 4's run: the tollman's `<scratchpad>/resolve/13` made field 13 a twin, two clears, the wrong folder."""
        real = self.stale("13")
        scratch = self.tmp / "scratchpad/resolve/13"
        git(self.main, "worktree", "add", "-q", "-b", "resolve-13", str(scratch), "origin/main")
        self.stale("13", scratch)
        self.feed(plans={"0149-x": {"state": "done"}})
        code, lines = self.prune()
        self.assertEqual(code, 0, lines)
        clears = [s for s in parse(lines)["stale-pointers"] if any(x.startswith("cleared CURRENT_PLAN") for x in s[2])]
        self.assertEqual([s[0] for s in clears], ["field 13"])
        self.assertFalse(real.exists(), "the real field was freed and removed")
        self.assertEqual((scratch / "plans/CURRENT_PLAN").read_text(), "0149-x\n", "the scratch folder is untouched")

    def test_a_recheck_collects_its_one_field_without_sizes_responses_or_the_cli_list(self):
        for slot in ("13", "14"):
            self.stale(slot)
        self.feed(plans={"0149-x": {"state": "done"}})
        real, seen = facts.collect, []

        def collect(main, only=None, **kw):
            seen.append((sorted(only) if only else None, kw.get("answers", True)))
            return real(main, only=only, **kw)

        walks = mock.MagicMock(side_effect=responses.candidates)
        with mock.patch.object(facts, "collect", side_effect=collect), \
                mock.patch.object(facts.responses, "candidates", walks), \
                mock.patch.object(sizes, "measure_all", wraps=sizes.measure_all) as measure:
            code, lines = self.prune()
        self.assertEqual(code, 0, lines)
        self.assertEqual(seen[0], (None, True), "the facts job gathers the farm once")
        self.assertTrue(len(seen) > 3 and all(len(o) == 1 and not a for o, a in seen[1:]), seen)
        self.assertEqual((walks.call_count, measure.call_count), (1, 1))
        self.assertEqual(self.calls("hal2-cli-git", "list"), [], "the fields come from git, not the CLI's 30 s list")

    def test_a_lock_left_by_a_terminated_run_is_taken_over(self):
        self.add("23")
        here = str(Path(__file__).resolve().parent)
        code = (f"import sys, time; sys.path.insert(0, {here!r}); import store\n"
                f"with store.farm_lock({str(self.main)!r}):\n    print('held', flush=True); time.sleep(60)")
        holder = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, env=os.environ)
        self.addCleanup(holder.stdout.close)
        self.addCleanup(holder.kill)
        self.assertEqual(holder.stdout.readline().strip(), "held")
        holder.send_signal(signal.SIGTERM)  # step 4: the run was TERMed, its lock.json kept the dead pid
        holder.wait()
        code, lines = self.prune()
        self.assertEqual(code, 0, lines)
        self.assertFalse(any(x.startswith("already running") for x in lines), lines)
        self.assertFalse((self.base / "23").exists())


if __name__ == "__main__":
    unittest.main()
