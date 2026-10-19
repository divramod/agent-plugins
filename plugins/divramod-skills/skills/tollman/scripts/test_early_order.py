"""Hal2 plan 0383 step 5 (D5, L32, L34, L35): a red job of a train's live land run whose triage names exactly one car
is that car's fix order by code while the run still runs, on `<NN>-train-fix` from `origin/<carrier>`; an unclear
culprit wakes the session; the fix is merged only after the run has ended. The regression replays train 20 of
2026-10-18 (L35): its early order went out by hand on the field's own branch 20 and `tollman.py fixed` refused the
fix. On engine_farm.py's farm (a bare origin, no landing), gh is gh_fake.py's."""
# enforces .adr/deterministic-first.md and .adr/tollman.md

import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import acks
import early_order
import mtm_scan
import tick
import train_state
import wake
import tollman
from engine_farm import Farm, out
from gh_fake import FakeGh, job, run
from test_farmer import git
from test_minute import CARS, NAME, URL, Pass

ERROR = "d1-01-rust-test\ttest\t2026-10-18T18:40:00.1Z error: assertion failed at code/x/twenty.py:3"


class Train20(Farm):
    """Train 20+02 lands; its run's first red job names 20's file."""

    def setUp(self):
        super().setUp()
        self.crop("20", {"code/x/twenty.py": "20"}, plan="0380-twenty")
        self.crop("02", {"two.txt": "2"}, plan="0381-two")
        self.panes = {"20": "%20", "02": "%2"}
        self.round()
        self.assertEqual(self.train()["state"], "landing")
        self.alive.add(self.train()["pid"])
        self.c = self.carrier()  # the train's own worktree and branch (plan 0375 D5)
        self.head = out(self.cw, "rev-parse", "HEAD")
        self.run = run(720, "land/" + self.train()["land_ref"], "2099-01-01T00:00:00Z", status="in_progress")
        self.url = self.run["url"]
        self.gh = FakeGh([self.run], jobs={"720": [job("d1-01-rust-test"), job("d1-02-ts-test", None)]},
                         logs={"720": ERROR}).start(self)
        queue, fake = mtm_scan.run_json, self.gh.run_json  # the gate's queue and the fake gh, both
        p = mock.patch.object(mtm_scan, "run_json", lambda args, cwd=None: fake(args, cwd) if args[:1] == ["gh"]
                              else queue(args, cwd))
        p.start()
        self.addCleanup(p.stop)

    def wakes(self):
        return [i["kind"] for i in wake.read(str(self.main), tollman.WIRING).get("items", [])]

    def fix(self):
        """20's foreman, as the order says: the side branch from the carrier's remote head, one commit, pushed."""
        path = self.fields["20"]
        git(path, "fetch", "-q", "origin", self.c)
        git(path, "switch", "-q", "-C", "20-train-fix", f"origin/{self.c}")
        (path / "code/x/twenty.py").write_text("20, fixed")
        git(path, "commit", "-qam", "fix 20")
        git(path, "push", "-q", "origin", "20-train-fix")
        return out(path, "rev-parse", "HEAD")

    def test_train_20_s_early_order_names_its_fix_branch_from_the_carrier_and_the_fix_waits_for_the_run_s_end(self):
        self.round()  # 18:40: the first red job while the run runs
        self.assertIn(("early-order", "run", "20"), self.last)
        order = train_state.lines(str(self.main))[-1]
        self.assertEqual((order["kind"], order["field"], order["branch"], order["base"], order["run"]),
                         ("order", "20", "20-train-fix", self.head, self.url))
        self.assertTrue(order["why"].startswith("d1-01-rust-test: error: assertion failed"), order["why"])
        self.assertEqual(self.train()["state"], "landing", "the run goes on")
        self.assertEqual(out(self.main, "ls-remote", "origin", f"refs/heads/{self.c}").split("\t")[0], self.head)
        ((pane, msg),) = self.typed
        self.assertEqual(pane, "%20")
        for part in (f"git switch -C 20-train-fix origin/{self.c}", "git push origin 20-train-fix", "done fixed <sha>",
                     "The run still runs", "fix order 20-fix-1"):
            self.assertIn(part, msg)
        self.assertNotIn("switch -C 20 ", msg, "never the field's own branch (L35)")
        self.assertNotIn("train-red", self.wakes(), "one car named: no wake")
        self.round()
        self.assertEqual((len(self.typed), [k for k, _, _ in self.last]), (1, []), "ordered once")
        self.assertEqual(self.call("order", "20", "--why", "by hand too")[0], 0, "by hand: no second order")
        self.assertEqual(len(self.typed), 1)

        sha = self.fix()  # 18:50: pushed while the run still runs
        code, text = self.call("fixed", "20", sha)
        self.assertEqual(code, 1, text)
        self.assertIn("still runs", text)
        self.assertEqual((out(self.cw, "rev-parse", "HEAD"), len(self.typed)), (self.head, 1),
                         "not merged, the foreman not told it was refused (L34)")
        ack = msg.split("]")[0].removeprefix("tollman [")
        self.assertEqual(acks.main(["ack", ack, "done", "fixed", sha, "--repo", str(self.wm), "--role", "tollman"]), 0)
        self.round()
        self.assertNotIn(("fixed", "run", "20"), self.last, "the answer waits for the run's end")

        self.gh.runs[0] = dict(self.run, status="completed", conclusion="failure")
        self.ends({"status": "gate_failed", "run": self.url, "red": [{"name": "d1-01-rust-test"}]})
        self.gate.of(self.c).update(state="held", train=None, hold={"reason": "failed"})
        self.round()  # the run's end: red, and `fixing` at once
        self.assertEqual(self.train()["state"], "fixing")
        self.assertNotIn("train-failed", self.wakes(), "the early order answers the red")
        self.round()  # the foreman's ack: `fixed` by code, accepted
        self.assertIn(("fixed", "run", "20"), self.last)
        self.assertEqual((self.train()["state"], out(self.cw, "rev-parse", "HEAD^2")), ("retry", sha))
        self.round()
        self.assertEqual(self.last, [("restart", "run", "-")])
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["20", "02"], "the same cars, never broken up")

    def test_a_red_that_names_both_cars_wakes_the_session_and_orders_nobody(self):
        self.gh.logs["720"] = ERROR + "\nd1-01-rust-test\ttest\terror: two.txt is wrong too"
        self.round()
        self.assertNotIn(("early-order", "run", "20"), self.last)
        self.assertIn(("train-red", "wake", "-"), self.last)
        self.assertEqual((self.typed, self.train()["orders"]), ([], []))

    def test_a_red_after_the_merge_job_is_green_is_a_post_merge_order_that_never_holds_the_train(self):
        self.gh.jobs["720"].append(job("d2-01-git-merge", "success"))
        self.round()  # plan 0383 step 6 (D6): the train is in the barn as good as; the fix rides the next train
        self.assertNotIn(("early-order", "run", "20"), self.last)
        self.assertIn(("post-order", "run", "20"), self.last)
        train = self.train()
        self.assertEqual((train["state"], train["orders"], [o["post"] for o in train["post"]]),
                         ("landing", [], [train["train"]]), "no early order: it never holds this train")
        ((pane, msg),) = self.typed
        self.assertEqual(pane, "%20")
        self.assertIn("red after its merge", msg)
        self.assertIn("merges it into the next train before that train's run starts", msg)


