"""Tests of find.py with a fake daybook command, a fake notifier and a fake apply command (no real notification).
Run from the scripts folder: python3 -m unittest test_find"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import find
import paths
import watchstate

DAYBOOK = """#!/usr/bin/env python3
import json, os, sys
with open(os.path.join(os.environ["FAKE_DIR"], "daybook.log"), "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
sys.exit(int(os.environ.get("FAKE_DAYBOOK_EXIT", "0")))
"""
APPLY = """#!/usr/bin/env python3
import os, sys
with open(os.path.join(os.environ["FAKE_DIR"], "apply.log"), "a") as f:
    f.write(sys.stdin.read() + "\\n")
sys.exit(int(open(os.path.join(os.environ["FAKE_DIR"], "apply.exit")).read()))
"""
EVENT = {"id": "email-1", "summary": "Acme: Ihre Bewerbung"}
VERDICT = {"verdict": "act", "title": "Acme: Einladung", "notify": "Acme: Einladung", "data": {"kind": "invitation"}}


class FindTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.farm_dir = root / "jobsearch"
        self.farm_dir.mkdir()
        self.env = {"LOOKOUT_STATE_DIR": str(root / "state"), "LOOKOUT_DIR": str(root / "cfg"),
                    "FAKE_DIR": str(root)}
        for key, value in self.env.items():
            old = os.environ.get(key)
            os.environ[key] = value
            self.addCleanup(lambda k=key, o=old: os.environ.pop(k, None) if o is None else os.environ.update({k: o}))
        self.daybook = self.script("daybook.py", DAYBOOK)
        self.apply_script = self.script("apply.py", APPLY)
        (root / "apply.exit").write_text("0")
        self.record = {"id": "replies", "title": "Replies", "farm": str(self.farm_dir)}
        self.calls = []
        self.state = watchstate.empty()
        self.now = paths.now()

    def script(self, name, text):
        path = Path(self.tmp.name) / name
        path.write_text(text)
        return path

    def notifier(self, fail=False, raises=False):
        def fake(title, body, farm, watch, backends):
            self.calls.append((title, body, farm, watch, backends))
            if raises:
                raise RuntimeError("boom")
            return [{"backend": b, "ok": not fail, "error": "down" if fail else None} for b in backends]
        return fake

    def process(self, record=None, notifier=None, verdict=VERDICT, **kw):
        return find.process(record or self.record, "jobsearch", EVENT, verdict, self.state, now=self.now,
                            settings={"notify": ["desktop"]}, daybook=str(self.daybook),
                            notifier=notifier or self.notifier(), **kw)

    def daybook_calls(self):
        log = Path(self.tmp.name) / "daybook.log"
        return [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []

    def test_find_writes_record_daybook_item_and_one_notify(self):
        out = self.process()
        self.assertEqual(out["status"], "done")
        self.assertEqual(out["last_result"], "Acme: Einladung")
        lines = find.read_finds("jobsearch")
        self.assertEqual(len(lines), 1)
        self.assertEqual((lines[0]["watch"], lines[0]["event"], lines[0]["judged"], lines[0]["data"]),
                         ("replies", "email-1", True, {"kind": "invitation"}))
        self.assertEqual(self.daybook_calls(),
                         [["--farm", str(self.farm_dir), "jot", "Acme: Einladung [lookout:replies]"]])
        self.assertEqual(self.calls, [("Acme: Einladung", "Acme: Einladung", "jobsearch", "replies", ["desktop"])])
        self.assertIn("email-1", self.state["delivered"])

    def test_failing_notifier_keeps_the_record(self):
        for kw in ({"fail": True}, {"raises": True}):
            self.state = watchstate.empty()
            out = self.process(notifier=self.notifier(**kw))
            self.assertEqual(out["status"], "done")
        self.assertEqual(len(find.read_finds("jobsearch")), 2)
        self.assertEqual(len(self.daybook_calls()), 2)
        log = [x for x in paths.read_log() if x.get("kind") == "find" and str(x["step"]).startswith("notify")]
        self.assertFalse(any(x["ok"] for x in log))
        self.assertEqual(len(self.calls), 2)  # never retried inside a call

    def test_failing_daybook_keeps_the_record_and_says_so(self):
        os.environ["FAKE_DAYBOOK_EXIT"] = "3"
        self.addCleanup(os.environ.pop, "FAKE_DAYBOOK_EXIT")
        out = self.process()
        self.assertEqual(out["status"], "done")
        self.assertEqual(len(find.read_finds("jobsearch")), 1)
        self.assertFalse(out["steps"]["daybook"]["ok"])
        self.assertIn("no daybook item", self.calls[0][1])
        self.assertEqual(len(self.calls), 1)

    def test_missing_daybook_keeps_the_record(self):
        find.daybook_script, real = lambda explicit=None: None, find.daybook_script
        self.addCleanup(setattr, find, "daybook_script", real)
        out = self.process()
        self.assertFalse(out["steps"]["daybook"]["ok"])
        self.assertEqual(out["status"], "done")
        self.assertEqual(len(find.read_finds("jobsearch")), 1)
        self.assertEqual(len(self.calls), 1)

    def test_notify_none_calls_no_backend(self):
        self.process(record=dict(self.record, notify="none"))
        self.assertEqual(self.calls[0][4], [])

    def test_apply_gets_the_find_on_stdin(self):
        record = dict(self.record, apply=f"{{python}} {self.apply_script}")
        self.process(record=record)
        sent = json.loads((Path(self.tmp.name) / "apply.log").read_text().strip())
        self.assertEqual((sent["event"], sent["title"]), ("email-1", "Acme: Einladung"))
        self.assertEqual(len(self.calls), 1)

    def test_apply_retries_then_an_apply_failed_item(self):
        (Path(self.tmp.name) / "apply.exit").write_text("1")
        record = dict(self.record, apply=f"{{python}} {self.apply_script}")
        first = self.process(record=record)
        self.assertEqual(first["status"], "pending")
        self.assertEqual(self.state["pending"][0]["step"], "apply")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.daybook_calls(), [])
        self.process(record=record)
        self.assertEqual(len(self.state["pending"]), 1)
        final = self.process(record=record)
        self.assertEqual(final["status"], "done")
        self.assertEqual(self.state["pending"], [])
        self.assertEqual(len(find.read_finds("jobsearch")), 1)  # the retries never doubled the record
        jots = [c[3] for c in self.daybook_calls()]
        self.assertEqual(jots, ["apply failed: Acme: Einladung [lookout:replies]", "Acme: Einladung [lookout:replies]"])
        self.assertEqual(len(self.calls), 1)

    def test_apply_succeeds_on_retry(self):
        (Path(self.tmp.name) / "apply.exit").write_text("1")
        record = dict(self.record, apply=f"{{python}} {self.apply_script}")
        self.assertEqual(self.process(record=record)["status"], "pending")
        (Path(self.tmp.name) / "apply.exit").write_text("0")
        self.assertEqual(self.process(record=record)["status"], "done")
        self.assertEqual(len(self.daybook_calls()), 1)
        self.assertEqual(len(self.calls), 1)

    def test_unwritable_record_stays_pending(self):
        blocker = Path(self.tmp.name) / "state" / "state"
        blocker.parent.mkdir(parents=True, exist_ok=True)
        blocker.write_text("a file where a folder should be")
        out = self.process()
        self.assertEqual(out["status"], "pending")
        self.assertEqual(self.state["pending"][0]["step"], "record")
        self.assertEqual(self.calls, [])

    def test_title_starting_with_a_dash_is_a_plain_argument(self):
        self.process(verdict=dict(VERDICT, title="--evil flag"))
        self.assertEqual(self.daybook_calls()[0][3], "evil flag [lookout:replies]")


if __name__ == "__main__":
    unittest.main()
