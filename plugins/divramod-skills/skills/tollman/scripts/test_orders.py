"""Hal2 plan 0360 step 6 (D6, D29): fix orders on engine_farm.py's farm. A red train is never broken up: the tollman
orders the car's foreman to fix on `<NN>-train-fix` from the carrier's head, the foreman answers `fixed <sha>`, the
fix is merged into the carrier and the same cars land again. No real gh, origin is the farm's bare repository."""

import json
import unittest

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import acks
import orders
import train_state
import wake
import tollman
from engine_farm import Farm, out
from test_farmer import git

RUN = "https://github.com/x/runs/9"
C = "tollman-train-0294-f09"  # the train's own worktree and branch, the carrier (plan 0375 D5)
MERGED = f"Merge 07-train-fix into {C} (fix order 07-fix-1)"


class Orders(Farm):
    def setUp(self):
        super().setUp()
        self.crop("07", {"seven.txt": "7"}, plan="0294-tollman-role")
        self.crop("09", {"nine.txt": "9"})
        self.panes = {"07": "%7", "09": "%9"}
        self.round()
        self.ends({"status": "gate_failed", "run": RUN, "red": [{"name": "linux / rust-test"}]})
        self.gate.of(C).update(state="held", train=None, hold={"reason": "failed"})
        self.round()
        self.assertEqual(self.train()["state"], "red")
        self.head = out(self.cw, "rev-parse", "HEAD")
        self.calls_before = len(self.gate.calls)

    def remote(self, branch=C):
        return out(self.main, "ls-remote", "origin", f"refs/heads/{branch}").split("\t")[0]

    def fix(self, field, text="fixed", start=None):
        """The foreman's part: the side branch from the carrier's remote head (or `start`), a commit, pushed."""
        path = self.fields[field]
        git(path, "fetch", "-q", "origin", C)
        git(path, "switch", "-q", "-C", f"{field}-train-fix", start or f"origin/{C}")
        (path / f"fix-{field}.txt").write_text(text)  # only the fix: plans/CURRENT_PLAN is gitignored in a real field
        git(path, "add", f"fix-{field}.txt")
        git(path, "commit", "-qm", f"fix {field}")
        git(path, "push", "-q", "-f", "origin", f"{field}-train-fix")
        return out(path, "rev-parse", "HEAD")

    def broken_up_never(self):
        self.assertNotIn("cleared", [k for k, _ in self.state()])
        self.assertFalse([c for c in self.gate.calls if "--clear" in c], self.gate.calls)
        self.assertNotIn("breakup", [k for k, _, _ in self.last])

    def test_an_order_writes_its_line_publishes_the_carrier_and_sends_one_acked_message(self):
        code, text = self.call("order", "07", "--why", "its test fails", "--run", RUN)
        self.assertEqual(code, 0, text)
        line = train_state.lines(str(self.main))[-1]
        self.assertEqual((line["kind"], line["field"], line["branch"], line["base"], line["run"], line["id"]),
                         ("order", "07", "07-train-fix", self.head, RUN, "07-fix-1"))
        self.assertEqual(self.remote(), self.head, "the foreman branches from the carrier's remote head")
        self.assertEqual((self.train()["state"], [o["field"] for o in self.train()["orders"]]), ("fixing", ["07"]))
        ((pane, msg),) = self.typed
        self.assertEqual(pane, "%7")
        self.assertTrue(msg.startswith("tollman [07-"), msg)
        for part in (f"git fetch origin {C}; git switch -C 07-train-fix origin/{C}", "git push origin 07-train-fix",
                     "fixed <sha>", self.head[:12], "its test fails", "fix order 07-fix-1", "never landed on its own",
                     "Reply `ack 07-"):
            self.assertIn(part, msg)
        self.assertEqual(len([e for e in self.wm_log() if e["kind"] == "ask-ack"]), 1)
        self.round()
        self.assertEqual((self.last, len(self.typed)), ([], 1), "a fixing train waits; nobody is told twice")

    def test_the_carrier_s_remote_is_never_moved_back(self):
        git(self.cw, "commit", "-q", "--allow-empty", "-m", "later")
        ahead = out(self.cw, "rev-parse", "HEAD")
        git(self.cw, "push", "-q", "origin", f"HEAD:refs/heads/{C}")
        self.assertEqual(orders.publish(str(self.cw), self.head), "")
        self.assertEqual(self.remote(), ahead, "the remote holds the base already: left as it is")
        git(self.cw, "push", "-q", "-f", "origin", f"{self.head}^:refs/heads/{C}")  # behind: fast-forwarded
        self.assertIn("pushed", orders.publish(str(self.cw), self.head))
        self.assertEqual(self.remote(), self.head)

    def test_a_good_fix_is_merged_and_the_same_cars_land_again_never_broken_up(self):
        self.call("order", "07", "--why", "its test fails")
        sha = self.fix("07")
        code, text = self.call("fixed", "07", sha)
        self.assertEqual(code, 0, text)
        self.assertEqual(out(self.cw, "log", "-1", "--format=%s"), MERGED)
        self.assertEqual(out(self.cw, "rev-parse", "HEAD^2"), sha)
        self.assertEqual((self.train()["state"], self.state()[-1]), ("retry", ("fixed", C)))
        self.round()
        self.assertEqual((self.last, len(self.spawned), self.train()["state"], self.train()["starts"]),
                         ([("restart", "run", "-")], 2, "landing", 2))
        self.assertEqual(out(self.cw, "log", "-1", "--format=%s"), MERGED,
                         "the merge is the new candidate: no empty retry commit")
        self.assertEqual(self.gate.calls[-1], ["worktree", "queue", "train", C, "07", "09", "--train", "1", "--attempt", "2"], "the same cars, the next attempt")
        self.assertEqual([c["field"] for c in self.train()["cars"]], ["07", "09"])
        self.broken_up_never()

    def test_a_fix_not_from_the_order_s_base_or_not_pushed_is_refused_and_the_order_stays_open(self):
        self.call("order", "07", "--why", "its test fails")
        stale = self.fix("07", start="origin/main")  # not from the train's head
        code, text = self.call("fixed", "07", stale)
        self.assertEqual(code, 1, text)
        self.assertIn("does not descend from the order's base", text)
        self.assertEqual((self.train()["state"], out(self.cw, "rev-parse", "HEAD")), ("fixing", self.head))
        self.assertIn("refused", self.typed[-1][1])
        self.assertEqual(self.typed[-1][0], "%7", "the foreman is told why")
        local = self.fix("07")
        git(self.fields["07"], "commit", "-q", "--allow-empty", "-m", "unpushed")
        code, text = self.call("fixed", "07", out(self.fields["07"], "rev-parse", "HEAD"))
        self.assertEqual(code, 1, text)
        self.assertIn("is not on origin/07-train-fix", text)
        self.assertEqual(self.call("fixed", "07", local)[0], 0)

    def test_two_orders_restart_the_train_only_after_both_are_fixed(self):
        self.call("order", "07", "--why", "07 breaks the test")
        self.call("order", "09", "--why", "09 breaks the lint")
        self.assertEqual([o["field"] for o in self.train()["orders"]], ["07", "09"])
        self.assertEqual(self.call("fixed", "07", self.fix("07"))[0], 0)
        self.assertEqual(self.train()["state"], "fixing")
        self.round()
        self.assertEqual((self.last, len(self.spawned)), ([], 1), "09's fix still open")
        self.assertEqual(self.call("fixed", "09", self.fix("09"))[0], 0)
        self.round()
        self.assertEqual((self.last, len(self.spawned)), ([("restart", "run", "-")], 2))
        self.assertEqual(out(self.cw, "log", "-2", "--first-parent", "--format=%s").splitlines(),
                         [f"Merge 09-train-fix into {C} (fix order 09-fix-1)",
                          MERGED])
        self.broken_up_never()

    def test_the_foreman_s_ack_is_answered_by_the_round_as_code(self):
        self.call("order", "07", "--why", "its test fails")
        ack_id = self.typed[0][1].split("]")[0].removeprefix("tollman [")
        sha = self.fix("07")
        argv = ["ack", ack_id, "done", "fixed", sha, "--repo", str(self.wm), "--role", "tollman"]
        self.assertEqual(acks.main(argv), 0)
        self.round()
        self.assertEqual(self.last, [("fixed", "run", "07")])
        self.assertEqual(self.train()["state"], "retry")
        self.round()
        self.assertEqual(self.last, [("restart", "run", "-")])
        self.broken_up_never()

    def test_order_main_wakes_the_own_session_and_sends_nothing(self):
        code, text = self.call("order", "main", "--why", "the barn is red: linux / rust-test")
        self.assertEqual(code, 0, text)
        line = train_state.lines(str(self.main))[-1]
        self.assertEqual((line["field"], line["branch"]), ("main", "tollman-train-fix"))
        self.assertEqual(self.typed, [])
        items = wake.read(str(self.main), tollman.WIRING)["items"]
        self.assertEqual([i["kind"] for i in items][-1], "fix-order-main")
        self.assertIn("tollman-train-fix", items[-1]["text"])
        git(self.cw, "branch", "-q", "tollman-train-fix", self.head)
        git(self.cw, "switch", "-q", "tollman-train-fix")
        (self.cw / "barn-fix.txt").write_text("fixed")
        git(self.cw, "add", "barn-fix.txt")
        git(self.cw, "commit", "-qm", "the barn's fix")
        sha = out(self.cw, "rev-parse", "HEAD")
        git(self.cw, "switch", "-q", C)
        self.assertEqual(self.call("fixed", "main", sha)[0], 0, "the tollman's own side branch, local")
        self.assertEqual(self.train()["state"], "retry")

    def test_an_order_needs_a_red_train_and_a_car(self):
        self.assertEqual(self.call("order", "11", "--why", "x")[0], 1, "11 rides no train")
        self.assertEqual(self.call("fixed", "07", self.head)[0], 1, "no order open")
        self.assertEqual(self.call("order", "07", "--why", "x")[0], 0)
        self.assertEqual(self.call("retry", "--why", "flaky")[0], 1, "an open order: the fix, not a retry")
        code, text = self.call("unhitch", "07", "--why", "x", repo=self.main)
        self.assertEqual(code, 1)
        self.assertIn("frozen (plan 0360 D3)", text)
        self.assertEqual(json.loads(json.dumps(self.train()["orders"]))[0]["id"], "07-fix-1")

    def test_a_smuggling_field_gets_an_order_only_with_smuggle(self):
        """Plan 0360 step 18 (D61, D62): the smuggle that conflicts with or broke the train is ordered by code."""
        self.assertEqual(self.call("order", "03", "--why", "x")[0], 1, "03 rides no car")
        code, text = self.call("order", "03", "--smuggle", "--why", "conflicts with your smuggle in a.txt")
        self.assertEqual(code, 0, text)
        line = train_state.lines(str(self.main))[-1]
        self.assertEqual((line["field"], line["branch"], line["id"]), ("03", "03-train-fix", "03-fix-1"))
        self.assertEqual(self.train()["state"], "fixing")


if __name__ == "__main__":
    unittest.main()
