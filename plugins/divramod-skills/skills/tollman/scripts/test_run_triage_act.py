"""Hal2 plan 0490 step 2: the dispatch of a finished land run's triage. Train 27's recorded reds (step 1's fixtures)
become the round's actions: each placed red an acked order (a `run` of `tollman.py order --post` while a train stands,
else a `send`), keyed `triage:<run id>:<bare job>`; matched to a hitched wagon, an open order or a running plan, a
`record` that names it; an unowned red, or one whose owner has no live session, a board note; `unsure` and
`unplaced` one wake per run and never an order."""
# enforces .adr/deterministic-first.md and .adr/tollman.md

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import run_triage
import run_triage_act as dispatch
import run_triage_dedup as dedup_
import test_run_triage as T

URL = "https://github.com/divramod/hal2/actions/runs/41009203691"
RID = "41009203691"
TRAIN = {"train": "train-27", "cars": ["02", "09", "21"]}
STANDING = {"train": "train-28", "state": "formed"}
PLANS = {"05": "0428-mac-vm-bash-test", "13": "0430-workqueue-runners-plugin"}
SPEC = "code/typescript/apps/hal9k-desktop/e2e/electron/ocr.spec.ts"


def result(n="27", dedup=None, **kw):
    data, jobs, log = T.recorded(n)
    run = {"id": RID, "url": URL, "sha": data["headSha"], "base": T.TRAINS[n]["base"]}
    got = run_triage.triage(run, jobs, log, T.context(n, previous=T.previous_26(), **kw))
    return {**got, "dedup": dedup if dedup is not None else got["dedup"]}


def placed(**kw):
    """Train 27 with every owner found: hub-e2e, web-e2e to the pipeline field 27, ocr to 05, workqueue to 13."""
    return result(pipeline_field="27", live={"27", "05", "13"}, plans=PLANS, **kw)


def plan(res, standing=STANDING, **kw):
    return dispatch.actions("/f/tollman-hal2", "/f/main", res, TRAIN, standing, kw.pop("panes", {"27": "%27"}),
                            read=kw.pop("read", lambda *_: []), **kw)


def of(actions, kind):
    return [a for a in actions if a["kind"] == kind]


class Orders(unittest.TestCase):
    def test_each_placed_owner_gets_one_acked_order_keyed_by_run_and_job(self):
        orders = of(plan(placed(dedup={"orders": [], "wagons": [], "plans": {}})), "triage-order")
        self.assertEqual([(a["slot"], a["key"]) for a in orders],
                         [("27", f"triage:{RID}:stack-test"), ("05", f"triage:{RID}:stack-test:05"),
                          ("13", f"triage:{RID}:stack-test:13")])
        a = orders[0]
        self.assertEqual(a["do"], "run")
        self.assertEqual(a["argv"][2:6], ["order", "27", "--post", "train-27"])
        self.assertEqual(a["argv"][a["argv"].index("--run") + 1], URL)
        why = a["argv"][a["argv"].index("--why") + 1]
        for part in ("stack-test/hub-e2e", "exit 124", "reproduce first: code/bash/scripts/gate/main.sh hub-e2e",
                     "stack-test/web-e2e"):
            self.assertIn(part, why)

    def test_a_failed_order_falls_back_to_the_text_sent_to_the_field(self):
        a = of(plan(placed()), "triage-order")[0]
        (send,) = a["on_fail"]
        self.assertEqual((send["do"], send["slot"], send["pane"], send["key"]), ("send", "27", "%27", a["key"] + ":send"))
        for part in ("train train-27 is in the barn", "reproduce first:", "the tollman did not", URL):
            self.assertIn(part, send["text"])

    def test_no_train_standing_sends_the_foreman_the_order(self):
        orders = of(plan(placed(), standing=None), "triage-order")
        self.assertEqual({a["do"] for a in orders}, {"send"})
        self.assertEqual([a["pane"] for a in orders], ["%27", None, None])
        self.assertEqual(orders[0]["key"], f"triage:{RID}:stack-test")

    def test_the_text_carries_the_evidence_and_never_a_rerun(self):
        send = of(plan(placed(), standing=None), "triage-order")[1]
        self.assertIn("e2e/electron/ocr.spec.ts", send["text"])
        self.assertIn("repeat of run 40971471569, never a car's", send["text"])
        self.assertIn("failing: e2e/electron/ocr.spec.ts:96", send["text"])

    def test_no_order_without_an_ack_key(self):
        for standing in (STANDING, None):
            for res in (placed(), result(), placed(dedup={"orders": [{"field": "05"}], "wagons": []})):
                for a in plan(res, standing):
                    self.assertTrue(a.get("key"), a)
                    if a["kind"] == "triage-order":
                        self.assertTrue(a["key"].startswith(f"triage:{RID}:"), a)
                        self.assertIn(a["do"], ("run", "send"))
                        self.assertTrue(all(f.get("key") for f in a.get("on_fail", [])))
        keys = [a["key"] for a in plan(placed())]
        self.assertEqual(len(keys), len(set(keys)), "every key is its own")

    def test_a_done_key_is_never_sent_twice(self):
        first = plan(placed())
        again = plan(placed(), done={a["key"] for a in first})
        self.assertEqual(again, [])
        self.assertEqual(len(plan(placed(), done={f"triage:{RID}:stack-test"})), len(first) - 1)


