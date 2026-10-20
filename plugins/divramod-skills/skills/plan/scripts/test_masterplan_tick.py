"""The tick's guards and what it says (hal2 plan 0275 D36), through plan.py: a row whose cells are not its header's
is never written, only a `done` row is reopened, every row that links the plan is ticked, `tick_skipped` says why
nothing was; a masterplan's plan.md keeps its line ends and its UTF-8 and is written in one move; `new --parent`
leaves nothing behind and `new --masterplan` skips a masterplan it cannot read.

Every test works in a scratch repository; none needs hal2 (test_masterplan.py's fixture, whose helpers it borrows)."""
import json
import os
import subprocess
import sys
import unittest

import test_masterplan as base
import test_masterplan_keep as keep

MASTER, TOOLS = base.MASTER, keep.TOOLS
ASCII = {"LC_ALL": "C", "LANG": "C", "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0"}


class TickTest(unittest.TestCase):
    setUp, tearDown = base.MasterplanTest.setUp, base.MasterplanTest.tearDown
    run_plan, plan, refused = base.MasterplanTest.run_plan, base.MasterplanTest.plan, base.MasterplanTest.refused
    write, farm = base.MasterplanTest.write, base.MasterplanTest.farm
    two_plans, row, finish = keep.KeepTest.two_plans, keep.KeepTest.row, keep.KeepTest.finish

    def set_row(self, master, number: str, status: str) -> None:
        """Write the Status cell of the masterplan's row `number` by hand."""
        lines = master.read_text().split("\n")
        at = next(i for i, line in enumerate(lines) if line.startswith(f"| {number} | ["))
        lines[at] = f"{lines[at].rstrip(' |').rsplit('|', 1)[0]}| {status} |"
        master.write_text("\n".join(lines))

    # a row that does not fit its header

    def test_the_tick_never_writes_a_row_whose_cells_are_not_the_headers_and_says_so(self):
        master = self.farm()
        master.write_text(master.read_text().replace(") tools |", ") tools `a|b` |"))  # an unescaped `|`: 8 cells
        before = master.read_text()

        info = self.finish(TOOLS)
        self.assertNotIn("tick", info)
        self.assertEqual(info["tick_skipped"], f"row 1 of masterplan {MASTER} is not written: it has 8 cells, its "
                                               "header 7: write a `|` inside a cell as `\\|`")
        self.assertEqual(master.read_text(), before)

    def test_plan_py_writes_no_cell_into_a_row_whose_cells_are_not_the_headers(self):
        path = self.write("0004-shifted")
        path.write_text(path.read_text().replace("| 1 | one |", "| 1 | one `a|b` |"))
        before = path.read_text()
        for command in (("status", "1", "done"), ("assign", "1", "lead", "--force"), ("migrate",)):
            self.assertIn("has 8 cells, its header 7", self.refused(*command, "--plan", "4"), command)
        self.assertEqual(path.read_text(), before)

    # which rows the tick writes

    def test_only_a_done_row_is_reopened_and_a_finished_plan_makes_any_row_done(self):
        master = self.two_plans()
        for status in ("blocked waits for the user", "draft", "done soon"):  # an open plan: the row stays
            self.set_row(master, "1", status)
            self.assertNotIn("tick", self.plan("status", "1", "next", "--plan", TOOLS))
            self.assertEqual(self.row(master, "1"), status)
        for status in ("blocked waits for the user", "draft"):  # the plan is stamped finished: `done`, whatever it read
            self.set_row(master, "1", status)
            self.assertEqual(self.finish(TOOLS)["tick"]["status"], "done")
            self.assertEqual(self.row(master, "1"), "done")
            self.set_row(master, "1", "done (brought in with 0003)")
            self.assertEqual(self.plan("status", "2", "next", "--plan", TOOLS)["tick"]["status"], "running")
            self.assertEqual(self.row(master, "1"), "running")

    def test_every_row_that_links_the_plan_is_ticked(self):
        master = self.farm()
        text = master.read_text()
        line = next(l for l in text.splitlines() if l.startswith("| 1 | ["))
        master.write_text(text.replace(line, line + "\n" + line.replace("| 1 |", "| 2 |", 1)))

        self.assertEqual(self.finish(TOOLS)["tick"], {"masterplan": MASTER, "row": "1, 2", "status": "done",
                                                      "masterplan_finished": True})
        self.assertEqual((self.row(master, "1"), self.row(master, "2")), ("done", "done"))
        self.assertEqual(self.plan("status", "2", "next")["tick"]["row"], "1, 2")
        self.assertEqual((self.row(master, "1"), self.row(master, "2")), ("running", "running"))

    def test_the_tick_says_why_it_did_nothing(self):
        self.farm()
        self.assertNotIn("tick_skipped", self.plan("status", "1", "next"))  # the row agrees: nothing to say
        self.write("0005-lonely", keys="parent: 1\n")  # names the masterplan, which has no row for it
        info = self.plan("status", "1", "done", "--plan", "5")
        self.assertEqual(info["tick_skipped"], f"no row of masterplan {MASTER} links 0005-lonely")
        self.write("0006-far", keys="parent: 42\n")  # its masterplan's folder is not in this checkout
        info = self.plan("status", "1", "done", "--plan", "6")
        self.assertIn("plan 0042, the `parent` of 0006-far, has no folder in this checkout", info["tick_skipped"])
        self.assertNotIn("tick", info)
        self.write("0007-child", keys="parent: 5\n")  # its parent is an ordinary plan: no tick, nothing skipped
        self.assertNotIn("tick_skipped", self.plan("status", "1", "done", "--plan", "7"))

    # the masterplan's file

    def test_a_masterplan_keeps_its_line_ends_and_is_written_in_one_move(self):
        master = self.farm()
        master.write_bytes(master.read_bytes().replace(b"\n", b"\r\n"))
        inode, files = master.stat().st_ino, sorted(p.name for p in master.parent.iterdir())

        self.plan("new", "view", "--parent", "1", "--schema", "1")  # its row is added
        self.assertNotEqual(master.stat().st_ino, inode)  # a temp file moved over it, never a write in place
        self.assertEqual(self.finish(TOOLS)["tick"]["row"], "1")  # row 1 is ticked
        data = master.read_bytes()
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"))
        self.assertIn(b") view |  |  | lead |", data)
        self.assertIn(b"| done |\r\n", data)
        self.assertEqual(sorted(p.name for p in master.parent.iterdir()), files)  # no temp file is left

    def test_the_masterplan_modules_read_and_write_utf_8_whatever_the_locale_says(self):
        master = self.farm()
        child = self.plans / TOOLS / "plan.md"
        master.write_text(master.read_text(encoding="utf-8").replace(") tools |", ") Ähren 🌾 |"), encoding="utf-8")
        child.write_text(child.read_text(encoding="utf-8").replace("status: open", "status: done"), encoding="utf-8")
        code = ("import json, pathlib, sys, masterplan, masterplan_keep\n"
                "child = pathlib.Path(sys.argv[1])\n"
                "print(json.dumps([masterplan_keep.tick(child), masterplan.pick_crop(child.parents[2])]))")
        out = subprocess.run([sys.executable, "-c", code, str(child)], cwd=base.HERE, env={**os.environ, **ASCII},
                             capture_output=True, text=True)

        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), [{"masterplan": MASTER, "row": "1", "status": "done"}, "corn"])
        self.assertIn(") Ähren 🌾 |  |  | lead |", master.read_text(encoding="utf-8"))

    def test_new_masterplan_skips_a_masterplan_it_cannot_read(self):
        broken = self.plans / "0001-masterplan-broken" / "plan.md"
        broken.parent.mkdir(parents=True)
        broken.write_bytes(b"---\ncrop: wheat\n\xff\xfe")  # no UTF-8
        (self.plans / "0002-masterplan-folder" / "plan.md").mkdir(parents=True)  # a folder: no file to read
        info = self.plan("new", "farm", "--masterplan")
        self.assertEqual((info["slug"], info["crop"]), ("0003-masterplan-farm", "wheat"))

    # new --parent

    def test_new_parent_leaves_nothing_behind_when_the_row_cannot_be_written(self):
        self.plan("new", "Masterplan farm view", "--masterplan")
        master = self.plans / MASTER / "plan.md"
        text = master.read_text()
        master.write_text(text.split("| # |")[0])  # no step table
        (self.plans / "0005-masterplan-flat.md").write_text(text)  # a masterplan without its folder
        self.assertIn(f"{MASTER} has no step table", self.refused("new", "tools", "--parent", "1"))
        self.assertIn("0005-masterplan-flat, a flat plan file", self.refused("new", "tools", "--parent", "5"))
        self.assertEqual([p.name for p in self.plans.iterdir() if p.is_dir()], [MASTER])
        self.assertEqual((self.plans / "CURRENT_PLAN").read_text(), MASTER + "\n")


if __name__ == "__main__":
    unittest.main()