class MinutePass(Pass):
    """The 1-minute pass places the early order on the `job failed` event, once, and prints its line."""

    def setUp(self):
        super().setUp()
        train_state.append(str(self.main), "formed", "tollman-hal2", train=NAME, cars=CARS[:1], base="b" * 40)
        self.train("started")
        self.set_run([job("d1-01-rust-test", "failure")])
        self.orders, real = [], tick.sh

        def sh(argv, cwd, timeout=900):  # the order verb itself is test_orders' and the regression's above
            if argv[1:3] == [str(early_order.CLI), "order"]:
                self.orders.append(argv[3:])
                return 0, "fix order 07-fix-1"
            return real(argv, cwd, timeout)

        p = mock.patch.object(tick, "sh", sh)
        p.start()
        self.addCleanup(p.stop)

    def test_the_pass_orders_the_one_car_on_the_job_failed_event_once(self):
        lines, orders = self.tick().splitlines(), self.orders
        self.assertEqual(self.tick(), "", "the next minute: nothing again")
        self.assertEqual(lines[0], "job failed: d1-01-rust-test: test hub::tenant_rls ... FAILED")
        self.assertTrue(lines[1].startswith(f"train {NAME}: fix order to 07 while its run runs"), lines)
        self.assertEqual([o[:6] for o in orders], [["07", "--why", "d1-01-rust-test: test hub::tenant_rls ... FAILED",
                                                    "--run", URL, "--repo"]])
        self.assertIn("early-order:501", [e["key"] for e in self.wm_log()])

    def test_smuggle_mode_orders_nobody(self):
        gh = self.gh.run_json
        asleep = {"queue": [], "mode": {"mode": "smuggle"}}
        with mock.patch.object(mtm_scan, "run_json", lambda args, cwd=None: gh(args, cwd) if args[:1] == ["gh"]
                               else asleep):
            self.assertEqual(self.tick(), "job failed: d1-01-rust-test: test hub::tenant_rls ... FAILED\n")
        self.assertEqual(self.orders, [])


