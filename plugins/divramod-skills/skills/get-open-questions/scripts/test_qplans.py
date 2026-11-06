"""q.py prints the related plans' questions in sections: the current plan, its masterplan, its rows running here (plan 0683)."""
import copy
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "q.py"

# The fake hal2-cli-plans (python), answering from a JSON file `fake.json` beside it:
#   show <n> [--repo R] [--json]            -> plans[n] (number, title, slug, parent); exit 1 when "fail_show" lists n
#   masterplan <n> [--repo R] [--json]      -> {"rows": masterplans[n]}
#   questions list --open|--answered|--all --markdown|--json --store <rel>
#                                           -> the store's text/entries; EMPTY stdout, exit 0 for a store with none
#   questions check --json --store <rel>    -> {"problems": []}
FAKE = r'''#!/usr/bin/env python3
import json, sys
from pathlib import Path
cfg = json.loads((Path(__file__).parent / "fake.json").read_text())
a = [x for x in sys.argv[1:] if x != "--json"]
def opt(name):
    return a[a.index(name) + 1] if name in a else None
if a[0] == "show":
    if a[1] in cfg["fail_show"]:
        sys.exit(1)
    print(json.dumps(cfg["plans"][a[1].lstrip("0")]))
elif a[0] == "masterplan":
    print(json.dumps({"rows": cfg["masterplans"][a[1].lstrip("0")]}))
elif a[:2] == ["questions", "check"]:
    print(json.dumps({"problems": []}))
elif a[:2] == ["questions", "list"]:
    store = opt("--store")
    if store is None and "--plan" in a:
        n = opt("--plan").lstrip("0")
        store = f"plans/{cfg['plans'][n]['slug']}/questions.md"
    mode = "all" if "--all" in a else "answered" if "--answered" in a else "open"
    items = cfg["stores"].get(store, {}).get(mode, [])
    if "--markdown" in a and items:
        print(f"{len(items)} {mode} question{'s' * (len(items) != 1)} ({store})\n\n" + "\n\n".join(items))
    elif items:
        print(json.dumps({"store": store, "mode": mode, "entries": [{"n": i + 1, "question": t} for i, t in enumerate(items)]}))
else:
    sys.exit(2)
'''

PLANS = {"1": {"number": 1, "title": "Master", "slug": "0001-master", "parent": None},
         "2": {"number": 2, "title": "Sub", "slug": "0002-sub", "parent": 1},
         "3": {"number": 3, "title": "Row three", "slug": "0003-row", "parent": 1},
         "4": {"number": 4, "title": "Row four", "slug": "0004-row", "parent": 1},
         "5": {"number": 5, "title": "Row five", "slug": "0005-row", "parent": 1}}
ROWS = [{"number": 2, "title": "Sub", "kind": "plan", "status": "running", "checkout": "33"},
        {"number": 3, "title": "Row three", "kind": "plan", "status": "running", "checkout": "33"},
        {"number": 4, "title": "Row four", "kind": "plan", "status": "running", "checkout": "06"},
        {"number": 5, "title": "Row five", "kind": "plan", "status": "done", "checkout": "33"}]
OPEN = {"plans/0002-sub/questions.md": {"open": ["Q1: sub one", "Q2: sub two"], "answered": ["Q3: sub done"]},
        "plans/0001-master/questions.md": {"open": ["Q1: master one"], "all": ["Q1: master one", "Q2: master done"]},
        "plans/0004-row/questions.md": {"open": ["Q1: row four"]},
        "plans/0005-row/questions.md": {"open": ["Q1: row five"]}}


