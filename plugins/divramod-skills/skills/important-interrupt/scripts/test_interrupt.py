"""interrupt.py stop: record, messages, daemon and VMs, quiet.py, builds, the re-scan to quiet, replies, the stats
row and --dry-run; the machine (FakeSys), the sessions (FakeMessenger), quiet.py (FakeQuiet) and the clock are fakes,
the stop record is stopall.py's own in a temp root."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import interrupt
import quiet
import stopall
from test_freeze import FakeSys, machine


class FakeMessenger:
    def __init__(self, pause_root, paused=()):
        self.pause_root, self.paused, self.sent = Path(pause_root), set(paused), []
        self.rows = [{"pid": 11, "name": "07-ab", "checkout": "/w/07", "socket": "/s/11.sock", "pane": "%1"},
                     {"pid": 12, "name": "08-cd", "checkout": "/w/08", "socket": None, "pane": "%2"},
                     {"pid": 13, "name": "09-ef", "checkout": "/w/09", "socket": "/s/13.sock", "pane": None},
                     {"pid": 14, "name": "10-gh", "checkout": "/w/10", "socket": "/s/14.sock", "pane": None}]

    def self_pid(self):
        return 500

    def caller_mode(self, pid):
        return "bypass" if pid == 500 else "prompting"

    def sessions(self, exclude):
        return [r for r in self.rows if r["pid"] != exclude]

    def pause_record(self, row):
        return self.pause_root / (row["checkout"].replace("/", "-") + ".md")

    def send(self, row, text, from_mode=None, dry_run=False):
        self.sent.append((row["name"], text, from_mode, dry_run))
        via = "socket" if row["socket"] else "hal2-cli-agents"
        return {"name": row["name"], "pid": row["pid"], "via": via, "status": "dry-run" if dry_run else "delivered",
                "reason": ""}

    def paused_since(self, row, t):
        return (row["name"] in self.paused), "pause record"


class FakeQuiet:
    """quiet.py's scan/apply: a CONFIRM runner row and a session row; later passes repeat a failing docker pause."""

    def __init__(self):
        self.applied = []
        self.rows = [{"kind": "session", "pid": 77, "what": "x"},
                     {"kind": "runner", "label": "actions.runner.hal2", "confirm": "self-hosted CI runner"},
                     {"kind": "session", "pid": 78, "what": "rsync /Volumes/x", "confirm": "copies or moves data"}]

    key = staticmethod(quiet.key)

    def scan(self, keep, runner):
        return self.rows

    def apply(self, keep, runner, dry, yes):
        self.applied.append((keep, runner, dry, list(yes)))
        w = "would " if dry else ""
        if len(self.applied) == 1:
            print(f"{w}freeze 77 (/w/07): kill -STOP 77")
            print(f"{w}unload LaunchAgent actions.runner.hal2: launchctl bootout gui/501/actions.runner.hal2")
            print("left alone (app): 9 50.0% Chrome")
            if not dry:
                stopall.add_actions([{"text": "freeze 77 (/w/07)", "do": ["STOP", 77], "undo": ["CONT", 77]}])
        else:
            print("pause container db: docker pause 1  (failed)")
        return 0


class Clock:
    def __init__(self, sys_, tables=()):
        self.t, self.sys, self.tables = float(int(time.time())), sys_, list(tables)

    def __call__(self):
        return self.t

    def sleep(self, n):
        self.t += n
        if self.tables:
            self.sys.procs.update(self.tables.pop(0))


