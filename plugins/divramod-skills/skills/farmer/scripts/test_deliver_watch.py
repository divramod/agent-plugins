"""The Mac delivery's finding (deliver_watch.py, hal2 plan 0728 D20 (1)): a red delivery wakes and pushes once per sha,
an unloaded agent wakes once a day, an unknown schema once; nothing on another system or without the unit. A fake
status runner and a scratch main checkout; never the real unit, alarm or notice."""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import deliver_watch as dw
import duties
import tick

NOW = dt.datetime(2026, 11, 8, 12, 0)


def status(**fields) -> dict:
    return {"schema": 1, "sha": "abcdef0123456789", "run": 7, "started": "2026-11-08T11:00:00Z",
            "ended": "2026-11-08T11:20:00Z", "steps": [{"name": "take", "outcome": "success"},
                                                      {"name": "install", "outcome": "failure"}],
            "result": "green", "reason": "", "log": None, "delivered": "abcdef0123456789",
            "agent": {"loaded": True, "state": "not running", "runs": "4", "last_exit_code": "0"}, **fields}


class Watch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="deliver-watch-")
        self.addCleanup(self.tmp.cleanup)
        self.main = Path(self.tmp.name) / "hal2"
        (self.main / dw.UNIT).parent.mkdir(parents=True)
        (self.main / dw.UNIT).write_text("")
        self.asked = []

    def plan(self, doc, system="Darwin", code=0):
        def runner(argv, cwd):
            self.asked.append((argv[1:], cwd))
            return code, doc if isinstance(doc, str) else json.dumps(doc)
        return dw.plan({"main": str(self.main)}, runner, system)

    def test_a_green_loaded_delivery_is_no_finding_and_is_read_by_the_status_command(self):
        self.assertEqual(self.plan(status()), [])
        self.assertEqual(self.asked, [([str(self.main / dw.UNIT), "status", "--json"], str(self.main))])
        for result in ("none", "waiting", "running"):
            self.assertEqual(self.plan(status(result=result)), [])

    def test_a_red_delivery_wakes_and_pushes_once_per_sha(self):
        acts = self.plan(status(result="red", reason="install failed", log="/state/logs/abcdef.log"))
        self.assertEqual([(a["duty"], a["kind"], a["do"]) for a in acts],
                         [("delivery", "red", "wake"), ("delivery", "alarm", "run")])
        self.assertIn("delivery of abcdef0123 is red: install failed, log /state/logs/abcdef.log", acts[0]["text"])
        self.assertEqual(acts[0]["evidence"]["reason"], "install failed")
        argv = acts[1]["argv"]
        self.assertEqual((Path(argv[1]).name, argv[2], argv[-2:]), ("alarm.py", "deliver-red", ["--repo", str(self.main)]))
        self.assertNotIn("deliver-red", __import__("alarm").STUCK, "a push, no ring")
        # The farmer's log remembers the keys: the next round plans the same acts and tick.fresh drops them.
        log = [{"at": "2026-11-08T11:59:00Z", "key": a["key"]} for a in acts]
        self.assertEqual(tick.fresh(self.plan(status(result="red", reason="x")), log, NOW), [])
        later = self.plan(status(result="red", sha="1111111111111111", reason="x"))
        self.assertEqual(len(tick.fresh(later, log, NOW)), 2, "the next red sha reaches the user again")

    def test_an_unloaded_agent_wakes_once_a_day(self):
        acts = self.plan(status(agent={"loaded": False}))
        self.assertEqual([(a["kind"], a["do"], a["window"]) for a in acts], [("agent-down", "wake", dw.DAY)])
        self.assertIn("deliver-pull-macos/main.py install", acts[0]["text"])
        log = [{"at": "2026-11-08T00:30:00Z", "key": "deliver-agent-down"}]
        self.assertEqual(tick.fresh(acts, log, dt.datetime(2026, 11, 8, 12, 0, tzinfo=dt.timezone.utc)), [])
        self.assertEqual(len(tick.fresh(acts, log, dt.datetime(2026, 11, 9, 1, 0, tzinfo=dt.timezone.utc))), 1)

    def test_a_schema_the_reader_does_not_know_wakes_once_and_nothing_else_is_read(self):
        acts = self.plan(status(schema=2, result="red"))
        self.assertEqual([(a["kind"], a["key"]) for a in acts], [("schema", "deliver-schema:2")])
        self.assertEqual(self.plan({"result": "red"})[0]["key"], "deliver-schema:None")

    def test_nothing_to_read_is_no_finding(self):
        self.assertEqual(self.plan(status(result="red"), system="Linux"), [])
        self.assertEqual(self.plan(status(result="red"), code=1), [])
        self.assertEqual(self.plan("not json"), [])
        self.assertEqual(self.plan("[1]"), [])
        (self.main / dw.UNIT).unlink()
        self.assertEqual(self.plan(status(result="red")), [])
        self.assertEqual(dw.plan({}), [])

    def test_the_default_caller_survives_a_missing_program(self):
        self.assertEqual(dw.call(["/nonexistent-program"], self.tmp.name)[0], 127)
        code, out = dw.call(["python3", "-c", "print('{}')"], self.tmp.name)
        self.assertEqual((code, out.strip()), (0, "{}"))

    def test_the_ci_duty_adds_it_after_its_own_findings(self):
        acts = duties.plan_ci({}, {"top": "/x/farmer", "main": str(self.main)}, {"findings": []},
                              delivery=self.plan(status(agent={"loaded": False})))
        self.assertEqual([a["kind"] for a in acts], ["agent-down"])
        self.assertEqual(duties.plan_ci({}, {"top": "/x/farmer", "main": "/x/hal2"}, {"findings": []}), [],
                         "no unit in this main: nothing is read")


if __name__ == "__main__":
    unittest.main()
