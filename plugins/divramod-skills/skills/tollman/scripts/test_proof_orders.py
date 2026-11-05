"""Every hitched wagon rides (the user, 2026-11-04, angry: "i told you at least 20 times, to take all finished ones
into the train"): a red light gate check is no unhitch any more, the car rides with `proof_red` and is fixed in the
train by its fix order (proof_orders.py). The draft over real git (test_trains.Crops), the whole flow on
engine_farm.py's farm."""
# enforces .adr/tollman.md

import re
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import engine_car
import proof_orders
import test_trains as tt
import run_names
import train_state
import trains
from engine_farm import Farm, out
from test_farmer import git

GREEN = {"state": "green", "lines": [], "checks": [], "skipped": [], "dropped": 0}
FINDING = "names: plans/0301-x/notes.md:1: slot — use worktree"
# The exceptions the draft keeps (ROLE.md "Exceptions where a hitched wagon does not ride" names the user's): each
# why starts so; anything else keeping a hitched wagon out fails the test.
NAMED = ("a servant's field (plans/LEAD) never rides", "its head is in the barn already", "its worktree is gone",
         "its entry's mode is smuggle", "rides alone in the next train", "rides in the next train, after",
         "rides in the next train: the smuggler")


def red_for(*fields, lines=(FINDING,)):
    """A proof that is red for the fields whose worktree name ends in one of `fields`, green for the rest."""
    def verdict(main, worktree, head, barn):
        hit = any(str(worktree).rstrip("/").endswith("/" + f) for f in fields)
        return {**GREEN, "state": "red", "lines": list(lines)} if hit else GREEN
    return verdict


class Draft(tt.Crops):
    def test_a_hitched_wagon_with_a_red_proof_is_a_car_with_proof_red(self):
        q = self.queue(**{"07": {"seven.rs": "7\n"}, "09": {"nine.rs": "9\n"}})
        with mock.patch.object(trains, "PROVE", lambda m, w, h, b: {**GREEN, "state": "red", "lines": [FINDING]}
                               if h == q[0]["ready"]["head"] else GREEN):
            d = self.draft(q)
        self.assertEqual((self.cars(d), d["unhitched"], d["waiting"]), (["07", "09"], [], []))
        self.assertEqual((d["cars"][0]["proof_red"], "proof_red" in d["cars"][1]), ([FINDING], False))

    def test_every_hitched_wagon_is_a_car_unless_a_named_exception_applies(self):
        q = self.queue(**{"03": {"three.rs": "3\n"}, "07": {"seven.rs": "7\n"}, "09": {"a.rs": "nine\n"},
                          "11": {"a.rs": "eleven\n"}, "13": {"thirteen.rs": "13\n"}, "15": {"fifteen.rs": "15\n"}})
        q[0]["worktree"] = self.servant_field()
        q[5]["mode"] = "smuggle"  # last: a smuggler cuts only the wagons behind it
        landed = tt.ticket("04", 6, self.g("rev-parse", "main"), self.d)
        reds = {q[1]["ready"]["head"], q[4]["ready"]["head"]}
        with mock.patch.object(trains, "PROVE", lambda m, w, h, b: {**GREEN, "state": "red", "lines": [FINDING]}
                               if h in reds else GREEN):
            d = self.draft([*q, landed])
        self.assertEqual(self.cars(d), ["07", "09", "11", "13"], "red proof and conflict ride")
        self.assertEqual([c["field"] for c in d["cars"] if c.get("proof_red")], ["07", "13"])
        self.assertEqual(d["cars"][2]["conflict"], ["a.rs"])
        left = [(x["field"], x["why"]) for x in d["unhitched"] + d["waiting"]]
        self.assertEqual(sorted(f for f, _ in left), ["03", "04", "15"])
        for field, why in left:
            self.assertTrue(why.startswith(NAMED), f"{field} is kept out without a named exception: {why}")


