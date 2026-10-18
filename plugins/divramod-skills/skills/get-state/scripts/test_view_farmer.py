"""The farmer's page (hal2 plan 0366 D6): pure grouping over hand-made rows, the plan description fact, and the
page of a farmer checkout over test_state's git fixture."""

import contextlib
import io
import re
import unittest
from pathlib import Path

import grid
import state
import state_sources as src
import view_farmer as vf
from test_state import Fixture, git

CTX = {"role": "farmer", "repo": "proj", "checkout": "farmer-proj", "top": "/x", "main": "/x"}


def row(wt, done=None, total=None, plan="0001-x", **kw) -> dict:
    pct = None if not total else (200 * done + total) // (2 * total)
    base = {"wt": wt, "is_main": False, "plan": plan, "plan_number": plan[:4] if plan[:1].isdigit() else None,
            "plan_name": plan[5:] or None if plan[:1].isdigit() else None, "steps_done": done, "steps_total": total,
            "done_pct": pct, "git": None, "agent": "idle", "queue": None, "waits": [], "own": False, "description": None}
    return {**base, **kw}


def data(*rows, mode=None, queue=None) -> dict:
    return {"default": "main", "rows": list(rows), "mode": mode, "queue": queue}


def tables(*rows, **kw) -> dict:
    _, sections = vf.view(data(*rows, **kw), CTX)
    return {s["id"]: s for s in sections}


def col(section: dict, key: str) -> list:
    return [r[key] for r in section["rows"]]


def shown(section: dict) -> list[str]:
    """The field numbers the table shows by default: default filter, then default sort (grid.py's static view)."""
    return [r["wt"] for r in grid.view(section)[1]]


class Tables(unittest.TestCase):
    def test_five_grids_in_order_with_ids(self):
        title, sections = vf.view(data(row("01", 1, 5)), CTX)
        self.assertEqual(title, "proj · farmer")
        self.assertEqual([(s["kind"], s["id"]) for s in sections], [("grid", i) for i in ("queue", "fields", "free", "questions", "decisions")])

    def test_table_by_id_and_unknown_id(self):
        d = data(row("01", 1, 5))
        self.assertEqual(vf.table(d, "fields"), tables(row("01", 1, 5))["fields"])
        self.assertIsNone(vf.table(d, "nope"))

    def test_shared_columns_in_the_three_tables(self):
        t = tables(row("01", 1, 5))
        keys = ["wt", "plan", "steps", "done_pct", "brings", "state", "behind", "ahead", "stash", "untracked", "added",
                "modified", "deleted"]
        self.assertEqual([c["key"] for c in t["fields"]["columns"]], keys)
        self.assertEqual(t["free"]["columns"], t["fields"]["columns"])
        self.assertEqual([c["key"] for c in t["queue"]["columns"]], ["place"] + keys)
        labels = [c["label"] for c in t["fields"]["columns"]]
        self.assertEqual(labels, ["Field", "Plan", "Steps", "Done %", "What it brings in", "State",
                                  "↓", "↑", "s", "?", "+", "~", "-"])
        self.assertEqual([c["key"] for c in t["fields"]["columns"] if c.get("hidden")], ["done_pct"])
        self.assertEqual({c["key"] for c in t["fields"]["columns"] if c["type"] == "num"} - {"done_pct"},
                         {"behind", "ahead", "stash", "untracked", "added", "modified", "deleted"})

    def test_main_and_role_worktrees_are_no_field(self):
        t = tables(row("main", 5, 5, is_main=True), row("farmer-proj", 5, 5), row("tollman-proj", 5, 5), row("10", 5, 5))
        self.assertEqual(col(t["fields"], "wt"), ["10"])
        self.assertEqual(t["free"]["rows"], [])

    def test_empty_states(self):
        t = tables(row("main", is_main=True))
        self.assertEqual(t["fields"]["empty"], "No field has a plan.")
        self.assertEqual(t["free"]["empty"], "No free field.")
        self.assertEqual(t["queue"]["empty"], "The merge queue is not known.")
        self.assertEqual(tables(row("01", 1, 5), queue=[])["queue"]["empty"], "The merge queue is empty.")
        self.assertEqual(tables(row("01", 1, 5))["queue"]["empty"], "The merge queue is not known.")


