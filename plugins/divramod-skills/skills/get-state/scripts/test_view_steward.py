"""The steward's page (hal2 plan 0366 D9): the daybook reader over a fixture day file, the plan rows, the UAT reader
over a canned `hal2-cli-plans uat list --json`, and the view with its empty states. No real tool is called."""

import datetime as dt
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import page
import state_sources as src
import steward_sources as ss
import view_steward as vs

CTX = {"role": "steward", "repo": "proj", "checkout": "main", "top": "/x", "main": "/x", "today": dt.date(2026, 10, 18)}
DAY = """# Daybook 2026-10-18 (Sunday)

## Today

- [ ] call the plumber
  with a second line
- [x] ticked chore

## Later

- [ ] <script>alert(1)</script> chore

## Watches

<!-- generated -->
- [ ] watch item [watch:ci]

## Plans

## Done

- [ ] 10:00 not a chore
"""


def row(wt, done, total, number="0007", name="the-plan", **kw) -> dict:
    return {"wt": wt, "plan_number": number, "plan_name": name, "steps_done": done, "steps_total": total, **kw}


def uat_plan(slug, *states) -> dict:
    return {"slug": slug, "title": slug[5:], "checks": [
        {"key": f"U{i}", "check": {"title": f"check {i}"}, "status": {"state": s}} for i, s in enumerate(states, 1)]}


class Daybook(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ["DAYBOOK_DIR"] = str(self.tmp)

    def test_open_chores_of_today_and_later_only(self):
        (self.tmp / "2026-10-18.md").write_text(DAY, encoding="utf-8")
        got = ss.chores(str(self.tmp), dt.date(2026, 10, 18))
        self.assertEqual(got["date"], "2026-10-18")
        self.assertEqual(got["items"], [("today", "call the plumber"), ("later", "<script>alert(1)</script> chore")])

    def test_without_a_day_file_for_today_the_newest_earlier_one(self):
        (self.tmp / "2026-10-16.md").write_text("## Today\n\n- [ ] old one\n", encoding="utf-8")
        (self.tmp / "2026-10-17.md").write_text("## Today\n\n- [ ] newer one\n", encoding="utf-8")
        (self.tmp / "2026-10-19.md").write_text("## Today\n\n- [ ] future\n", encoding="utf-8")
        got = ss.chores(str(self.tmp), dt.date(2026, 10, 18))
        self.assertEqual((got["date"], got["items"]), ("2026-10-17", [("today", "newer one")]))

    def test_no_day_file_or_folder_is_unknown_and_nothing_is_written(self):
        self.assertIsNone(ss.chores(str(self.tmp), dt.date(2026, 10, 18)))
        os.environ["DAYBOOK_DIR"] = str(self.tmp / "none")
        self.assertIsNone(ss.chores(str(self.tmp), dt.date(2026, 10, 18)))
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_a_missing_daybook_skill_is_unknown(self):
        with mock.patch.object(ss, "sibling", side_effect=FileNotFoundError("daybook")):
            self.assertIsNone(ss.chores(str(self.tmp)))

    def test_an_unreadable_day_file_is_unknown(self):
        (self.tmp / "2026-10-18.md").write_bytes(b"\xff\xfe## Today")
        self.assertIsNone(ss.chores(str(self.tmp), dt.date(2026, 10, 18)))


class Uats(unittest.TestCase):
    def test_plans_with_checks_still_to_run(self):
        raw = [uat_plan("0001-a", "pass", "skip"), uat_plan("0002-b", "pass", "untested", "fail"), {"slug": "0003-c"}, "junk"]
        with mock.patch.object(src, "tool_json", return_value=raw) as tool:
            got = ss.open_uats("/m")
        self.assertEqual(got, [{"plan": "0002-b", "title": "b", "open": 2, "failed": 1, "next": "U2 check 2"}])
        self.assertEqual(tool.call_args.args[0], ["hal2-cli-plans", "uat", "list", "--json"])

    def test_a_tool_that_gives_nothing_is_unknown(self):
        with mock.patch.object(src, "tool_json", return_value=None):
            self.assertIsNone(ss.open_uats("/m"))


class View(unittest.TestCase):
    def sections(self, rows, chores, uats) -> dict:
        with mock.patch.object(ss, "chores", return_value=chores), mock.patch.object(ss, "open_uats", return_value=uats):
            title, sections = vs.view({"repo": "/x", "rows": rows}, CTX)
        self.assertEqual(title, "proj · steward")
        return {s["heading"].split(" (")[0]: s for s in sections}

    def test_the_three_sections(self):
        rows = [row("main", 1, 3, "0001", "m", is_main=True), row("10", 2, 5), row("02", 5, 5), row("03", None, None),
                row("04", 0, 4, None, None), row("05", 1, 2, "0009", "nine")]
        got = self.sections(rows, {"date": "2026-10-18", "items": [("today", "a"), ("later", "b")]},
                            [{"plan": "0002-b", "title": "b", "open": 2, "failed": 1, "next": "U2 check 2"}])
        self.assertEqual(got["Daybook 2026-10-18: open chores"]["rows"], [["Today", "a"], ["Later", "b"]])
        self.assertEqual(got["Unfinished plans"]["rows"],
                         [["05", "0009 nine", "1/2"], ["10", "0007 the-plan", "2/5"], ["main", "0001 m", "1/3"]])
        self.assertEqual(got["Open UAT checks"]["rows"], [["0002-b", 2, 1, "U2 check 2"]])

    def test_every_empty_state(self):
        got = self.sections([row("02", 5, 5)], {"date": "2026-10-18", "items": []}, [])
        self.assertEqual(got["Daybook 2026-10-18: open chores"]["empty"], "No open chores.")
        self.assertEqual(got["Unfinished plans"]["empty"], "No unfinished plan.")
        self.assertEqual(got["Open UAT checks"]["empty"], "No open UAT check.")
        html = page.render("t", list(got.values()))
        for line in ("No open chores.", "No unfinished plan.", "No open UAT check."):
            self.assertIn(line, html)
        self.assertNotIn("<table>", html)

    def test_unknown_sources_say_so(self):
        got = self.sections([], None, None)
        self.assertIn("No daybook day file", got["Daybook"]["empty"])
        self.assertIn("unknown", got["Open UAT checks"]["empty"])

    def test_failures_first_and_the_list_is_capped(self):
        plans = [{"plan": f"{i:04d}-p", "title": "p", "open": 1, "failed": int(i == 30), "next": "U1"} for i in range(1, 31)]
        got = self.sections([], None, plans)["Open UAT checks"]
        self.assertEqual(len(got["rows"]), vs.UAT_LIMIT + 1)
        self.assertEqual(got["rows"][0][0], "0030-p")
        self.assertEqual(got["rows"][-1][0], "... and 15 more plans")

    def test_a_chore_is_escaped_in_the_page(self):
        got = self.sections([], {"date": "d", "items": [("today", "<script>alert(1)</script>")]}, [])
        html = page.render("t", list(got.values()))
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()
