"""Hal2 plan 0595 step 12 (D22, replacing D17's wait): every finished wagon rides; a dependent is only ordered.
`trains.draft` reads the farm's plan dependencies from a fake `hal2-cli-plans` (`$HAL2_CLI_PLANS`, a script printing
`depends list --json`, schema 1) over test_trains' crops: a dependent hitched first rides after its dependency, one
whose dependency is not hitched rides all the same, and a missing or older CLI changes nothing but its advisory line.
Never the real queue."""
# enforces .adr/tollman.md

import json
import os
import shutil
import stat
import tempfile
from pathlib import Path
from unittest import mock

import test_trains
import train_depends
import trains_dry
import trains

READ = train_depends.read  # before any test fakes it


def link(plan, field, state, until="main"):
    return {"plan": plan, "slug": f"{plan:04d}-dep", "field": field, "steps": [], "needs": [], "until": until,
            "state": state, "reached": False}


def node(plan, field, depends_on):
    return {"plan": plan, "slug": f"{plan:04d}-plan", "field": field, "depends_on": depends_on, "dependents": []}


class Depends(test_trains.Crops):
    def setUp(self):
        super().setUp()
        real = mock.patch.object(train_depends, "read", READ)  # the real read (Crops fakes it), over the fake CLI
        real.start()
        self.addCleanup(real.stop)
        self.bin = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.bin, True)

    def fake(self, body: str) -> Path:
        """A fake hal2-cli-plans whose `depends list` runs the shell `body`; `$HAL2_CLI_PLANS` names it."""
        path = self.bin / "hal2-cli-plans"
        path.write_text(f"#!/bin/sh\necho \"$@\" >> {self.bin / 'calls'}\n{body}\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        env = mock.patch.dict(os.environ, {train_depends.ENV: str(path)})
        env.start()
        self.addCleanup(env.stop)
        return path

    def listing(self, *nodes):
        doc = {"schema": 1, "farm": "hal2", "plans": list(nodes), "problems": []}
        (self.bin / "out.json").write_text(json.dumps(doc))
        self.fake(f"cat {self.bin / 'out.json'}")

    def calls(self) -> list[str]:
        path = self.bin / "calls"
        return path.read_text().splitlines() if path.exists() else []

    def test_a_dependent_car_first_in_hitch_order_rides_after_its_dependency(self):
        self.listing(node(505, "05", [link(707, "07", "hitched")]), node(707, "07", []))
        q = self.queue(**{"05": {"five.txt": "5"}, "07": {"seven.txt": "7"}, "09": {"nine.txt": "9"}})
        d = self.draft(q)
        self.assertEqual(self.cars(d), ["07", "05", "09"], "05 moves behind 07 only; 09 keeps its place after 05")
        self.assertEqual(d["waiting"], [])
        self.assertEqual(d["depends"], ["05 rides after 07 (0707, hitched): its plan depends on it"])
        self.assertEqual(self.calls(), [f"depends list --json --repo {self.d}"], "one read per forming")

    def test_a_dependency_in_main_orders_nothing(self):
        self.listing(node(505, "05", [link(707, "07", "main")]))
        q = self.queue(**{"05": {"five.txt": "5"}, "07": {"seven.txt": "7"}})
        d = self.draft(q)
        self.assertEqual((self.cars(d), d["waiting"], d["depends"]), (["05", "07"], [], []))

    def test_a_dependent_whose_dependency_is_not_hitched_rides_all_the_same(self):
        self.listing(node(505, "05", [link(514, "38", "pushed", until="pushed")]))
        q = self.queue(**{"05": {"five.txt": "5"}, "07": {"seven.txt": "7"}})
        d = self.draft(q)
        self.assertEqual((self.cars(d), d["waiting"]), (["05", "07"], []),
                         "the user, 2026-11-04: all finished worktrees ride (D22)")

    def test_a_dependent_whose_dependency_rides_the_standing_train_joins_it(self):
        self.listing(node(505, "05", [link(707, "07", "hitched")]))
        q = self.queue(**{"05": {"five.txt": "5"}})
        self.assertEqual(self.cars(trains.draft(self.d, q, "tollman-hal2", "main", "main")), ["05"])
        self.assertEqual((self.cars(self.draft(q)), self.draft(q)["waiting"]), (["05"], []))

    def test_a_chain_rides_whole_in_dependency_order(self):
        self.listing(node(505, "05", [link(707, "07", "hitched")]), node(707, "07", [link(900, None, "open")]))
        q = self.queue(**{"05": {"five.txt": "5"}, "07": {"seven.txt": "7"}})
        d = self.draft(q)
        self.assertEqual((self.cars(d), d["waiting"]), (["07", "05"], []))

    def test_a_missing_or_older_cli_changes_nothing_but_says_so(self):
        q = self.queue(**{"05": {"five.txt": "5"}, "07": {"seven.txt": "7"}})
        with mock.patch.dict(os.environ, {train_depends.ENV: ""}), mock.patch.object(train_depends.shutil, "which",
                                                                                      return_value=None):
            d = self.draft(q)
        self.assertEqual((self.cars(d), d["waiting"], d["depends"]), (["05", "07"], [], [train_depends.MISSING]))
        self.fake("echo \"error: unrecognized subcommand 'depends'\" >&2; exit 2")
        d = self.draft(q)
        self.assertEqual((self.cars(d), d["waiting"], d["depends"]), (["05", "07"], [], [train_depends.OLD]))
        self.fake("echo not json")
        self.assertEqual(self.draft(q)["depends"], [f"{train_depends.BROKEN} (exit 0)"])

    def test_no_wagon_reads_nothing(self):
        self.listing()
        self.assertEqual((self.draft([])["depends"], self.calls()), ([], []))

    def test_the_dry_run_prints_the_reasons(self):
        d = {"standing": None, "alone": False, "cars": [], "unhitched": [], "yard": {"skipped": None, "left": []},
             "waiting": [{"field": "05", "why": "rides alone in the next train: x"}], "depends": [train_depends.OLD]}
        with mock.patch("builtins.print") as out, mock.patch.object(trains_dry.yard_report, "lines", return_value=[]):
            trains_dry.print_dry_run(d)
        text = "\n".join(str(c.args[0]) for c in out.call_args_list)
        self.assertIn("waiting: 05: rides alone in the next train: x", text)
        self.assertIn(f"depends: {train_depends.OLD}", text)


class Order(test_trains.unittest.TestCase):
    def test_a_cycle_keeps_queue_order(self):
        deps = {"plans": [node(1, "01", [link(2, "02", "open")]), node(2, "02", [link(1, "01", "open")])]}
        wagons = [{"slot": "01"}, {"slot": "02"}]
        self.assertEqual(train_depends.order(wagons, deps), wagons)

    def test_a_car_is_found_by_its_current_plan_when_its_field_is_not_named(self):
        deps = {"plans": [node(505, None, [link(707, "07", "pushed")])]}
        self.assertEqual([link["plan"] for link in train_depends.pending(deps, "05", "0505-plan\n")], [707])
        self.assertEqual(train_depends.pending(deps, "05", ""), [])


if __name__ == "__main__":
    test_trains.unittest.main()
