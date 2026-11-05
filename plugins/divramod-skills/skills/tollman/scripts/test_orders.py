"""Hal2 plan 0360 step 6 (D6, D29): fix orders on engine_farm.py's farm. A red train is never broken up: the tollman
orders the car's foreman to fix on `<NN>-train-<n>-<a>-fix` from the carrier's head (`origin/train-<n>-<a>`, plan 0610 D18), the foreman answers `fixed <sha>`, the
fix is merged into the carrier and the same cars land again. No real gh, origin is the farm's bare repository."""

import contextlib
import io
import json
import unittest
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import acks
import fix_proof
import orders
import run_names
import train_state
import tick
import wake
import tollman
from engine_farm import Farm, out
from test_farmer import git

RUN = "https://github.com/x/runs/9"
C = "tollman-train"  # the kept carrier worktree, the queue's slot (plan 0610 D18)
R = "train-1-1"  # the carrier's branch of run 1 of train 1, on origin where every fix starts (plan 0610 D18)
MERGED = f"Merge 07-train-1-1-fix into {R} (fix order 07-fix-1)"


class Red(Farm):
    """A red train of the cars 07 and 09, its run red on rust-test."""

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

    def order_of(self, field):
        """The field's last order's branch and the carrier's run it starts from (plan 0610 D18: run_names.py)."""
        o = [e for e in train_state.lines(str(self.main)) if e["kind"] == "order" and e.get("field") == field][-1]
        return o["branch"], run_names.base_of(o["branch"])

    def remote(self, branch=R):
        return out(self.main, "ls-remote", "origin", f"refs/heads/{branch}").split("\t")[0]

    def fix(self, field, text="fixed", start=None):
        """The foreman's part: the side branch from the carrier's remote head (or `start`), a commit, pushed."""
        path = self.fields[field]
        git(path, "fetch", "-q", "origin", R)
        git(path, "switch", "-q", "-C", f"{field}-train-1-1-fix", start or f"origin/{R}")
        (path / f"fix-{field}.txt").write_text(text)  # only the fix: plans/CURRENT_PLAN is gitignored in a real field
        git(path, "add", f"fix-{field}.txt")
        git(path, "commit", "-qm", f"fix {field}")
        git(path, "push", "-q", "-f", "origin", f"{field}-train-1-1-fix")
        return out(path, "rev-parse", "HEAD")

    def green(self, sha, job="rust-test"):
        """The gate's line for a green job on `sha` (plan 0522 D5: the proof a heavy job's answer carries)."""
        return f"gate: {job} green at {sha[:12]}"

    def broken_up_never(self):
        self.assertNotIn("cleared", [k for k, _ in self.state()])
        self.assertFalse([c for c in self.gate.calls if "--clear" in c], self.gate.calls)
        self.assertNotIn("breakup", [k for k, _, _ in self.last])