class Quiet(unittest.TestCase):
    def test_needs_red_is_a_record_and_nobody_is_ordered(self):
        got = {a["key"]: a for a in plan(placed())}
        a = got[f"triage:{RID}:hub-deploy:record"]
        self.assertEqual((a["do"], a["slot"]), ("record", "-"))
        self.assertIn("needs-red: nobody ordered", a["text"])
        self.assertEqual({o["slot"] for o in of(plan(placed()), "triage-order")}, {"27", "05", "13"})

    def test_unsure_is_a_record_and_the_one_wake_never_an_order(self):
        res = result()  # no owners found: pipeline unsure, repeats unowned, runner-image unsure
        out = plan(res)
        self.assertEqual(of(out, "triage-order"), [])
        (wake,) = of(out, "triage-wake")
        self.assertEqual((wake["do"], wake["key"]), ("wake", f"triage-wake:{RID}"))
        unsure = [v for v in res["verdicts"] if v["kind"] == "unsure"]
        self.assertTrue(unsure)
        for v in unsure:
            self.assertIn(v["missing"][:40], wake["text"])
            rec = next(a for a in out if a["key"] == v["key"] + ":record")
            self.assertIn("nothing ordered", rec["text"])
            self.assertEqual(rec["do"], "record")
        self.assertIn("reproduce first:", wake["text"])

    def test_unplaced_and_an_unknown_kind_join_the_wake(self):
        v = {"key": f"triage:{RID}:rust-test", "kind": "unplaced", "owner": None, "live": False, "cause": "unplaced",
             "evidence": {"unit": "rust-test", "job": "d1-01-rust-test", "lines": ["error: boom"], "cars": []},
             "reproduce": "code/bash/scripts/ci-check/main.sh rust-test", "reproduced": run_triage.REPRODUCED}
        w = {**v, "key": f"triage:{RID}:x", "kind": "mystery"}
        out = plan({"run": {"id": RID, "url": URL}, "verdicts": [v, w], "dedup": {}})
        self.assertEqual([a["kind"] for a in out], ["triage-record", "triage-record", "triage-wake"])
        self.assertEqual(len(of(out, "triage-wake")), 1, "one wake per run, not per job")
        self.assertIn("error: boom", out[-1]["text"])


class Notes(unittest.TestCase):
    def test_an_unowned_red_is_a_board_note(self):
        out = plan(result(pipeline_field="27", live={"27"}), standing=STANDING)  # ocr and workqueue: no owner
        notes = of(out, "triage-note")
        self.assertEqual(len(notes), 2)
        a = notes[0]
        self.assertEqual((a["do"], a["key"].endswith(":note")), ("run", True))
        argv = a["argv"]
        self.assertTrue(argv[1].endswith("board.py"))
        self.assertEqual(argv[2:10], ["post", "--kind", "note", "--from", "tollman-hal2", "--to", "-", "--train"])
        self.assertIn("no owner found", argv[argv.index("--text") + 1])
        self.assertEqual({o["slot"] for o in of(out, "triage-order")}, {"27"}, "the pipeline field is ordered")

    def test_an_owner_without_a_live_session_is_a_board_note_naming_it(self):
        out = plan(result(pipeline_field="27", live={"05"}, plans=PLANS))
        notes = {a["argv"][a["argv"].index("--to") + 1] for a in of(out, "triage-note")}
        self.assertIn("13", notes)
        text = next(a["argv"][-1] for a in of(out, "triage-note") if a["argv"][a["argv"].index("--to") + 1] == "13")
        self.assertIn("owner 13 has no live session", text)