class Actions(unittest.TestCase):
    TRAIN = {"train": "07+09+11@x", "state": "red", "status": proof_orders.STATUS,
             "cars": [{"field": "07", "head": "7" * 40, "proof_red": [FINDING]}, {"field": "09", "head": "9" * 40},
                      {"field": "11", "head": "b" * 40, "proof_red": [FINDING]}]}

    def test_identical_findings_get_one_order_to_the_first_car_and_a_note_to_the_farmer(self):
        with mock.patch.object(proof_orders.mtm_scan.roles, "slot_name", return_value="farmer-hal2"):
            acts = proof_orders.actions("/f/tollman-hal2", "/f/hal2", self.TRAIN, [])
        self.assertEqual([(a["kind"], a["do"], a["slot"]) for a in acts],
                         [("proof-order", "run", "07"), (proof_orders.NOTE, "record", "farmer-hal2")])
        argv = acts[0]["argv"]
        self.assertEqual(argv[2:4] + argv[-4:], ["order", "07", "--job", "python-lint", "--repo", "/f/tollman-hal2"])
        self.assertIn(FINDING, argv[argv.index("--why") + 1])
        self.assertIn("car 11's light checks are red with the same findings as car 07's", acts[1]["text"])
        ordered = [{"kind": "order", "train": self.TRAIN["train"], "field": "07"}]
        with mock.patch.object(proof_orders.mtm_scan.roles, "slot_name", return_value="farmer-hal2"):
            again = proof_orders.actions("/f/tollman-hal2", "/f/hal2", self.TRAIN, ordered)
        self.assertEqual([a["kind"] for a in again], [proof_orders.NOTE], "an order placed is never placed twice")

    def test_distinct_findings_get_an_order_each(self):
        train = {**self.TRAIN, "cars": [self.TRAIN["cars"][0], {**self.TRAIN["cars"][2], "proof_red": [
            "records: .adr/x.md: no title"]}]}
        acts = proof_orders.actions("/f/tollman-hal2", "/f/hal2", train, [])
        self.assertEqual([(a["kind"], a["slot"]) for a in acts], [("proof-order", "07"), ("proof-order", "11")])
        self.assertEqual(acts[1]["argv"][-4:-2], ["--job", "records-check"])

    def test_the_round_of_a_proof_red_train_places_the_orders(self):
        rows = [{"schema": 1, "at": tt.AT, "kind": "formed", "slot": "tollman-hal2", "train": self.TRAIN["train"],
                 "cars": self.TRAIN["cars"], "base": "b" * 40},
                {"schema": 1, "at": tt.AT, "kind": "red", "slot": "tollman-hal2", "train": self.TRAIN["train"],
                 "status": proof_orders.STATUS, "why": "light gate checks red"}]
        with mock.patch.object(proof_orders.mtm_scan.roles, "slot_name", return_value="farmer-hal2"):
            acts = trains.plan("/no/such/farm/tollman-hal2", "/no/such/farm", [], rows, {}, alive=lambda p: False,
                               result=lambda m: None)
        self.assertEqual([a["kind"] for a in acts], ["proof-order", proof_orders.NOTE])
        red = dict(rows[1], status="gate_failed")  # plan 0610 E5: a car that joined with red light checks
        with mock.patch.object(proof_orders.mtm_scan.roles, "slot_name", return_value="farmer-hal2"):
            acts = trains.plan("/no/such/farm/tollman-hal2", "/no/such/farm", [], [rows[0], red], {},
                               alive=lambda p: False, result=lambda m: None)
        self.assertEqual([a["kind"] for a in acts], ["proof-order", proof_orders.NOTE], "any red: its order too")
        clean = dict(rows[0], cars=[{k: v for k, v in c.items() if k != "proof_red"} for c in self.TRAIN["cars"]])
        self.assertEqual(trains.plan("/no/such/farm/tollman-hal2", "/no/such/farm", [], [clean, red], {},
                                     alive=lambda p: False, result=lambda m: None), [], "any other red waits as before")

    def test_a_retry_round_places_an_unordered_proof_red_car_s_order_before_its_restart(self):
        """Plan 0620 D6 (L254, car 74 of train 53): a car with red light checks and no order in a `retry` train gets
        its order this round and no restart; once ordered (and fixed), the round restarts."""
        name, at = self.TRAIN["train"], {"schema": 1, "at": tt.AT, "slot": "tollman-hal2"}
        cars = [dict(self.TRAIN["cars"][1]), dict(self.TRAIN["cars"][0])]  # 09 rode clean, 07 joined with proof_red
        rows = [{**at, "kind": "formed", "train": name, "cars": cars, "base": "b" * 40},
                {**at, "kind": "red", "train": name, "status": "gate_failed", "why": "rust-test"},
                {**at, "kind": "retry", "train": name, "why": "flaky"}]

        def plan(rows):
            return trains.plan("/no/such/farm/tollman-hal2", "/no/such/farm", [], rows, {}, alive=lambda p: False,
                               result=lambda m: None)
        self.assertEqual(train_state.standing(rows)["state"], "retry")
        acts = plan(rows)
        self.assertEqual([(a["kind"], a.get("slot")) for a in acts], [("proof-order", "07")], "its order, no restart")
        fixed = rows + [{**at, "kind": "order", "train": name, "field": "07", "id": "07-fix-1"},
                        {**at, "kind": "fixed", "train": name, "field": "07", "id": "07-fix-1"}]
        self.assertEqual(train_state.standing(fixed)["state"], "retry")
        self.assertEqual([a["kind"] for a in plan(fixed)], ["restart"], "ordered and fixed: the restart")
        clean = [dict(rows[0], cars=[cars[0]]), *rows[1:]]
        self.assertEqual([a["kind"] for a in plan(clean)], ["restart"], "no proof_red car: the restart as before")