class Culprit(unittest.TestCase):
    TRAIN = {"train": "t", "cars": [{"field": "20"}, {"field": "02"}]}

    def verdict(self, cars, tail="", tests=(), kind="car"):
        return {"kind": kind, "evidence": {"cars": cars, "tail": tail, "tests": list(tests)}}

    def test_the_one_car_whose_files_the_red_names(self):
        cars = [{"field": "20", "files": ["code/x/twenty.py"]}, {"field": "02", "files": ["two.txt"]}]
        self.assertEqual(early_order.culprit(self.TRAIN, self.verdict(cars, "at code/x/twenty.py:3")), "20")
        self.assertEqual(early_order.culprit(self.TRAIN, self.verdict(cars, tests=["test_twenty::works"])), "20",
                         "a file's stem in a failing test")
        self.assertIsNone(early_order.culprit(self.TRAIN, self.verdict(cars, "two.txt code/x/twenty.py")), "two")
        self.assertIsNone(early_order.culprit(self.TRAIN, self.verdict(cars, "nothing named")), "none")
        self.assertIsNone(early_order.culprit(self.TRAIN, self.verdict(cars, "code/x/twenty.py", kind="main")))

    def test_a_train_of_one_car_names_it_unless_the_yard_rides_and_could_be_it(self):
        one = {"train": "t", "cars": [{"field": "20"}]}
        cars = [{"field": "20", "files": []}]
        self.assertEqual(early_order.culprit(one, self.verdict(cars)), "20")
        yard = {**one, "yard": [{"path": "notes.md", "hash": "h"}]}
        self.assertIsNone(early_order.culprit(yard, self.verdict(cars, "notes.md")), "the yard's file: unclear")
        self.assertIsNone(early_order.culprit(yard, self.verdict(cars)), "nothing named: unclear")

    def test_two_handlers_of_one_round_plan_one_order(self):
        ctx, a = {}, {"kind": "early-order", "key": "early-order:720"}
        record = {"kind": "job-failed", "key": "job:720:x"}
        self.assertEqual(early_order.once(ctx, [a]), [a])
        self.assertEqual(early_order.once(ctx, [record, dict(a)]), [record])


if __name__ == "__main__":
    unittest.main()
