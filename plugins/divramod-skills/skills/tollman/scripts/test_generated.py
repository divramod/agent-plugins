"""Hal2 plan 0313 step 8 (D13): a trial-merge conflict only in generated files is no unhitch. The case of 2026-10-14
(the tollman's train.jsonl, 11:04:57Z): fields 07 and 13 conflicted with the barn only in plans/uats.md, which
every foreman writes again, and were unhitched by hand. On engine_farm's farm (a bare origin, no landing, D5), the
map `.github/hal2-versions.toml` names a fake regenerator, `gen.py`, which writes plans/uats.md from the plans'
uat.md files, as `hal2-cli-plans uat generated` does."""

import json
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import generated
import train_state
from engine_farm import OWN, Farm, out
from test_farmer import git

MAP = """[[generated]]
command = ["python3", "gen.py"]
paths = ["plans/uats.md", "AGENTS.md", "plans/*/uat-results.jsonl"]
"""
GEN = """import json, subprocess, sys
rev = sys.argv[sys.argv.index("--rev") + 1]
names = subprocess.run(["git", "ls-tree", "-r", "--name-only", rev, "plans"], capture_output=True, text=True).stdout
plans = sorted(n.split("/")[1] for n in names.split() if n.endswith("/uat.md"))
print(json.dumps({"files": {"plans/uats.md": "# UATs\\n" + "".join(p + "\\n" for p in plans),
                            "elsewhere.md": "a file outside the entry's paths is dropped"}, "problems": []}))
"""

AGENTS = "# Rules\n\n{hand}\n\n<!-- generated: rules -->\n{rules}\n<!-- /generated -->\n"


def uats(*plans):
    return "# UATs\n" + "".join(p + "\n" for p in plans)