class Base(unittest.TestCase):
    """The fakes of a stop, shared with test_resume; no tests of its own."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.env = {"STOP_ALL_AGENT_WORK_ROOT": str(base / "stop"), "IMPORTANT_INTERRUPT_ROOT": str(base / "ii")}
        os.environ.update(self.env)
        (base / "pause").mkdir()
        self.msg = FakeMessenger(base / "pause", paused={"07-ab"})
        self.sys = FakeSys(machine(), idle=(30.0, 85.0),
                           vms=[{"Name": "hal2-ci-runner-macos", "Running": True}])
        self.quiet, self.lines = FakeQuiet(), []

    def tearDown(self):
        for k in self.env:
            del os.environ[k]
        self.tmp.cleanup()

    def deps(self, tables=()):
        self.clock = Clock(self.sys, tables)
        return interrupt.Deps(self.sys, self.msg, self.quiet, stopall, self.clock, self.clock.sleep,
                              self.lines.append, lambda: 502)

    def run_stop(self, *args, tables=()):
        return interrupt.main(["stop", *args], self.deps(tables))


class InterruptTest(Base):

    def test_dry_run_changes_nothing(self):
        self.assertEqual(self.run_stop("--dry-run"), 0)
        self.assertFalse(stopall.record().exists())
        self.assertFalse((interrupt.root() / "log.jsonl").exists())
        self.assertEqual(self.sys.kills, [])
        self.assertFalse(any(c[:2] == ["tart", "stop"] for c in self.sys.calls))
        self.assertTrue(all(s[3] for s in self.msg.sent))
        self.assertEqual(self.quiet.applied[0][2], True)
        out = "\n".join(self.lines)
        for want in ("would freeze hal2-daemon 600", "would stop tart VM hal2-ci-runner-macos",
                     "would freeze build 100", "would freeze 77", "would re-scan every 5 s", "would tell 4"):
            self.assertIn(want, out)

    def test_stop_records_tells_freezes_and_logs(self):
        self.assertEqual(self.run_stop("--note", "a call"), 0)
        state = json.loads(stopall.record().read_text())
        self.assertEqual(state["kind"], "important-interrupt")
        self.assertEqual(state["stopped"], ["07-ab", "08-cd", "09-ef", "10-gh"])
        ii = state["important_interrupt"]
        self.assertEqual(ii["first_action"], 0)
        self.assertEqual(ii["caller"], "/w/yard")
        self.assertEqual(ii["seconds"], 5.0)
        texts = [a["text"] for a in state["actions"]]
        self.assertTrue(texts[0].startswith("freeze hal2-daemon 600"))
        self.assertEqual(texts[1], "stop tart VM hal2-ci-runner-macos")
        self.assertEqual(texts[2], "freeze 77 (/w/07)")
        self.assertTrue(any(t.startswith("freeze build 100") for t in texts))
        self.assertEqual(self.sys.kills[0], (600, "STOP"))
        self.assertNotIn((503, "STOP"), self.sys.kills)  # the caller's own cargo
        self.assertEqual(self.quiet.applied[0][:3], (["/w/yard"], True, False))
        self.assertEqual(sorted(self.quiet.applied[0][3]), ["78", "actions.runner.hal2"])
        self.assertTrue(all(s[2] == "bypass" and "run the pause skill" in s[1] and "/pause" not in s[1]
                            and "a call" in s[1] for s in self.msg.sent))
        row = json.loads((interrupt.root() / "log.jsonl").read_text().splitlines()[-1])
        self.assertEqual((row["kind"], row["told"], row["paused"], row["silent"], row["dry"]), ("stop", 4, 1, 3, False))
        self.assertEqual(row["counts"]["daemon"], 1)
        self.assertEqual(row["counts"]["runner"], 1)
        self.assertEqual(row["counts"]["build"], 8)
        self.assertIn("quiet after 0m 5s (idle 85%)", self.lines)
        self.assertNotIn("pause container db: docker pause 1  (failed)", self.lines)

    def test_rescan_freezes_what_starts_later(self):
        late = {700: [1, os.getuid(), "R", 90.0, "/x/xcodebuild", "xcodebuild build"]}
        self.sys.idle = [30.0, 30.0, 85.0]
        self.run_stop(tables=[late])
        self.assertIn((700, "STOP"), self.sys.kills)
        state = json.loads(stopall.record().read_text())
        self.assertTrue(any(a["text"].startswith("freeze build 700") for a in state["actions"]))
        self.assertEqual(state["important_interrupt"]["seconds"], 10.0)

    def test_not_quiet_within_the_timeout(self):
        self.sys.idle = [10.0]
        self.assertEqual(self.run_stop("--timeout", "20", "--reply-wait", "0"), 4)
        self.assertTrue(any(line.startswith("not quiet after 20.0s") for line in self.lines))
        row = json.loads((interrupt.root() / "log.jsonl").read_text())
        self.assertIsNone(row["quiet_at"])

    def test_earlier_holds_are_left_as_they_are(self):
        stopall.save(["08-cd"], [], "earlier")
        old = self.msg.pause_record(self.msg.rows[2])
        old.write_text("paused")
        os.utime(old, (time.time() - 3600, time.time() - 3600))
        self.run_stop()
        told = sorted(s[0] for s in self.msg.sent)
        self.assertEqual(told, ["07-ab", "10-gh"])
        held = json.loads(stopall.record().read_text())["important_interrupt"]["held"]
        self.assertEqual(held, [{"name": "08-cd", "why": "in an active stop"},
                                {"name": "09-ef", "why": "paused earlier"}])
        self.assertTrue(any("earlier hold (paused earlier)" in line for line in self.lines))

    def test_stale_or_busy_pause_records_are_no_hold(self):
        for row in self.msg.rows[1:3]:
            self.msg.pause_record(row).write_text("paused")
            os.utime(self.msg.pause_record(row), (time.time() - 3600, time.time() - 3600))
        self.msg.rows[2]["status"] = "busy"  # paused once, working again since
        history = stopall.root() / "history"
        history.mkdir(parents=True)
        (history / "1.json").write_text(json.dumps({"continued_at": "2000-01-01T00:00:00+00:00"}))
        self.run_stop("--dry-run")
        self.assertEqual(sorted(s[0] for s in self.msg.sent), ["07-ab", "09-ef", "10-gh"])
        (history / "2.json").write_text(json.dumps({"continued_at": interrupt.iso(time.time() - 60)}))
        self.msg.sent.clear()
        self.run_stop("--dry-run")  # both records are older than the last system-wide continue: stale
        self.assertEqual(sorted(s[0] for s in self.msg.sent), ["07-ab", "08-cd", "09-ef", "10-gh"])

    def test_classify(self):
        for text, kind in (("would freeze build 1 (x)", "build"), ("freeze 7 (/w)", "session"),
                           ("unload LaunchAgent local.x", "agent"), ("terminate Ollama", "ollama"),
                           ("unload LaunchAgent actions.runner.y", "runner"), ("stop tart VM a", "vm")):
            self.assertEqual(interrupt.classify(text), kind)

    def test_stop_is_the_default_and_done_without_a_stop_exits_1(self):
        self.assertEqual(interrupt.main(["--dry-run"], self.deps()), 0)
        self.assertEqual(interrupt.main(["done", "--dry-run"], self.deps()), 1)
        self.assertIn("no important interrupt is active", self.lines[-1])

    def test_stop_text_never_aborts_a_landing(self):
        self.run_stop("--dry-run")
        text = self.msg.sent[0][1]
        self.assertIn("never abort it", text)
        self.assertIn("adopts the interrupted landing", text)
        self.assertNotIn("NEW landing", text)


if __name__ == "__main__":
    unittest.main()