class FieldsTable(unittest.TestCase):
    def rows(self):
        return [row("01", 5, 5), row("02", 4, 5), row("03", 4, 6), row("04", 3, 6), row("05", plan=""),
                row("06", 2, 6), row("07", 0, 1), row("08", plan="my-shots/3/fix")]

    def test_free_fields_are_only_in_the_free_table(self):
        t = tables(*self.rows())
        self.assertEqual(col(t["free"], "wt"), ["05"])
        self.assertNotIn("05", col(t["fields"], "wt"))

    def test_filters_and_their_groups(self):
        t = tables(*self.rows())["fields"]
        self.assertEqual([(f["key"], f["label"]) for f in t["filters"]],
                         [("done", "Done"), ("one", "One step left"), ("nearly", "Nearly done"), ("rest", "The rest"),
                          ("all", "All")])
        self.assertIsNone(t["filters"][-1]["match"])
        got = {f["key"]: [r["wt"] for r in t["rows"] if grid.matches(r, f)] for f in t["filters"]}
        self.assertEqual(got, {"done": ["01"], "one": ["02", "07"], "nearly": ["03"], "rest": ["04", "06", "08"],
                               "all": ["01", "02", "03", "04", "06", "07", "08"]})

    def test_a_shot_or_unknown_steps_is_the_rest_not_free(self):
        t = tables(row("01", plan="my-shots/3/fix"), row("02", 1, None))["fields"]
        self.assertEqual({r["group"] for r in t["rows"]}, {"rest"})

    def test_default_filter_all_and_sort_by_done_percent_descending(self):
        t = tables(*self.rows())["fields"]
        self.assertEqual(t["filter"], "all")
        self.assertEqual(grid.default_filter(t), "all")
        self.assertEqual(t["sort"], {"key": "done_pct", "dir": "desc"})
        # 07 0/1 = 0 %, 06 2/6 = 33, 04 3/6 = 50, 03 4/6 = 67, 02 4/5 = 80, 01 100; 08 has none: last
        self.assertEqual(shown(t), ["01", "02", "03", "04", "06", "07", "08"])
        self.assertEqual(col(t, "done_pct"), [100, 80, 67, 50, 33, 0, None])

    def test_free_table_is_sorted_by_field_ascending(self):
        t = tables(row("30", plan=""), row("02", plan=""), row("10", plan=""))["free"]
        self.assertEqual(t["sort"], {"key": "wt", "dir": "asc"})
        self.assertEqual(shown(t), ["02", "10", "30"])

    def test_cells_plan_steps_description_and_numbers(self):
        git = {"behind": 3, "ahead": 2, "stash": 1, "untracked": 0, "added": 0, "modified": 4, "deleted": 5}
        t = tables(row("07", 4, 5, plan="0123-big-thing", description="Adds the big thing.", git=git))["fields"]
        r = t["rows"][0]
        self.assertEqual((r["wt"], r["plan"], r["steps"], r["done_pct"], r["brings"]),
                         ("07", "0123 big thing", "4 of 5", 80, "Adds the big thing."))
        self.assertEqual([r[k] for k in ("behind", "ahead", "stash", "untracked", "added", "modified", "deleted")],
                         [3, 2, 1, 0, 0, 4, 5])

    def test_unknown_numbers_and_description_are_empty(self):
        r = tables(row("07", 4, 5))["fields"]["rows"][0]
        self.assertEqual(r["brings"], "")
        self.assertTrue(all(r[k] is None for k in ("behind", "ahead", "stash", "untracked", "added", "modified", "deleted")))
        free = tables(row("10", plan=""))["free"]["rows"][0]
        self.assertEqual((free["plan"], free["steps"], free["done_pct"]), ("", "", None))

    def test_the_full_description_is_kept(self):
        text = "word " * 80
        self.assertEqual(tables(row("07", 1, 2, description=text))["fields"]["rows"][0]["brings"], text)

    def test_state_phrases(self):
        def state(r, **kw):
            return tables(r, **kw)["fields"]["rows"][0]["state"]
        queue = {"holds": True, "position": 1}
        self.assertIn("holds the merge queue", state(row("01", 5, 5, queue=queue)))
        waiting = {"holds": False, "position": 3}
        self.assertEqual(state(row("01", 5, 5, queue=waiting, agent="none")), "no session; queue 3")
        self.assertNotIn("smuggling", state(row("01", 5, 5, queue=waiting)))
        self.assertIn("smuggling", state(row("01", 5, 5, queue=waiting), mode={"mode": "smuggle"}))
        self.assertNotIn("smuggling", state(row("01", 5, 5), mode={"mode": "smuggle"}))
        qs = [{"kind": "questions", "open": ["Q5", "Q6", "Q7", "Q9"]}]
        self.assertEqual(state(row("01", 1, 9, waits=qs)), "idle; waits on Q5-Q7, Q9")

    def test_a_sparse_row_does_not_raise(self):
        r = tables({"wt": "10", "cells": ["10"]})["free"]["rows"][0]
        self.assertEqual((r["wt"], r["plan"], r["state"]), ("10", "", ""))

    def test_the_own_field_is_marked(self):
        t = tables(row("01", 5, 5), row("02", 5, 5, own=True), row("03", 5, 5))["fields"]
        self.assertEqual({r["wt"]: r["_marked"] for r in t["rows"]}, {"01": False, "02": True, "03": False})


