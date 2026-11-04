"""spec.py new runs the overlap check (plan 0593 step 6; plan 0592 D16): overlap.json beside the spec, a Context line in
its plan.md, the hits printed to settle; an overlap-resolved fixture (an empty answer) and a missing CLI never block."""
import json
import unittest

from spec_testkit import SpecCase, spec  # noqa: F401
from overlap_testkit import EMPTY, HIT, calls, fake_cli


class SpecOverlap(SpecCase):
    def new_with(self, answer):
        with fake_cli(answer) as cli:
            code, out, err = self.run_spec("new", "Login with passkeys", "--json")
            made = calls(cli)
        self.assertEqual(code, 0, err)
        return json.loads(out), err, made

    def test_hits_are_recorded_beside_the_spec_and_printed_to_settle(self):
        info, err, made = self.new_with(HIT)
        folder = self.root / info["dir"] if "dir" in info else (self.root / info["spec"]).parent
        self.assertEqual(json.loads((folder / "overlap.json").read_text()), HIT)
        self.assertIn("- Overlap: 0571-milestone-hitch, 0131-plan-consistency", (folder / "plan.md").read_text())
        self.assertIn("settle each hit before writing", err)
        self.assertEqual(len(info["overlap"]), 2)
        self.assertEqual(len(made), 1)
        self.assertIn("Login with passkeys", made[0][made[0].index("--goal") + 1])

    def test_an_overlap_resolved_spec_has_a_checked_line(self):
        info, err, _ = self.new_with(EMPTY)
        folder = (self.root / info["spec"]).parent
        self.assertIn("- Overlap: checked", (folder / "plan.md").read_text())
        self.assertIn("overlap: none", err)

    def test_without_the_cli_the_spec_is_written_and_says_unchecked(self):
        info, err, _ = self.new_with(None)
        folder = (self.root / info["spec"]).parent
        self.assertTrue((folder / "spec.md").is_file())
        self.assertFalse((folder / "overlap.json").exists())
        self.assertIn("overlap unchecked", err)


if __name__ == "__main__":
    unittest.main()