class Orders(Red):
    def test_an_order_writes_its_line_publishes_the_carrier_and_sends_one_acked_message(self):
        code, text = self.call("order", "07", "--why", "its test fails", "--run", RUN)
        self.assertEqual(code, 0, text)
        line = train_state.lines(str(self.main))[-1]
        self.assertEqual((line["kind"], line["field"], line["branch"], line["base"], line["run"], line["id"]),
                         ("order", "07", "07-train-1-1-fix", self.head, RUN, "07-fix-1"))
        self.assertEqual(self.remote(), self.head, "the foreman branches from the carrier's remote head")
        self.assertEqual((self.train()["state"], [o["field"] for o in self.train()["orders"]]), ("fixing", ["07"]))
        ((pane, msg),) = self.typed
        self.assertEqual(pane, "%7")
        self.assertTrue(msg.startswith("tollman [07-"), msg)
        for part in (f"git fetch origin {R}; git -C ", f"/07-fix checkout -B 07-train-1-1-fix origin/{R} || "
                     "git worktree add -B 07-train-1-1-fix ", f"/07-fix origin/{R}`", "never your field's own checkout",
                     "git push origin 07-train-1-1-fix",
                     "fixed <sha>", self.head[:12], "its test fails", "fix order 07-fix-1", "never landed on its own",
                     "Reply `ack 07-"):
            self.assertIn(part, msg)
        self.assertEqual(len([e for e in self.wm_log() if e["kind"] == "ask-ack"]), 1)
        self.round()
        self.assertEqual((self.last, len(self.typed)), ([], 1), "a fixing train waits; nobody is told twice")

    def test_the_carrier_s_remote_is_never_moved_back(self):
        git(self.cw, "commit", "-q", "--allow-empty", "-m", "later")
        ahead = out(self.cw, "rev-parse", "HEAD")
        git(self.cw, "push", "-q", "origin", f"HEAD:refs/heads/{R}")
        self.assertEqual(orders.publish(str(self.cw), self.head, R), "")
        self.assertEqual(self.remote(), ahead, "the remote holds the base already: left as it is")
        git(self.cw, "push", "-q", "-f", "origin", f"{self.head}^:refs/heads/{R}")  # behind: fast-forwarded
        self.assertIn("pushed", orders.publish(str(self.cw), self.head, R))
        self.assertEqual(self.remote(), self.head)

    def test_a_good_fix_is_merged_and_the_same_cars_land_again_never_broken_up(self):
        self.call("order", "07", "--why", "its test fails")
        sha = self.fix("07")
        code, text = self.call("fixed", "07", sha, "--proof", self.green(sha))
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
        self.assertIn("is not on origin/07-train-1-1-fix", text)
        self.assertEqual(self.call("fixed", "07", local, "--proof", self.green(local))[0], 0)

    def test_two_orders_restart_the_train_only_after_both_are_fixed(self):
        self.call("order", "07", "--why", "07 breaks the test")
        self.call("order", "09", "--why", "09 breaks the lint")
        self.assertEqual([o["field"] for o in self.train()["orders"]], ["07", "09"])
        sha = self.fix("07")
        self.assertEqual(self.call("fixed", "07", sha, "--proof", self.green(sha))[0], 0)
        self.assertEqual(self.train()["state"], "fixing")
        self.round()
        self.assertEqual((self.last, len(self.spawned)), ([], 1), "09's fix still open")
        sha = self.fix("09")
        self.assertEqual(self.call("fixed", "09", sha, "--proof", self.green(sha, "python-lint"))[0], 0)
        self.round()
        self.assertEqual((self.last, len(self.spawned)), ([("restart", "run", "-")], 2))
        self.assertEqual(out(self.cw, "log", "-2", "--first-parent", "--format=%s").splitlines(),
                         [f"Merge 09-train-1-1-fix into {R} (fix order 09-fix-1)",
                          MERGED])
        self.broken_up_never()

    def test_the_foreman_s_ack_is_answered_by_the_round_as_code(self):
        self.call("order", "07", "--why", "its test fails")
        ack_id = self.typed[0][1].split("]")[0].removeprefix("tollman [")
        sha = self.fix("07")
        argv = ["ack", ack_id, "done", "fixed", f"{sha}:", *self.green(sha).split(), "--repo", str(self.wm),
                "--role", "tollman"]
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
        self.assertEqual((line["field"], line["branch"]), ("main", "tollman-train-1-1-fix"))
        self.assertEqual(self.typed, [])
        items = wake.read(str(self.main), tollman.WIRING)["items"]
        self.assertEqual([i["kind"] for i in items][-1], "fix-order-main")
        self.assertIn(f"tollman-fix` on `tollman-train-1-1-fix` from {self.head[:12]}", items[-1]["text"])
        self.assertIn(f"the carrier `{R}` is never switched", items[-1]["text"])
        git(self.cw, "branch", "-q", "tollman-train-1-1-fix", self.head)
        git(self.cw, "switch", "-q", "tollman-train-1-1-fix")
        (self.cw / "barn-fix.txt").write_text("fixed")
        git(self.cw, "add", "barn-fix.txt")
        git(self.cw, "commit", "-qm", "the barn's fix")
        sha = out(self.cw, "rev-parse", "HEAD")
        git(self.cw, "switch", "-q", R)
        self.assertEqual(self.call("fixed", "main", sha, "--proof", self.green(sha))[0], 0,
                         "the tollman's own side branch, local")
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

    def test_a_retry_train_takes_a_car_s_order_and_is_fixing(self):
        """Plan 0620 D6 (L254: car 74 joined train 53 in retry and `order` refused it): a `retry` train takes it."""
        self.assertEqual(self.call("retry", "--why", "flaky")[0], 0)
        self.assertEqual(self.train()["state"], "retry")
        code, text = self.call("order", "07", "--why", "proof: names red")
        self.assertEqual((code, self.train()["state"]), (0, "fixing"), text)
        self.assertEqual([o["field"] for o in self.train()["orders"]], ["07"])
        self.assertEqual(self.call("order", "11", "--why", "x")[0], 1, "still only a car of the train")

    def test_a_smuggling_field_gets_an_order_only_with_smuggle(self):
        """Plan 0360 step 18 (D61, D62): the smuggle that conflicts with or broke the train is ordered by code."""
        self.assertEqual(self.call("order", "03", "--why", "x")[0], 1, "03 rides no car")
        code, text = self.call("order", "03", "--smuggle", "--why", "conflicts with your smuggle in a.txt")
        self.assertEqual(code, 0, text)
        rows = train_state.lines(str(self.main))
        line = [r for r in rows if r["kind"] == "order"][-1]
        self.assertEqual((line["field"], line["branch"], line["id"]), ("03", "03-train-1-1-fix", "03-fix-1"))
        self.assertEqual(self.train()["state"], "fixing")
        # plan 0522 D21: 03 has no session, so the order first starts its foreman (faked by the farm) and says so
        self.assertEqual(self.started, [["hal2-cli-git", "worktree", "run", "03", "--agent", "claude", "--detach"]])
        self.assertEqual((rows[-1]["kind"], rows[-1]["field"], rows[-1]["id"]), ("woke", "03", "03-fix-1"))


