"""The farmer's delegate runs the overlap check before the foreman starts (plan 0593 step 6; plan 0592 D16): the hits go
into the brief and beside it; create.py is told not to scan again; a missing CLI never blocks."""
import json
import sys
import unittest
from pathlib import Path

import delegation
from skillpath import sibling

sys.path.append(str(sibling("plan") / "scripts"))  # the testkit only; appended, it shadows no module of ours
from overlap_testkit import EMPTY, HIT, calls, fake_cli
from test_delegation import MAIN, NOW, Ledger, flaky


class DelegationOverlap(Ledger):
    def delegate(self, answer):
        with fake_cli(answer) as cli:
            result = delegation.delegate(flaky(), MAIN, 5, False, NOW)
            made = calls(cli)
        brief = Path(result["brief"])
        return result, brief, made

    def test_hits_are_in_the_brief_and_beside_it(self):
        result, brief, made = self.delegate(HIT)
        self.assertEqual(result["state"], "running")
        text = brief.read_text()
        self.assertIn("## Overlap with unfinished work", text)
        self.assertIn("## Overlap with unfinished work\n\n- CLI-REPORT\n", text)  # the CLI's report, its settle hint
        self.assertNotIn("Settle each hit", text)  # no copy of it
        self.assertEqual(json.loads(brief.with_name(brief.name + ".overlap.json").read_text()), HIT)
        self.assertIn("disable the load-flaky test t", made[0][made[0].index("--goal") + 1])
        (create,) = [c for c in self.calls if c[:2] == delegation.CREATE]
        self.assertIn("--no-overlap", create)

    def test_an_overlap_resolved_brief_says_none(self):
        _, brief, _ = self.delegate(EMPTY)
        self.assertIn("## Overlap with unfinished work\n\n- CLI-REPORT-NONE\n", brief.read_text())

    def test_without_the_cli_the_foreman_still_starts_and_the_brief_says_unchecked(self):
        result, brief, _ = self.delegate(None)
        self.assertEqual(result["state"], "running")
        self.assertIn("## Overlap with unfinished work\n\n- overlap: overlap unchecked\n", brief.read_text())


if __name__ == "__main__":
    unittest.main()