class NeverLeaves(Farm):
    """The user, 2026-11-04: "when a car has hitched, it will never leave the queue again". No path of the train
    code unhitches a hitched wagon, clears its ready mark or tells a foreman to unhitch or hitch again; only the
    user's own `--by-user` command takes a ready mark."""

    FILES = ("trains.py", "trains_sort.py", "frozen.py", "leavers.py", "engine.py", "engine_car.py", "engine_yard.py",
             "orders.py", "orders_cli.py", "orders_open.py", "orders_text.py")
    REHITCH = re.compile(r"ready again|hitch(es|ed)? (it )?again|re-?hitch|queue ready`", re.I)

    def test_the_round_never_unhitches_and_the_session_s_unhitch_is_refused(self):
        self.crop("07", {"seven.txt": "7"})
        self.crop("31", {"servant.txt": "s"})
        (self.fields["31"] / "plans").mkdir(exist_ok=True)
        (self.fields["31"] / "plans/LEAD").write_text("07 0383-train-rules 16\n")
        self.round()
        self.assertNotIn("unhitch", [k for k, _, _ in self.last])
        self.assertTrue(self.gate.of("31")["ready"], "the servant's wagon stays hitched")
        code, text = engine_car.unhitch(str(self.main), "31", "the session's word")
        self.assertEqual(code, 1, text)
        self.assertIn("never leave the queue again", text)
        self.assertTrue(self.gate.of("31")["ready"])
        self.assertEqual(engine_car.unhitch(str(self.main), "31", "the user's word", user=True,
                                            words="the user said so")[0], 0)
        self.assertIsNone(self.gate.of("31"), "only the user's own command takes it")

    def test_no_train_code_clears_a_ready_mark_or_says_hitch_again(self):
        here = Path(__file__).parent
        for name in self.FILES:
            text = (here / name).read_text()
            clears = [ln for ln in text.splitlines() if '"ready"' in ln and '"--clear"' in ln]
            self.assertEqual(clears, [] if name != "engine_car.py" else clears, name)
            for m in self.REHITCH.finditer(text):
                line = text[text.rfind("\n", 0, m.start()) + 1:text.find("\n", m.end())]
                self.assertTrue("hal2-cli-git worktree queue ready` (D9)" in line, f"{name}: {line.strip()}")
        car = (here / "engine_car.py").read_text()
        self.assertLess(car.index("if not user:"), car.index('"--clear"'), "engine_car clears only after the user check")


class Flow(Farm):
    """07's light checks are red: it rides, the train goes red before its landing, 07 is ordered, its fix is merged
    and only then the landing starts, with both cars."""

    def order_of(self, field):
        """The field's last order's branch and the carrier's run it starts from (plan 0610 D18: run_names.py)."""
        o = [e for e in train_state.lines(str(self.main)) if e["kind"] == "order" and e.get("field") == field][-1]
        return o["branch"], run_names.base_of(o["branch"])

    def test_a_red_proof_rides_and_the_landing_waits_for_its_fix(self):
        self.crop("07", {"seven.txt": "7"})
        self.crop("09", {"nine.txt": "9"})
        self.panes = {"07": "%7", "09": "%9"}
        with mock.patch.object(trains, "PROVE", red_for("07")):
            self.round()
        train = self.train()
        self.assertEqual(([c["field"] for c in train["cars"]], train["state"], train["status"]),
                         (["07", "09"], "red", proof_orders.STATUS))
        self.assertEqual(self.spawned, [], "no landing starts while a light check is red: nothing is pushed")
        self.round()
        self.assertEqual(([o["field"] for o in self.train()["orders"]], self.train()["state"]), (["07"], "fixing"))
        ((pane, msg),) = self.typed
        self.assertEqual(pane, "%7")
        self.assertIn(FINDING, msg)
        path, carrier, (branch, base) = self.fields["07"], self.carrier(), self.order_of("07")
        git(path, "fetch", "-q", "origin", base)
        git(path, "switch", "-q", "-C", branch, f"origin/{base}")
        (path / "fix-07.txt").write_text("fixed")
        git(path, "add", "fix-07.txt")
        git(path, "commit", "-qm", "fix 07")
        git(path, "push", "-q", "-f", "origin", branch)
        sha = out(path, "rev-parse", "HEAD")
        code, text = self.call("fixed", "07", sha, "--proof", f"gate: python-lint green at {sha[:12]}")
        self.assertEqual((code, self.train()["state"]), (0, "retry"), text)
        self.round()
        self.assertEqual((self.spawned, self.train()["state"]), ([carrier], "landing"))
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["07", "09"], "never dropped")
        self.assertNotIn("unhitched", [k for k, _ in self.state()])
        self.assertIn("red", [e["kind"] for e in train_state.lines(str(self.main))])


if __name__ == "__main__":
    unittest.main()