class Sections(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.root = base / "33"  # the field's name
        (self.root / ".git").mkdir(parents=True)
        (self.root / "plans" / "0002-sub").mkdir(parents=True)
        (self.root / "plans" / "0002-sub" / "plan.md").write_text("# Plan 0002: Sub\n")
        (self.root / "plans" / "CURRENT_PLAN").write_text("0002-sub\n")
        self.cli = base / "hal2-cli-plans"
        self.cli.write_text(FAKE)
        self.cli.chmod(self.cli.stat().st_mode | stat.S_IXUSR)
        self.cfg = copy.deepcopy({"plans": PLANS, "masterplans": {"1": ROWS}, "stores": OPEN, "fail_show": []})
        self.write_cfg()

    def tearDown(self):
        self.tmp.cleanup()

    def write_cfg(self):
        (self.cli.parent / "fake.json").write_text(json.dumps(self.cfg))

    def q(self, *args):
        env = {**os.environ, "HAL2_CLI_PLANS": str(self.cli)}
        return subprocess.run(["python3", str(SCRIPT), *args], cwd=self.root, text=True, capture_output=True, env=env)

    def headings(self, out):
        return [ln for ln in out.splitlines() if ln[:4].isdigit() and ln[4:5] == " "]

    def test_open_prints_current_master_and_running_rows_in_order(self):
        out = self.q()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.headings(out.stdout), ["0002 Sub", "0001 Master", "0003 Row three"])
        text = out.stdout
        self.assertLess(text.index("sub one"), text.index("master one"))
        self.assertNotIn("row four", text)  # running in another field
        self.assertNotIn("row five", text)  # done
        self.assertEqual(text.count("0002 Sub"), 1)  # the current plan is not repeated as a row

    def test_a_plan_without_open_questions_prints_its_heading_and_the_none_line(self):
        text = self.q().stdout
        self.assertTrue(text.rstrip().endswith("0003 Row three\nno open questions"), text)

    def test_sections_are_apart_by_a_blank_line(self):
        self.assertIn("\n\n0001 Master\n", self.q().stdout)

    def test_answered_mode_picks_the_answered_questions(self):
        out = self.q("a").stdout
        self.assertEqual(self.headings(out), ["0002 Sub", "0001 Master", "0003 Row three"])
        self.assertIn("sub done", out)
        self.assertNotIn("sub one", out)
        self.assertIn("no answered questions", out)

    def test_list_mode_picks_all_questions(self):
        out = self.q("l").stdout
        self.assertIn("master done", out)
        self.assertEqual(self.headings(out), ["0002 Sub", "0001 Master", "0003 Row three"])

    def test_json_keeps_the_current_plans_shape_and_adds_plans(self):
        data = json.loads(self.q("--json").stdout)
        self.assertEqual(data["store"], "plans/0002-sub/questions.md")
        self.assertEqual(data["mode"], "open")
        self.assertEqual(len(data["entries"]), 2)
        self.assertEqual(data["problems"], [])
        self.assertEqual([(p["number"], p["title"], p["role"]) for p in data["plans"]],
                         [(2, "Sub", "current"), (1, "Master", "masterplan"), (3, "Row three", "row")])
        for p in data["plans"]:
            self.assertEqual(set(p), {"number", "title", "role", "store", "entries", "problems"})
        self.assertEqual(data["plans"][1]["store"], "plans/0001-master/questions.md")
        self.assertEqual(len(data["plans"][1]["entries"]), 1)
        self.assertEqual(data["plans"][2]["entries"], [])

    def test_a_lone_plan_prints_without_headings(self):
        self.cfg["plans"]["2"]["parent"] = None
        self.write_cfg()
        out = self.q().stdout
        self.assertEqual(self.headings(out), [])
        self.assertTrue(out.startswith("2 open questions (plans/0002-sub/questions.md)\n"), out)
        self.assertNotIn("master one", out)
        self.assertNotIn("plans", json.loads(self.q("--json").stdout))

    def test_a_failing_parent_lookup_still_prints_the_current_plan(self):
        self.cfg["fail_show"] = ["1"]
        self.write_cfg()
        out = self.q()
        self.assertEqual(out.returncode, 0)
        self.assertIn("sub one", out.stdout)
        self.assertNotIn("master one", out.stdout)


if __name__ == "__main__":
    unittest.main()
