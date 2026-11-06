"""Hal2 plan 0383 step 5 (D5, L32, L34, L35): a red job of a train's live land run whose triage names exactly one car
is that car's fix order by code while the run still runs, on `<NN>-train-<n>-<a>-fix` from `origin/train-<n>-<a>`; an unclear
culprit wakes the session; the fix is merged only after the run has ended. The regression replays train 20 of
2026-10-18 (L35): its early order went out by hand on the field's own branch 20 and `tollman.py fixed` refused the
fix. On engine_farm.py's farm (a bare origin, no landing), gh is gh_fake.py's."""
# enforces .adr/deterministic-first.md and .adr/tollman.md

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import farmer_frame  # noqa: F401  (the farmer skill's frame on the import path)
import acks
import early_order
import mtm_scan
import run_triage
import red_tests
import run_names
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
        self.base = run_names.base_ref(self.train(), self.c)  # its run on origin, where a fix starts (plan 0610 D18)
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

    def order_of(self, field="20"):
        """The field's last order's branch and the carrier's run it starts from (plan 0610 D18: run_names.py)."""
        o = [e for e in train_state.lines(str(self.main)) if e["kind"] == "order" and e.get("field") == field][-1]
        return o["branch"], run_names.base_of(o["branch"])

    def fix(self):
        """20's foreman, as the order says: the side branch from the carrier's remote head, one commit, pushed."""
        path, (branch, base) = self.fields["20"], self.order_of()
        git(path, "fetch", "-q", "origin", base)
        git(path, "switch", "-q", "-C", branch, f"origin/{base}")
        (path / "code/x/twenty.py").write_text("20, fixed")
        git(path, "commit", "-qam", "fix 20")
        git(path, "push", "-q", "origin", branch)
        return out(path, "rev-parse", "HEAD")

    def test_train_20_s_early_order_names_its_fix_branch_from_the_carrier_and_the_fix_waits_for_the_run_s_end(self):
        self.round()  # 18:40: the first red job while the run runs
        self.assertIn(("early-order", "run", "20"), self.last)
        order = train_state.lines(str(self.main))[-1]
        self.assertEqual((order["kind"], order["field"], order["branch"], order["base"], order["run"]),
                         ("order", "20", f"20-{self.base}-fix", self.head, self.url))
        self.assertTrue(order["why"].startswith("d1-01-rust-test: error: assertion failed"), order["why"])
        self.assertEqual(self.train()["state"], "landing", "the run goes on")
        self.assertEqual(out(self.main, "ls-remote", "origin", f"refs/heads/{self.base}").split("\t")[0], self.head)
        ((pane, msg),) = self.typed
        self.assertEqual(pane, "%20")
        for part in (f"checkout -B 20-{self.base}-fix origin/{self.base}", f"git push origin 20-{self.base}-fix",
                     "done fixed <sha>",
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
        green = f"{sha}: gate: rust-test green at {sha[:12]}".split()  # the heavy job's proof (plan 0522 D5)
        self.assertEqual(acks.main(["ack", ack, "done", "fixed", *green, "--repo", str(self.wm), "--role", "tollman"]),
                         0)
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

    def test_a_second_red_job_of_the_car_is_added_to_its_open_order_and_told(self):
        self.round()  # the first red: the early order 20-fix-1 (rust-test)
        self.assertEqual(self.call("order", "20", "--why", "d1-02-ts-test: FAIL x", "--job", "ts-test")[0], 0)
        ((_, first), (pane, msg)) = self.typed
        self.assertEqual(pane, "%20")
        for part in ("fix order 20-fix-1 for field 20 also: d1-02-ts-test: FAIL x", f"20-{self.base}-fix", "done fixed"):
            self.assertIn(part, msg)
        (o,) = self.train()["orders"]
        self.assertEqual((o["id"], o["jobs"]), ("20-fix-1", ["ts-test"]), "one order, the new job on it (D16; "
                         "this farm has no gate, so the first order named no job)")
        self.assertEqual(self.call("order", "20", "--why", "d1-02-ts-test: again", "--job", "ts-test")[0], 0)
        self.assertEqual(len(self.typed), 2, "a job the order has already: no message")

    def test_separate_failures_of_both_cars_order_each_car_and_wake_nobody(self):
        self.gh.logs["720"] = ERROR + "\nd1-01-rust-test\ttest\terror: two.txt is wrong too"  # plan 0608 D4
        self.round()
        self.assertIn(("early-order", "run", "20"), self.last)
        self.assertIn(("early-order", "run", "02"), self.last)
        self.assertNotIn(("train-red", "wake", "-"), self.last)
        self.assertEqual(sorted(p for p, _ in self.typed), ["%2", "%20"])
        self.assertEqual(sorted(o["field"] for o in self.train()["orders"]), ["02", "20"])

    def test_one_failure_that_names_both_cars_wakes_the_session_and_orders_nobody(self):
        self.gh.logs["720"] = "d1-01-rust-test\ttest\terror: two.txt and code/x/twenty.py disagree"
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
        self.assertIn("early-order:501:d1-01-rust-test:07", [e["key"] for e in self.wm_log()])  # per job, car (0608 D4)

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


class Run41851365404(unittest.TestCase):
    """Plan 0608 (L240): train 51's run 2, its c3-01 red (fixtures/job-126650244054.txt, the failed tests of its
    GitHub job log) has separate failures of cars 38, 22 and 03 and two no car's; it ordered nobody."""
    LOG = (Path(__file__).parent / "fixtures" / "job-126650244054.txt").read_text()
    CARS = [{"field": "38", "files": ["code/rust/libs/hal2-agents-node/tests/it/unit_autopilot.rs"]},
            {"field": "22", "files": ["code/rust/libs/hal2-remarkable-node/tests/it/remarkable/wifi_ssh.rs"]},
            {"field": "03", "files": ["code/rust/apps/hal2-cli-tmux/tests/it/list.rs"]},
            {"field": "47", "files": [".github/workflows/merge-to-main-cloud.yml"]}]
    TRAIN = {"train": "51", "cars": [{"field": c["field"], "plan": "p" + c["field"]} for c in CARS]}

    def verdict(self):
        return {"kind": "car", "evidence": {"cars": self.CARS, "tail": "", "tests": mtm_scan.failing_tests(self.LOG)}}

    def test_each_car_named_by_its_own_failures_is_its_order_and_the_rest_the_session_s(self):
        cars, rest = early_order.split(self.TRAIN, self.verdict(), self.LOG)
        self.assertEqual(sorted(cars), ["03", "22", "38"])
        self.assertEqual(cars["38"], ["hal2-agents-node::it "
                                      "unit_autopilot::a_folder_of_no_farm_and_a_bad_value_are_refused"])
        self.assertEqual(len(cars["22"]), 2)
        self.assertEqual([t.split("::it ")[1].split("::")[0] for t in cars["03"]], ["list"] * 3)
        self.assertTrue(rest, "hal2-roles' and hal2-cli-tmux serve:: failures name no car: the session's")

    def test_the_actions_order_each_car_once_with_its_tests_and_wake_the_session(self):
        jobs = [{**job("c3-01-rust-build-test-linux"), "databaseId": 126650244054}]
        rid, url = "41851365404", "https://github.com/divramod/hal2/actions/runs/41851365404"
        data = ({"id": rid, "url": url, "cancelled": False}, [], "", {"cars": self.CARS})
        with mock.patch.object(early_order, "read_log", return_value=[]), \
                mock.patch.object(train_state, "lines", return_value=[]), \
                mock.patch.object(early_order.triage, "gather", return_value=data), \
                mock.patch.object(early_order.job_error, "job_log", return_value=self.LOG):
            out = early_order.actions("top", "main", self.TRAIN, url, rid, jobs)
        orders = {a["slot"]: a for a in out if a["kind"] == "early-order"}
        self.assertEqual(sorted(orders), ["03", "22", "38"])
        self.assertEqual(orders["38"]["key"], f"early-order:{rid}:c3-01-rust-build-test-linux:38")
        why = orders["38"]["argv"][orders["38"]["argv"].index("--why") + 1]
        self.assertEqual(why, "c3-01-rust-build-test-linux: hal2-agents-node::it "
                              "unit_autopilot::a_folder_of_no_farm_and_a_bad_value_are_refused")
        self.assertEqual(orders["38"]["argv"][-2:], ["--unit", why.split(": ", 1)[1]], "one red, one foreman: its unit")
        self.assertEqual(orders["22"]["argv"].count("--unit"), 2)
        self.assertEqual([a["key"] for a in out if a["kind"] == "train-red"], [f"train-red:{rid}"])
        self.assertIn("c3-01-rust-build-test-linux: ordered to 38, 03, 22; yours.", out[-1]["text"])

    def test_an_order_placed_by_hand_with_the_bare_run_id_counts_as_handled(self):
        url, rid = "https://github.com/divramod/hal2/actions/runs/41851365404", "41851365404"
        rows = [{"kind": "order", "train": "51", "run": rid, "jobs": ["rust-build-test-linux"],
                 "why": "c3-01-rust-build-test-linux: by hand"}]
        log = [{"key": f"early-order:{rid}:c2-02-lint:05"}, {"key": f"early-order:{rid}:c2-03-agents-build-test-linux"}]
        with mock.patch.object(train_state, "lines", return_value=rows):
            done = early_order.handled("main", self.TRAIN, url, rid, log)
        for name in ("c3-01-rust-build-test-linux", "*rust-build-test-linux", "c2-02-lint",
                     "c2-03-agents-build-test-linux"):
            self.assertIn(name, done, "the old key form and the new per-car one, the bare id and the URL (D5)")


class Train56_5(unittest.TestCase):
    """Plan 0714 (L262): train 56-5's bash, agents and python reds name their failing test only by its name (bats
    `not ok <n> <name>`, unittest `FAIL: <test> (<dotted id>)`), no car path; each is ordered to the car that touched
    the test's file or its unit, and a test in no car's files stays the session's."""
    GATE, PY = "code/bash/scripts/gate/", "code/python/scripts/codemap/"
    RID, URL = "56500000005", "https://github.com/divramod/hal2/actions/runs/56500000005"
    LOGS = {
        "d1-01-bash-test-linux": "not ok 3 abort keeps the queue\n# (in test file gate/test-abort.bats, line 9)\n"
                                 "not ok 4 other works\n# a failure",
        "d1-02-python-test-linux": "FAIL: test_x (test_main.TestY.test_x)\nAssertionError: 1 != 2",
        "d1-03-agents-test-linux": "FAIL: test_nobody (test_elsewhere.TestZ.test_nobody)\nAssertionError: 1 != 2",
        "d1-04-bash-test-linux": "not ok 2 other works\n# (in test file other/test-other.bats, line 3)",
    }
    OTHER = "code/bash/scripts/other/test-other.bats"  # in the base, in no car's files

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.main = tmp.name
        for path, text in ((self.GATE + "test-abort.bats", '@test "abort keeps the queue" {\n  run true\n}\n'),
                           (self.GATE + "main.sh", "echo\n"), (self.PY + "main.py", "x = 1\n"),
                           (self.PY + "test_main.py", "import unittest\n"),
                           ("code/bash/scripts/other/test-other.bats", '@test "other works" {\n  run true\n}\n')):
            (Path(self.main) / path).parent.mkdir(parents=True, exist_ok=True)
            (Path(self.main) / path).write_text(text)
        for argv in (["init", "-q", "-b", "main"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@l",
                                                                  "commit", "-qm", "base"]):
            subprocess.run(["git", *argv], cwd=self.main, check=True, capture_output=True)
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.main, capture_output=True,
                              text=True).stdout.strip()
        self.cars = [{"field": "08", "files": [self.GATE + "test-abort.bats"]},
                     {"field": "13", "files": [self.PY + "main.py"]}]
        self.train = {"train": "56-5", "base": head,
                      "cars": [{"field": c["field"], "plan": "p" + c["field"], "head": head} for c in self.cars]}
        red_tests.SEEN.clear()

    def actions(self, *names, orders=()):
        self.train = {**self.train, "orders": list(orders)}
        jobs = [{**job(n), "databaseId": 100 + i} for i, n in enumerate(names)]
        data = ({"id": self.RID, "url": self.URL, "cancelled": False}, [], "", {"cars": self.cars})
        with mock.patch.object(early_order, "read_log", return_value=[]), \
                mock.patch.object(train_state, "lines", return_value=[]), \
                mock.patch.object(early_order.triage, "gather", return_value=data), \
                mock.patch.object(early_order.triage, "classify", return_value={
                    "kind": "car", "evidence": {"cars": self.cars, "tail": "", "tests": []}}), \
                mock.patch.object(early_order.job_error, "job_log",
                                  side_effect=lambda main, j: self.LOGS[j["name"]]):
            return early_order.actions(self.main, self.main, self.train, self.URL, self.RID, jobs)

    def test_the_bats_and_the_unittest_red_are_each_ordered_to_the_car_that_touched_their_test_or_unit(self):
        out = self.actions("d1-01-bash-test-linux", "d1-02-python-test-linux")
        orders = {a["slot"]: a for a in out if a["kind"] == "early-order"}
        self.assertEqual(sorted(orders), ["08", "13"])
        self.assertEqual(orders["08"]["key"], f"early-order:{self.RID}:d1-01-bash-test-linux:08")
        self.assertEqual(orders["13"]["key"], f"early-order:{self.RID}:d1-02-python-test-linux:13")
        why = orders["13"]["argv"][orders["13"]["argv"].index("--why") + 1]
        self.assertEqual(why, "d1-02-python-test-linux: FAIL: test_x (test_main.TestY.test_x)")

    def test_a_bats_red_whose_other_failure_is_in_no_cars_files_orders_the_one_car_and_wakes_the_session(self):
        out = self.actions("d1-01-bash-test-linux")
        orders = [a for a in out if a["kind"] == "early-order"]
        self.assertEqual([a["slot"] for a in orders], ["08"])
        argv = orders[0]["argv"]
        self.assertEqual(argv[argv.index("--unit") + 1], "not ok 3 abort keeps the queue",
                         "its own failure only")
        self.assertIn("d1-01-bash-test-linux: ordered to 08; yours.", out[-1]["text"], "'other works' is no car's")

    def test_a_test_in_no_cars_files_or_unit_stays_the_session_s(self):
        out = self.actions("d1-03-agents-test-linux")
        self.assertEqual([a["kind"] for a in out], ["early-red", "train-red"])
        self.assertIn("d1-03-agents-test-linux: yours", out[-1]["text"])

    def open_order(self, field, why, **more):
        return {"id": f"{field}-fix-1", "field": field, "why": why, "jobs": ["d1-05-other-job"], "early": True, **more}

    def test_a_second_job_whose_test_file_an_open_order_names_joins_that_order_though_no_car_holds_it(self):
        """Train 56-5: bash-test's red named the test file of lint's open order for car 13, and went to the session."""
        order = self.open_order("13", f"d1-05-other-job: not ok 1 first ({self.OTHER}:3)")
        out = self.actions("d1-04-bash-test-linux", orders=[order])
        orders = [a for a in out if a["kind"] == "early-order"]
        self.assertEqual([(a["slot"], a["key"]) for a in orders],
                         [("13", f"early-order:{self.RID}:d1-04-bash-test-linux:13")], "ordered to 13: an also")
        self.assertEqual([a["kind"] for a in out], ["early-red", "early-order"], "no wake for the session")
        self.assertTrue(out[0]["text"].endswith("ordered to 13"), out[0]["text"])
        self.assertNotIn("yours", out[0]["text"])

    def test_an_open_order_that_names_the_unit_or_the_test_s_name_takes_it_too(self):
        for why in ("d1-05-other-job: an error in code/bash/scripts/other/test-x.sh:9",
                    "d1-05-other-job: not ok 2 other works"):
            out = self.actions("d1-04-bash-test-linux", orders=[self.open_order("13", why)])
            self.assertEqual([a["slot"] for a in out if a["kind"] == "early-order"], ["13"], why)

    def test_two_open_orders_naming_it_none_naming_it_or_a_post_merge_order_leave_it_to_the_session(self):
        names = f"d1-05-other-job: {self.OTHER}"
        for orders in ([self.open_order("13", names), self.open_order("08", names)],
                       [self.open_order("13", "d1-05-other-job: nothing alike")],
                       [self.open_order("13", names, post="55")], []):
            out = self.actions("d1-04-bash-test-linux", orders=orders)
            self.assertEqual([a["kind"] for a in out], ["early-red", "train-red"], orders)
            self.assertIn("d1-04-bash-test-linux: yours", out[-1]["text"])

    def test_the_run_end_triage_places_the_car_whose_open_order_names_the_test_file(self):
        verdict = {"kind": "car", "evidence": {"cars": self.cars, "tail": self.LOGS["d1-04-bash-test-linux"],
                                               "tests": []}}
        order = self.open_order("13", f"d1-05-other-job: {self.OTHER}")
        self.assertIsNone(early_order.culprit(self.train, verdict, main=self.main), "no open order: unclear")
        self.assertEqual(early_order.culprit({**self.train, "orders": [order]}, verdict, main=self.main), "13")
        self.assertIsNone(early_order.culprit({**self.train, "orders": [order]}, verdict), "no checkout: no lookup")

    def test_the_run_end_triage_reads_the_checkout_the_heads_and_the_open_orders_from_its_context(self):
        """run_triage.cause (the finished run's triage) maps the test and links the open order as the early one does."""
        unit = {"job": "d1-04-bash-test-linux", "lines": self.LOGS["d1-04-bash-test-linux"].splitlines()}
        f = {"timeout": False, "tests": [], "files": []}
        order = self.open_order("13", f"d1-05-other-job: {self.OTHER}")
        cars = [*self.cars[1:], {"field": "09", "files": ["docs/a.md"]}]  # not the gate's car: it owns the pipeline
        ctx = {"cars": cars, "yard": [], "main": self.main, "base": self.train["base"],
               "heads": [{"field": c["field"], "head": c["head"]} for c in self.train["cars"]]}
        self.assertEqual(run_triage.cause(unit, None, f, ctx, None)[0], "unplaced")
        self.assertEqual(run_triage.cause(unit, None, f, {**ctx, "orders": [order]}, None), ("car", {
            "field": "13", "live": False}))
        py = {"job": "d1-02-python-test-linux", "lines": self.LOGS["d1-02-python-test-linux"].splitlines()}
        self.assertEqual(run_triage.cause(py, None, f, ctx, None)[1]["field"], "13", "mapped to its unit")


if __name__ == "__main__":
    unittest.main()