class Proof(Red):
    """Plan 0522 D5: a `fixed <sha>` counts only proven green: a light job (python-lint here) run by the tollman on the
    sha (its pretest faked: `self.proof`), a heavy one (rust-test) by a green line in the answer (the gate's or the red check's, plan 0610 D6)."""

    def setUp(self):
        super().setUp()
        self.proof, self.proved, farm = {"result": "green"}, [], tick.sh
        cfg = {"budget": 180, "parallel": 3, "jobs": ["python-lint"], "groups": {}}

        def sh(argv, cwd, timeout=900):  # `fix_proof.py start` in this process, its detached run too
            if argv[1:2] != [str(fix_proof.CLI)]:
                return farm(argv, cwd, timeout)
            with contextlib.redirect_stdout(io.StringIO()) as text:
                return fix_proof.main(argv[2:]), text.getvalue()

        def prove(top, main, jobs, sha, log):
            self.proved.append((jobs, sha))
            return {"jobs": [], "why": "", "errors": {}, **self.proof}

        def spawn(argv, out, cwd):
            with contextlib.redirect_stdout(io.StringIO()):
                fix_proof.main(argv[2:])
            return 1
        for patch in (mock.patch.object(tick, "sh", sh), mock.patch.object(fix_proof, "prove", prove),
                      mock.patch.object(fix_proof, "spawn", spawn),
                      mock.patch.object(fix_proof, "light_jobs", return_value=(cfg, cfg["jobs"])),
                      mock.patch.object(fix_proof, "known_jobs", return_value={"python-lint", "rust-test"})):
            patch.start()
            self.addCleanup(patch.stop)

    def ack(self, sha, *proof):
        ack_id = self.typed[0][1].split("]")[0].removeprefix("tollman [")
        self.assertEqual(acks.main(["ack", ack_id, "done", "fixed", sha, *" ".join(proof).split(), "--repo",
                                    str(self.wm), "--role", "tollman"]), 0)

    def test_a_heavy_job_s_answer_without_its_green_line_is_refused_with_it_taken(self):
        self.call("order", "07", "--why", "its test fails")
        self.assertEqual(train_state.lines(str(self.main))[-1]["jobs"], ["rust-test"], "named by the train's red")
        self.assertIn("For rust-test add the red check's own green", self.typed[0][1])  # plan 0610 D6
        sha = self.fix("07")
        self.ack(sha)
        self.round()
        self.assertEqual((self.last[0], self.train()["state"]), (("fixed", "run", "07"), "fixing"))
        self.assertIn("no proof for rust-test", self.typed[-1][1], "the foreman is told what is missing")
        self.ack(sha, ":", self.green(sha, "python-lint"))  # a line of another job is no proof of this one
        self.round()
        self.assertEqual(self.train()["state"], "fixing")
        self.ack(sha, ":", self.green(sha))
        self.round()
        self.assertEqual(self.train()["state"], "retry")
        self.assertEqual(self.proved, [], "a heavy job is never run here")

    def test_a_light_job_is_run_on_the_sha_by_the_round_red_refused_green_taken(self):
        self.call("order", "07", "--why", "python-lint: x.py:1:1: E501", "--job", "python-lint")
        self.assertIn("The tollman runs python-lint itself on your sha", self.typed[0][1])
        red = self.fix("07")
        self.proof = {"result": "red", "errors": {"python-lint": "x.py:1:1: E501 line too long"}}
        self.ack(red)
        self.round()  # the proof starts (here: runs to its end at once); nothing is taken yet
        self.assertEqual((self.last, self.proved), ([("fix-proof", "run", "07")], [(["python-lint"], red)]))
        self.round()
        self.assertEqual((self.last[0], self.train()["state"]), (("fixed", "run", "07"), "fixing"))
        self.assertIn("python-lint: x.py:1:1: E501 line too long", self.typed[-1][1], "the red line, told")
        good = self.fix("07", text="fixed again")
        self.proof = {"result": "green"}
        self.ack(good)
        self.round()
        self.assertEqual(self.last, [("fix-proof", "run", "07")])
        self.round()
        self.assertEqual((self.train()["state"], out(self.cw, "rev-parse", "HEAD^2")), ("retry", good))

    def test_a_running_proof_is_waited_for_and_only_one_runs_at_a_time(self):
        self.call("order", "07", "--why", "x", "--job", "python-lint")
        sha = self.fix("07")
        self.alive.add(4711)
        fix_proof.write(str(self.main), "07-fix-1", sha, {"state": "running", "attempt": 1, "pid": 4711})
        self.ack(sha)
        self.round()
        self.assertEqual((self.last, self.train()["state"]), ([], "fixing"), "it waits for the proof")
        self.assertEqual(fix_proof.start(str(self.cw), str(self.main), "09-fix-1", sha), tick.OFFLINE)

    def test_the_manual_fixed_proves_at_once_and_unproven_is_the_session_s_word(self):
        self.call("order", "07", "--why", "x", "--job", "python-lint", "--job", "rust-test")
        sha = self.fix("07")
        self.proof = {"result": "red", "errors": {"python-lint": "E501"}}
        code, text = self.call("fixed", "07", sha, "--proof", self.green(sha))
        self.assertEqual(code, 1, text)
        self.assertIn("red on", text)
        self.assertEqual(self.proved, [(["python-lint"], sha)])
        code, text = self.call("fixed", "07", sha, "--unproven", "the red is 09's car")
        self.assertEqual(code, 0, text)
        self.assertEqual(train_state.lines(str(self.main))[-1]["unproven"], "the red is 09's car")


if __name__ == "__main__":
    unittest.main()