class QueueTable(unittest.TestCase):
    def tickets(self, *wts):
        return [{"slot": w, "wt": w, "worktree": None, "position": i, "holding": i == 0, "state": "x"}
                for i, w in enumerate(wts)]

    def test_rows_follow_the_queue_order_not_the_field_numbers(self):
        t = tables(row("01", 1, 5), row("05", 4, 5), row("09", 5, 5, plan=""), row("12", 2, 5),
                   queue=self.tickets("09", "12", "01"))["queue"]
        self.assertEqual(col(t, "wt"), ["09", "12", "01"])
        self.assertEqual(col(t, "place"), [1, 2, 3])
        self.assertNotIn("sort", t)
        self.assertEqual(shown(t), ["09", "12", "01"])

    def test_a_row_has_the_shared_cells_and_a_foreign_ticket_still_shows(self):
        git = {"behind": 1, "ahead": 2, "stash": 0, "untracked": 0, "added": 0, "modified": 3, "deleted": 0}
        t = tables(row("12", 2, 5, git=git, own=True), queue=self.tickets("12", "farmer-x"))["queue"]
        self.assertEqual((t["rows"][0]["steps"], t["rows"][0]["modified"], t["rows"][0]["_marked"]), ("2 of 5", 3, True))
        self.assertEqual(col(t, "wt"), ["12", "farmer-x"])
        self.assertIn("holds the merge queue", t["rows"][0]["state"])

    def test_the_mode_line_above_the_table(self):
        note = lambda mode: tables(row("01", 1, 5), mode=mode)["queue"]["note"]  # noqa: E731
        self.assertEqual(note({"mode": "production", "by": None, "at": None, "since": None}), "Merge queue mode: production")
        self.assertEqual(note({"mode": "smuggle", "by": "mod", "at": "2026-10-18T10:00", "since": "2026-10-18T10:00"}),
                         "Merge queue mode: smuggle since 2026-10-18T10:00 by mod")
        self.assertEqual(note({"mode": "smuggle", "by": None, "at": "t", "since": "t"}), "Merge queue mode: smuggle since t")
        self.assertEqual(note({"mode": "smuggle"}), "Merge queue mode: smuggle")
        self.assertEqual(note(None), "Merge queue mode: unknown")


