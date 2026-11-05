"""The wagon table (hal2 plan 0604 step 7, D11; L225): wagons.py on temporary repositories with an origin, the verb
`tollman.py wagons` and the duty `wagons` (wagons_duty.py). Never the tollman's real state: python3 -m unittest
test_wagon_table (in scripts/); the status and the store are test_wagons.py."""
# enforces .adr/tollman.md

import contextlib
import datetime as dt
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import wagon_store as ws
import wagons
import wagons_duty

SKILL = Path(__file__).resolve().parents[1]
T0, T1, T2 = "2026-11-04T10:00:00Z", "2026-11-04T10:30:00Z", "2026-11-04T11:00:00Z"


def git(cwd, *args):
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                       env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
                            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
                            "GIT_COMMITTER_EMAIL": "t@x"})
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


class Table(unittest.TestCase):
    """The table on a temporary repository with an origin, worktrees as fields and a state folder of its own."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.root, ignore_errors=True))
        self.origin, self.main, self.state = self.root / "origin.git", self.root / "repo", self.root / "state"
        self.state.mkdir()
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.main)], check=True, capture_output=True)
        git(self.main, "checkout", "-q", "-b", "main")
        self.commit(self.main, "base.txt", "base")
        git(self.main, "push", "-q", "origin", "main")
        self.base = git(self.main, "rev-parse", "HEAD")

    def commit(self, where, name, text):
        (Path(where) / name).write_text(text)
        git(where, "add", name)
        git(where, "commit", "-q", "-m", f"add {name}")
        return git(where, "rev-parse", "HEAD")

    def field(self, name, plan=None, steps=("done", "next")):
        path = self.root / "wt" / name
        git(self.main, "worktree", "add", "-q", "-b", name, str(path), self.base)
        if plan:
            (path / "plans" / plan).mkdir(parents=True)
            (path / "plans" / "CURRENT_PLAN").write_text(plan + "\n")
            rows = "\n".join(f"| {i + 1} | s | d | m | e | w | s | {s} |" for i, s in enumerate(steps))
            (path / "plans" / plan / "plan.md").write_text(f"# Plan {plan[:4]}: a title\n\n{rows}\n")
        return path

    def train(self, cars, number=7, run=1, formed="2026-11-04T10:00:00Z", extra=()):
        carrier = f"train-{number}-{run}"
        git(self.main, "push", "-q", "origin", f"{self.base}:refs/heads/{carrier}")
        git(self.main, "fetch", "-q", "origin")
        lines = [{"schema": 1, "at": formed, "kind": "formed", "slot": "tollman-train", "train": "+".join(cars) + "@" + formed,
                  "number": number, "branch": carrier},
                 {"schema": 1, "at": formed, "kind": "started", "slot": "tollman-train",
                  "train": "+".join(cars) + "@" + formed, "land_ref": carrier}, *extra]
        (self.state / "train.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
        return carrier

    def table(self, queue=None):
        return wagons.collect(self.main, self.state, do_fetch=False, ask_queue=lambda r: queue or {})

    def test_no_train_is_an_empty_table(self):
        self.assertEqual(self.table(), {"carrier": None, "rows": [], "counts": dict.fromkeys(wagons.KINDS, 0)})
        self.assertEqual(wagons.render(self.table(), {}, "10:00", None), "no train yet: no wagons")

    def test_the_carrier_is_named_train_number_run_from_the_last_land_ref(self):
        self.train(["14"], number=7, run=1)
        self.assertEqual(self.table()["carrier"], "train-7-1")
        self.train(["14"], number=7, run=3)
        self.assertEqual(self.table()["carrier"], "train-7-3")

    def test_a_car_with_its_head_in_the_carrier_is_boarded_and_carries_its_plan(self):
        self.field("14", plan="0604-train-carrier-names")
        self.train(["14"])
        t = self.table({"14": self.base})
        self.assertEqual([(r["wt"], r["plan"], r["name"], r["steps"], r["status"]) for r in t["rows"]],
                         [("14", "0604", "a title", "1/2", "boarded")])
        self.assertEqual(t["counts"]["boarded"], 1)

    def test_a_hitched_head_not_in_the_carrier_is_hitched_and_a_ready_one_is_a_rider_waiting_for_the_merge(self):
        w = self.field("20")
        head = self.commit(w, "new.txt", "n")
        self.train(["14"])
        t = self.table({"20": head})
        self.assertEqual([(r["wt"], r["status"]) for r in t["rows"]], [("14", "boarded"), ("20", "hitched")])
        ws.add("need", "20", self.state / "wagons.jsonl", sha=head, why="by hand", at=T2)
        t = self.table({"20": head})
        self.assertEqual([(r["wt"], r["status"], r["detail"]) for r in t["rows"]][1], ("20", "ready", head[:10]))

    def test_an_open_order_is_entering_and_facts_of_an_older_train_do_not_count(self):
        self.train(["14"], formed="2026-11-04T10:00:00Z")
        store = self.state / "wagons.jsonl"
        ws.add("order", "14", store, id="14-1", at="2026-11-03T09:00:00Z")
        self.assertEqual(self.table({"14": self.base})["rows"][0]["status"], "boarded")
        ws.add("order", "14", store, id="14-2", at=T1)
        t = self.table({"14": self.base})
        self.assertEqual((t["rows"][0]["status"], t["rows"][0]["detail"]), ("entering", "14-2"))

    def test_render_and_json(self):
        self.field("14", plan="0604-train-carrier-names")
        self.train(["14"])
        text = wagons.render(self.table({"14": self.base}), {"at": "09:40", "boarded": 0}, "10:00", [])
        self.assertIn("carrier train-7-1 at ", text)
        self.assertIn("| 14 | 0604 | a title | 1/2 | boarded |", text)
        self.assertIn("| **sum: 1 wagons** | **1 plans** | | **1/2** | **0 entering, 0 ready, 1 boarded", text)
        self.assertIn("prev run: 09:40; current run: 10:00 (boarded +1 since the prev run)", text)
        self.assertIn("names: all standard", text)
        self.assertIn("names: 2 off-standard", wagons.render(self.table(), {}, "1", ["a", "b"]))
        self.assertIn("not checked", wagons.render(self.table(), {}, "1", None))

    def test_run_keeps_the_counts_for_the_next_delta_and_json_has_a_schema(self):
        self.train(["14"])
        with mock.patch.object(wagons, "queue", return_value={}):
            text = wagons.run(self.main, do_fetch=False, state=self.state)
            self.assertIn("boarded +0", text)
            doc = json.loads(wagons.run(self.main, do_fetch=False, as_json=True, state=self.state))
        self.assertEqual((doc["schema"], doc["carrier"], doc["prev"]["boarded"]), (1, "train-7-1", 0 + doc["prev"]["boarded"]))
        self.assertTrue((self.state / wagons.LAST).exists())

    def test_the_train_record_reads_a_torn_file_and_a_train_before_plan_0604(self):
        (self.state / "train.jsonl").write_text(
            json.dumps({"kind": "formed", "slot": "tollman-train-big", "train": "09@T", "branch": "tollman-train-big"})
            + '\n{"kind": "sta')
        t = wagons.train_record(self.state)
        self.assertEqual((t["name"], t["carrier"], t["cars"]), ("", "tollman-train-big", ["09"]))

    def test_the_carrier_branch_is_the_formed_lines_not_a_later_resolve_branch(self):
        self.train(["14"], extra=[{"schema": 1, "at": T1, "kind": "resolving", "slot": "tollman-train", "field": "14",
                                   "train": "14@2026-11-04T10:00:00Z", "branch": "14-train-resolve"}])
        self.assertEqual(wagons.train_record(self.state)["carrier"], "train-7-1")

    def test_plan_of_reads_schema_1_and_2_and_no_plan(self):
        w = self.field("30", plan="0111-x", steps=("done", "done", "next"))
        self.assertEqual(wagons.plan_of(w), ("0111", "a title", "2/3"))
        self.assertEqual(wagons.plan_of(self.root / "none"), ("-", "-", "-"))
        s2 = self.root / "s2"
        (s2 / "plans" / "0222-y" / "subplans" / "01" / "steps").mkdir(parents=True)
        (s2 / "plans" / "CURRENT_PLAN").write_text("0222-y\n")
        (s2 / "plans" / "0222-y" / "subplans" / "01" / "steps" / "step-01.md").write_text("status: done\n")
        self.assertEqual(wagons.plan_of(s2), ("0222", "y", "1/1"))

    def test_a_failed_queue_ask_is_an_empty_queue(self):
        with mock.patch.object(wagons.bounded, "run", side_effect=OSError("no cli")):
            self.assertEqual(wagons.queue(self.main), {})


class Verb(unittest.TestCase):
    def test_tollman_py_has_the_verb_and_the_duty(self):
        import tollman
        from handlers import HANDLERS
        self.assertIn("wagons", tollman.WIRING.duties)
        self.assertIn("duty:wagons", HANDLERS)
        args = tollman.parser().parse_args(["wagons", "--no-fetch", "--json", "--repo", "/x"])
        self.assertEqual((args.cmd, args.no_fetch, args.json, args.repo), ("wagons", True, True, "/x"))

    def test_the_verb_prints_the_run(self):
        import tollman
        args = tollman.parser().parse_args(["wagons", "--repo", "/x"])
        out = io.StringIO()
        with mock.patch.object(wagons, "run", return_value="TABLE") as run, contextlib.redirect_stdout(out):
            self.assertEqual(tollman.command(args, []), 0)
        run.assert_called_once_with("/x", do_fetch=True, as_json=False)
        self.assertEqual(out.getvalue(), "TABLE\n")

    def test_role_duties_lists_wagons_with_its_text(self):
        with tempfile.TemporaryDirectory() as d:
            p = subprocess.run([sys.executable, str(SKILL.parent / "farmer/scripts/role_duties.py"), "tollman", "--repo", d,
                                "--json"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        got = {x["id"]: x for x in json.loads(p.stdout)["duties"]}
        self.assertIn("wagons", got)
        self.assertIn("*/20", got["wagons"]["text"])


class Duty(unittest.TestCase):
    ctx = {"top": "/t", "main": "/m", "now": dt.datetime(2026, 11, 4, 10, 20), "dry": False}

    def test_the_handler_records_the_table_and_makes_no_wake(self):
        with mock.patch.object(wagons, "run", return_value="| wt |\ntable") as run:
            acts = wagons_duty.handler({}, self.ctx)
        run.assert_called_once_with("/t")
        self.assertEqual([(a["duty"], a["do"], a["text"], a["key"]) for a in acts],
                         [("wagons", "record", "| wt |\ntable", "wagons:2026-11-04T10:20")])

    def test_a_dry_run_makes_no_table(self):
        with mock.patch.object(wagons, "run", side_effect=AssertionError("touched")):
            acts = wagons_duty.handler({}, {**self.ctx, "dry": True})
        self.assertIn("dry run", acts[0]["text"])

    def test_a_failing_table_is_a_line_not_a_failed_round(self):
        with mock.patch.object(wagons, "run", side_effect=RuntimeError("boom")):
            acts = wagons_duty.handler({}, self.ctx)
        self.assertEqual((acts[0]["do"], acts[0]["text"]), ("record", "wagon table failed: RuntimeError: boom"))


if __name__ == "__main__":
    unittest.main()
