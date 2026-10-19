"""interrupt.py done/continue and stats (resume.py): the reverse undo with hal2-daemon last, the continue messages,
earlier holds left as they are, the record closed, --dry-run; the stats table and its median. Fakes only: the
machine (FakeSys), the sessions (FakeMessenger), quiet.py (FakeQuiet), the clock; temp roots for every record."""
import json
import os
import tempfile
import unittest

import interrupt
import resume
import stopall
from test_interrupt import Base


class ResumeTest(Base):
    def stopped(self, *args):
        self.assertEqual(self.run_stop(*args), 0)
        self.sys.kills.clear()
        self.sys.calls.clear()
        self.msg.sent.clear()
        self.lines.clear()

    def run_done(self, *args, cmd="done"):
        return interrupt.main([cmd, *args], self.deps())

    def test_done_undoes_in_reverse_and_tells_the_sessions(self):
        self.stopped()
        stops = [a for a in json.loads(stopall.record().read_text())["actions"] if a["undo"]]
        del self.msg.rows[3]  # 10-gh ended meanwhile
        self.assertEqual(self.run_done(), 0)
        conts = [k for k in self.sys.kills if k[1] == "CONT"]
        self.assertEqual(conts[-1], (600, "CONT"))  # hal2-daemon last
        want = [(a["undo"][1], "CONT") for a in reversed(stops) if a["undo"][1] != 600]
        self.assertEqual(conts[:-1], want)
        self.assertFalse(any(c[:2] == ["tart", "stop"] for c in self.sys.calls))
        self.assertEqual(sorted(s[0] for s in self.msg.sent), ["07-ab", "08-cd", "09-ef"])
        self.assertTrue(all("continue skill" in s[1] and s[2] == "bypass" and not s[3] for s in self.msg.sent))
        self.assertTrue(all("/continue" not in s[1] for s in self.msg.sent))
        self.assertFalse(stopall.record().exists())
        history = json.loads(next((stopall.root() / "history").glob("*.json")).read_text())
        self.assertEqual(history["kind"], "important-interrupt")
        out = "\n".join(self.lines)
        self.assertIn("10-gh", out)
        self.assertIn("gone", out)
        self.assertIn("approval in its terminal: 08-cd, 09-ef", out)
        row = json.loads((interrupt.root() / "log.jsonl").read_text().splitlines()[-1])
        self.assertEqual((row["kind"], row["told"], row["delivered"], row["gone"], row["silent"]),
                         ("done", 4, 3, 1, 2))
        self.assertEqual(row["counts"]["daemon"], 1)

    def test_continue_is_done(self):
        self.stopped()
        self.assertEqual(self.run_done(cmd="continue"), 0)
        self.assertFalse(stopall.record().exists())

    def test_dry_run_changes_nothing(self):
        self.stopped()
        record = stopall.record().read_text()
        log = (interrupt.root() / "log.jsonl").read_text()
        self.assertEqual(self.run_done("--dry-run"), 0)
        self.assertEqual(self.sys.kills, [])
        self.assertTrue(all(s[3] for s in self.msg.sent))
        self.assertEqual(stopall.record().read_text(), record)
        self.assertEqual((interrupt.root() / "log.jsonl").read_text(), log)
        self.assertFalse((stopall.root() / "history").exists())
        self.assertTrue(any(line.startswith("would undo freeze hal2-daemon 600") for line in self.lines))

    def test_no_interrupt_or_a_plain_stop_exits_1(self):
        self.assertEqual(self.run_done(), 1)
        stopall.save(["08-cd"], [], "benchmarks")
        self.assertEqual(self.run_done(), 1)
        self.assertTrue(stopall.record().exists())
        self.assertEqual(self.sys.kills, [])

    def test_an_earlier_stop_stays_held(self):
        stopall.save(["08-cd"], [], "benchmarks")
        stopall.add_actions([{"text": "freeze 42 (/w/08)", "do": ["STOP", 42], "undo": ["CONT", 42]}])
        self.stopped()
        self.assertEqual(self.run_done(), 0)
        self.assertNotIn((42, "CONT"), self.sys.kills)
        self.assertNotIn("08-cd", [s[0] for s in self.msg.sent])
        back = json.loads(stopall.record().read_text())
        self.assertEqual(back["stopped"], ["08-cd"])
        self.assertEqual([a["text"] for a in back["actions"]], ["freeze 42 (/w/08)"])
        self.assertNotIn("important_interrupt", back)
        self.assertNotIn("kind", back)
        self.assertIn("left as it is: 08-cd (earlier hold, in an active stop)", self.lines)

    def test_a_second_stop_keeps_the_first_interrupts_sessions(self):
        self.stopped()
        self.msg.rows.append({"pid": 15, "name": "11-ij", "checkout": "/w/11", "socket": "/s/15.sock", "pane": None})
        self.stopped()
        ii = json.loads(stopall.record().read_text())["important_interrupt"]
        self.assertEqual(ii["told"], ["07-ab", "08-cd", "09-ef", "10-gh", "11-ij"])
        self.assertEqual((ii["first_action"], ii["held"], ii["earlier"]), (0, [], None))
        self.assertEqual(self.run_done(), 0)
        self.assertEqual(len(self.msg.sent), 5)
        self.assertFalse(stopall.record().exists())


class StatsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["IMPORTANT_INTERRUPT_ROOT"] = self.tmp.name
        self.lines = []

    def tearDown(self):
        del os.environ["IMPORTANT_INTERRUPT_ROOT"]
        self.tmp.cleanup()

    def stats(self, *args):
        return interrupt.main(["stats", *args], interrupt.Deps(out=self.lines.append))

    def test_rows_and_the_median(self):
        rows = [{"kind": "stop", "start": "2026-10-19T11:29:34+02:00", "quiet_at": "x", "seconds": s,
                 "counts": {"build": 3, "runner": 2}, "told": 5, "paused": 4, "silent": 1} for s in (30.0, 132.0, 60.0)]
        rows.append({"kind": "stop", "start": "2026-10-19T12:00:00+02:00", "quiet_at": None, "seconds": 300.0})
        rows.append({"kind": "done", "start": "2026-10-19T13:00:00+02:00", "seconds": 4.0, "counts": {"build": 3}})
        (interrupt.root() / "log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows) + "broken\n")
        self.assertEqual(self.stats(), 0)
        self.assertEqual(len(self.lines), 7)
        self.assertIn("2026-10-19T11:29:34 | stop | 30.0", self.lines[1])
        self.assertIn("|      3 |       2 |    5 | 4      | 1", self.lines[1])
        self.assertIn("(not quiet)", self.lines[4])
        self.assertEqual(self.lines[-1], "seconds to quiet over 3 stops: median 60.0, max 132.0")
        self.lines.clear()
        self.stats("--json", "--last", "2")
        data = json.loads(self.lines[0])
        self.assertEqual((len(data["rows"]), data["median"]), (2, None))

    def test_empty_log(self):
        self.assertEqual(self.stats(), 0)
        self.assertIn("no runs logged yet", self.lines[-1])
        self.assertEqual(resume.summary([])["median"], None)


if __name__ == "__main__":
    unittest.main()