class Description(unittest.TestCase):
    def read(self, text: str):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "plan.md"
            f.write_text(text, encoding="utf-8")
            return src.description(f)

    def test_quoted_plain_and_block_values(self):
        self.assertEqual(self.read('---\nid: 1\ndescription: "Say \\"hi\\" | now"\nstatus: open\n---\n# x\n'), 'Say "hi" | now')
        self.assertEqual(self.read("---\ndescription: plain words here\n---\n"), "plain words here")
        self.assertEqual(self.read("---\ndescription: 'it''s'\n---\n"), "it's")
        self.assertEqual(self.read("---\ndescription: >\n  folded\n  over lines\nstatus: open\n---\n"), "folded over lines")

    def test_missing_or_no_front_matter_is_none(self):
        self.assertIsNone(self.read("---\nid: 1\n---\n"))
        self.assertIsNone(self.read("# Plan\n\ndescription: not front matter\n"))
        self.assertIsNone(self.read('---\ndescription: ""\n---\n'))
        self.assertIsNone(src.description(Path("/nonexistent/plan.md")))


class FarmerPage(Fixture):
    def page(self) -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(state.main(["--repo", str(self.wt / "farmer-x"), "--no-open"]), 0)
        return Path(buf.getvalue().strip()).read_text(encoding="utf-8")

    def test_the_description_reaches_the_json_row(self):
        text = (self.plan_dir / "plan.md").read_text()
        (self.plan_dir / "plan.md").write_text('---\ndescription: "Answers it <all>."\n---\n' + text)
        row = self.rows()["02"]
        self.assertEqual(row["description"], "Answers it <all>.")
        self.assertIsNone(self.rows()["10"]["description"])

    def plan_in(self, wt: str, number: str, done: int, total: int, description: str | None = None) -> None:
        slug = f"{number}-plan-{wt}"
        d = self.wt / wt / "plans" / slug
        d.mkdir(parents=True, exist_ok=True)
        front = f'---\ndescription: "{description}"\n---\n' if description else ""
        rows = "".join(f"| {i} | s | x | {'done' if i <= done else ''} |\n" for i in range(1, total + 1))
        (d / "plan.md").write_text(front + "# Plan\n\n| # | Step | Done when | Status |\n|---|---|---|---|\n" + rows)
        (self.wt / wt / "plans").mkdir(exist_ok=True)
        (self.wt / wt / "plans/CURRENT_PLAN").write_text(slug + "\n")

    def test_a_farmer_checkout_gets_the_grids(self):
        git(self.main, "worktree", "add", "-q", "-b", "03", str(self.wt / "03"))
        git(self.main, "worktree", "add", "-q", "-b", "04", str(self.wt / "04"))
        self.plan_in("10", "0100", 5, 5, "Is all done <now>.")
        self.plan_in("03", "0101", 4, 5, "Needs one more step.")
        self.plan_in("04", "0102", 4, 6, "Nearly there.")  # 02 stays the rest (1 of 3); 1 is free
        page = self.page()
        self.assertEqual(re.findall(r"<h2>(.*?)</h2>", page), ["Merge queue", "Fields with a plan", "Free fields", "Questions", "Decisions"])
        self.assertEqual(re.findall(r'<section class="grid" data-grid="(.*?)"', page), ["queue", "fields", "free", "questions", "decisions"])
        self.assertIn("<title>proj · farmer</title>", page)
        self.assertIn('<p class="grid-note">Merge queue mode: ', page)
        self.assertIn("<th", page)
        self.assertIn("What it brings in", page)
        self.assertIn("<td>Is all done &lt;now&gt;.</td>", page)
        self.assertIn("<td>0101 plan 03</td>", page)
        self.assertIn("<td>4 of 5</td>", page)
        self.assertNotIn("<td>farmer-x</td>", page)


if __name__ == "__main__":
    unittest.main()