class GeneratedConflicts(Farm):
    def setUp(self):
        super().setUp()
        for name, text in ((".github/hal2-versions.toml", MAP), ("gen.py", GEN),
                           ("plans/0001/uat.md", "# UAT\n"), ("plans/uats.md", uats("0001"))):
            self.commit(self.main, name, text)
        git(self.main, "push", "-q", "origin", "HEAD")

    def plan_crop(self, field, plan, more=None):
        """A foreman's crop with its plan's uat.md and the overview it wrote again: the barn's plus its own."""
        files = {f"plans/{plan}/uat.md": "# UAT\n", "plans/uats.md": uats("0001", plan)}
        return self.crop(field, {**files, **(more or {})})

    def barn(self, plan, more=None):
        """The train before (09's) is in the barn: its uat.md and its overview."""
        files = {f"plans/{plan}/uat.md": "# UAT\n", "plans/uats.md": uats("0001", plan), **(more or {})}
        for name, text in files.items():
            self.commit(self.main, name, text)
        git(self.main, "push", "-q", "origin", "HEAD")

    def test_07_and_13_conflicting_only_in_plans_uats_md_ride_and_the_last_commit_writes_it_again(self):
        self.plan_crop("07", "0007")
        self.plan_crop("13", "0013")
        self.barn("0009")
        d = json.loads(self.call("train", "--dry-run", "--json")[1])
        self.assertEqual(([c["field"] for c in d["cars"]], d["unhitched"]), (["07", "13"], []))
        r = self.round()
        self.assertEqual((self.last, r["wake"]), ([("form", "run", "-")], []))
        self.assertEqual(self.gate.calls, [["worktree", "queue", "train", OWN, "07", "13"]])
        self.assertEqual(self.state(), [("formed", OWN), ("regenerated", OWN), ("started", OWN)])
        self.assertEqual(self.subjects()[0], generated.SUBJECT, "the regeneration is the train's last commit")
        self.assertEqual(out(self.wm, "log", "-1", "--format=%(trailers:key=Worktree,valueonly,separator=%x2C)").strip().replace(" ", ""),
                         "07,13", "the cars' fields, in car order, as the origin trailer (plan 0355)")
        self.assertEqual(out(self.wm, "show", "HEAD:plans/uats.md") + "\n", uats("0001", "0007", "0009", "0013"))
        self.assertEqual(out(self.wm, "status", "--porcelain", "--untracked-files=no"), "")
        self.assertFalse((self.wm / "elsewhere.md").exists(), "only the entry's paths are written")
        line = [e for e in train_state.lines(str(self.main)) if e["kind"] == "regenerated"][0]
        self.assertEqual((line["commit"], line["files"]), (out(self.wm, "rev-parse", "HEAD"), ["plans/uats.md"]))
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["07", "13"])

    def test_a_conflict_in_generated_and_other_files_still_unhitches(self):
        self.commit(self.main, "vimPreset.ts", "base\n", push=True)
        self.plan_crop("05", "0005", {"vimPreset.ts": "five\n"})
        self.plan_crop("13", "0013")
        self.barn("0009", {"vimPreset.ts": "barn\n"})
        self.round()
        self.assertEqual(self.last, [("unhitch", "run", "05"), ("unhitched", "relay", "05"), ("form", "run", "-")])
        why = [e for e in train_state.lines(str(self.main)) if e["kind"] == "unhitched"][0]["why"]
        self.assertEqual(why, "conflicts with the barn in plans/uats.md, vimPreset.ts")
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["13"])

    def test_a_conflict_in_the_hand_written_part_of_a_partly_generated_file_unhitches(self):
        self.commit(self.main, "AGENTS.md", AGENTS.format(hand="base", rules="- a"), push=True)
        self.crop("05", {"AGENTS.md": AGENTS.format(hand="five", rules="- a")})
        self.barn("0009", {"AGENTS.md": AGENTS.format(hand="barn", rules="- a")})
        self.round()
        self.assertEqual(self.last[:2], [("unhitch", "run", "05"), ("unhitched", "relay", "05")])
        conflict = "<<<<<<< ours\n{}\n=======\nb\n>>>>>>> x"
        self.assertTrue(generated.in_blocks(AGENTS.format(hand="h", rules=conflict.format("- a"))))
        self.assertFalse(generated.in_blocks(AGENTS.format(hand=conflict.format("h"), rules="- a")))
        self.assertTrue(generated.in_blocks("# UATs\n" + conflict.format("0007")), "generated whole")

    def test_a_conflict_in_a_plan_s_uat_results_still_unhitches_its_verdicts_are_never_the_barn_s(self):
        self.commit(self.main, "plans/0001/uat-results.jsonl", '{"check": 1}\n', push=True)
        self.plan_crop("05", "0005", {"plans/0001/uat-results.jsonl": '{"check": 1}\n{"check": 2, "by": "05"}\n'})
        self.barn("0009", {"plans/0001/uat-results.jsonl": '{"check": 1}\n{"check": 2, "by": "barn"}\n'})
        self.round()
        self.assertEqual(self.last[:2], [("unhitch", "run", "05"), ("unhitched", "relay", "05")])
        self.assertFalse(generated.only(str(self.main), "HEAD", ["plans/0001/uat-results.jsonl"]))

    def test_a_failing_regenerator_breaks_the_train_up_and_wakes_the_session_no_car_is_unhitched(self):
        self.plan_crop("07", "0007")
        self.barn("0009")
        why = ValueError("python3 gen.py: code/a/libs/x/README.md: missing")
        with mock.patch.object(generated, "printed", side_effect=why):
            r = self.round()
        form = next(a for a in r["planned"] if a["kind"] == "form")
        self.assertEqual((self.last, [w["kind"] for w in r["wake"]], form["exit"]),
                         ([("form", "run", "-")], ["train-stuck"], 1))
        self.assertIn("not written again: python3 gen.py: code/a/libs/x/README.md: missing", form["output"])
        self.assertEqual(self.state(), [("formed", OWN), ("regenerated", OWN), ("cleared", OWN)])
        self.assertEqual((self.train(), self.spawned, self.gate.of("07")["ready"] is not None), (None, [], True))
        self.assertEqual(out(self.wm, "rev-parse", "HEAD"), out(self.main, "rev-parse", "HEAD"), "back on the barn")

    def test_without_a_map_nothing_is_generated_and_a_glob_stays_in_its_segment(self):
        git(self.main, "rm", "-q", ".github/hal2-versions.toml")
        git(self.main, "commit", "-qm", "no map")
        git(self.main, "push", "-q", "origin", "HEAD")
        self.assertEqual((generated.entries(str(self.main)), generated.only(str(self.main), "HEAD", ["plans/uats.md"])),
                         ([], False))
        self.assertTrue(generated.only(str(self.main), "HEAD~1", ["plans/uats.md"]))
        self.assertFalse(generated.only(str(self.main), "HEAD~1", []))
        self.assertTrue(generated.matches("code/*/docs/codemap.md", "code/rust/docs/codemap.md"))
        self.assertFalse(generated.matches("code/*/docs/codemap.md", "code/rust/x/docs/codemap.md"))


if __name__ == "__main__":
    unittest.main()