class Dedup(unittest.TestCase):
    def test_a_hitched_wagon_touching_the_files_is_a_record_not_an_order(self):
        dedup = {"orders": [], "wagons": [{"field": "19", "head": "abc123abc123abc", "files": [SPEC]}], "plans": {}}
        out = plan(placed(dedup=dedup))
        rec = next(a for a in out if a["key"] == f"triage:{RID}:stack-test/desktop-e2e:{T.OCR}:record")
        self.assertIn("hitched wagon 19 (abc123abc123) touches", rec["text"])
        self.assertEqual({o["slot"] for o in of(out, "triage-order")}, {"27", "13"}, "05's red rides the wagon")

    def test_a_wagon_reads_its_files_after_the_run(self):
        seen = []

        def read(main, wagon, since):
            seen.append((main, wagon["field"], since))
            return [SPEC]
        res = placed(dedup={"orders": [], "wagons": [{"field": "19", "head": "h"}]})
        res["run"]["at"] = "2026-10-30T10:00:00Z"
        plan(res, read=read)
        self.assertEqual(seen[0], ("/f/main", "19", "2026-10-30T10:00:00Z"))

    def test_a_car_of_the_red_run_is_no_fix_without_a_time(self):
        res = placed(dedup={"orders": [], "wagons": [{"field": "02", "head": "h", "files": [SPEC]}]})
        self.assertEqual({o["slot"] for o in of(plan(res), "triage-order")}, {"27", "05", "13"})

    def test_a_pipeline_red_matches_a_wagon_changing_the_gate(self):
        wagon = {"field": "19", "head": "h", "files": ["code/bash/scripts/gate/jobs/hub-e2e.sh"]}
        out = plan(placed(dedup={"orders": [], "wagons": [wagon]}))
        self.assertEqual({o["slot"] for o in of(out, "triage-order")}, {"05", "13"})
        self.assertIn("hitched wagon 19", next(a for a in out if a["key"].endswith("hub-e2e:record"))["text"])

    def test_an_open_order_of_the_owner_is_no_second_order(self):
        out = plan(placed(dedup={"orders": [{"field": "27", "id": "27-fix-1"}], "wagons": []}))
        self.assertEqual({o["slot"] for o in of(out, "triage-order")}, {"05", "13"})
        self.assertIn("fix order 27-fix-1 for 27 stands open", next(a for a in out if a["key"].endswith("hub-e2e:record"))["text"])

    def test_a_running_plan_naming_the_red_is_a_record(self):
        out = plan(placed(dedup={"orders": [], "wagons": [], "plans": PLANS}))
        rec = next(a for a in out if a["key"].endswith(f"{T.WQ}:record"))
        self.assertIn("field 13 runs plan 0430-workqueue-runners-plugin, which names it", rec["text"])
        self.assertEqual({o["slot"] for o in of(out, "triage-order")}, {"27", "05"})

    def test_the_helpers(self):
        queue = [{"slot": "19", "ready": {"head": "h1", "at": "t"}}, {"slot": "20", "ready": None}, {"slot": "21"}]
        self.assertEqual(dedup_.wagons(queue), [{"field": "19", "head": "h1", "at": "t"}])
        self.assertEqual(dedup_.words({"evidence": {"unit": "stack-test/hub-e2e", "spec": "e2e/a/ocr.spec.ts"}}),
                         {"stack-test"})


class Touched(unittest.TestCase):
    def test_the_files_a_wagon_adds_beyond_the_barn(self):
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                   "GIT_COMMITTER_EMAIL": "t@t"}

            def git(*a):
                return subprocess.run(["git", "-C", d, *a], check=True, capture_output=True, text=True, env=env).stdout
            git("init", "-q", "-b", "main")
            Path(d, "a.txt").write_text("a")
            git("add", "."), git("commit", "-qm", "base")
            git("update-ref", "refs/remotes/origin/main", "HEAD")
            git("switch", "-qc", "wagon")
            Path(d, "b.txt").write_text("b")
            git("add", "."), git("commit", "-qm", "fix")
            head = git("rev-parse", "HEAD").strip()
            self.assertEqual(dedup_.touched(d, {"field": "19", "head": head}), ["b.txt"])
            self.assertEqual(dedup_.touched(d, {"field": "19", "head": head}, "2090-01-01T00:00:00Z"), [])
            self.assertEqual(dedup_.touched(d, {"field": "19", "head": "nope"}), [])


if __name__ == "__main__":
    unittest.main()
