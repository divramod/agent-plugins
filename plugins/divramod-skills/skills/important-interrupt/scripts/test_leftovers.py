"""leftovers.py's report on canned outputs of each probe (ps, nettop, tmutil), a timeout, a missing tool and the
report's place in stop (also in the dry run, and the stop record's `leftovers`); the machine is a fake, nothing is
signalled or stopped."""
import json
import unittest

import interrupt  # first: it puts stop-all-agent-work's scripts on sys.path
import leftovers
import stopall
from test_freeze import ME, FakeSys, machine
from test_interrupt import Base

NETTOP = """,bytes_in,bytes_out,
launchd.1,5,5,
claude.2,900000,900000,
,bytes_in,bytes_out,
launchd.1,0,0,
mDNSResponder.434,3757195,313403,
Google Drive.1027,21807,26347,
2.1.317.7015,904168,11946269,
idle.9,0,0,
"""
TM_RUNNING = '''Backup session status:
{
    BackupPhase = Copying;
    ClientID = "com.apple.backupd";
    Percent = "0.45";
    Running = 1;
}
'''
TM_IDLE = '{\n    ClientID = "com.apple.backupd";\n    Percent = "-1";\n    Running = 0;\n}\n'
LOAD = {
    900: [1, ME, "R", 70.0, "/x/com.docker.virtualization", "com.docker.virtualization --kernel x"],
    901: [1, ME, "S", 8.0, "/x/com.docker.backend", "com.docker.backend"],
    902: [1, 0, "R", 40.0, "/System/Library/Metadata.framework/Support/mds_stores", "mds_stores"],
    903: [1, ME, "R", 15.0, "/System/Library/Metadata.framework/Support/mdworker_shared", "mdworker_shared -s x"],
    904: [1, ME, "R", 25.0, "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "Google Chrome"],
    905: [1, ME, "S", 12.0, "/Applications/Google Chrome.app/Helpers/Google Chrome Helper", "Chrome Helper"],
    906: [1, ME, "T", 99.0, "/u/.rustup/bin/rustc", "rustc frozen by the interrupt"],  # stopped: no load
}


class Sys(FakeSys):
    """FakeSys plus nettop and tmutil; `nettop`/`tmutil` set to a (code, output) pair."""

    def __init__(self, nettop=(0, NETTOP), tmutil=(0, TM_IDLE), procs=None):
        super().__init__({**machine(), **LOAD} if procs is None else procs)
        self.nettop, self.tmutil, self.timeouts = nettop, tmutil, []

    def run(self, cmd, timeout=60):
        if cmd[0] in ("nettop", "tmutil"):
            self.calls.append(cmd)
            self.timeouts.append((cmd[0], timeout))
            code, out = self.nettop if cmd[0] == "nettop" else self.tmutil
            return code, out, "" if code == 0 else ("timed out" if code == 124 else "nope")
        return super().run(cmd, timeout)


class D:
    def __init__(self, sys_):
        self.sys, self.lines = sys_, []

    def out(self, line):
        self.lines.append(line)


def report(**kw):
    d = D(Sys(**kw))
    return d, {i["item"]: i for i in leftovers.report(d)}


class ReportTest(unittest.TestCase):
    def test_every_item_on_canned_outputs(self):
        d, items = report(tmutil=(0, TM_RUNNING))
        self.assertEqual(list(items), ["cpu", "network", "docker", "timemachine", "spotlight", "chrome"])
        self.assertEqual(d.lines[0], "still running (reported only, not stopped):")
        self.assertEqual(len(d.lines), 7)
        cpu = items["cpu"]["top"]
        pids = [r["pid"] for r in cpu]
        self.assertEqual(pids[:3], [200, 201, 101])  # busiest first
        self.assertNotIn(906, pids)  # stopped by the interrupt (stat T): no load
        self.assertEqual(len(cpu), 5)
        self.assertEqual(items["docker"]["count"], 2)
        self.assertEqual(items["docker"]["cpu"], 78.0)
        self.assertEqual(items["spotlight"]["cpu"], 55.0)
        self.assertEqual(items["chrome"]["text"], "Chrome: 2 processes, CPU 37%")
        self.assertIn("Time Machine: backup RUNNING (Copying, 45%)", items["timemachine"]["text"])

    def test_network_takes_the_last_sample_biggest_first(self):
        rows = leftovers.talkers(NETTOP)
        self.assertEqual([(r[1], r[2]) for r in rows[:3]], [("2.1.317", 7015), ("mDNSResponder", 434),
                                                             ("Google Drive", 1027)])
        _, items = report()
        top = items["network"]["top"]
        self.assertEqual(top[0]["name"], "2.1.317")
        self.assertNotIn("claude", json.dumps(top))  # the first (cumulative) sample is dropped
        self.assertNotIn("idle", [t["name"] for t in top])  # zero bytes: no talker
        self.assertIn("in 883.0KB out 11.4MB", items["network"]["text"])

    def test_time_machine_idle(self):
        _, items = report()
        self.assertEqual(items["timemachine"]["text"], "Time Machine: not running")
        self.assertFalse(items["timemachine"]["running"])

    def test_quiet_machine_says_so(self):
        d, items = report(nettop=(0, ",bytes_in,bytes_out,\nlaunchd.1,0,0,\n"), procs={1: [0, 0, "Ss", 0.1, "/sbin/launchd", "launchd"]})
        self.assertEqual(items["cpu"]["text"], "CPU top: no process over 1%")
        self.assertEqual(items["network"]["text"], "network top: quiet (no bytes in the last second)")
        self.assertEqual(items["docker"]["text"], "Docker VM: not running")
        self.assertEqual(items["chrome"]["count"], 0)

    def test_a_missing_tool_and_a_timeout_are_one_line_never_fatal(self):
        d, items = report(nettop=(127, ""), tmutil=(124, ""))
        self.assertEqual(items["network"]["text"], "network: nettop not found")
        self.assertEqual(items["timemachine"]["text"], "Time Machine: tmutil timed out after 10s")
        self.assertEqual(len(items), 6)  # the other probes still ran
        _, items = report(nettop=(1, ""), tmutil=(0, "garbage"))
        self.assertEqual(items["network"]["text"], "network: nettop failed (1): nope")
        self.assertEqual(items["timemachine"]["text"], "Time Machine: status not readable")

    def test_every_external_probe_has_a_timeout(self):
        d, _ = report()
        sys_ = d.sys
        self.assertEqual(sys_.timeouts, [("nettop", leftovers.NETTOP_TIMEOUT), ("tmutil", leftovers.TM_TIMEOUT)])

    def test_ps_gives_nothing(self):
        d, items = report(procs={})
        self.assertEqual(items["cpu"]["text"], "CPU top: ps gave nothing")


class StopTest(Base):
    def test_dry_run_prints_the_section_before_the_table_and_writes_no_record(self):
        self.assertEqual(self.run_stop("--dry-run"), 0)
        out = "\n".join(self.lines)
        self.assertIn("still running (reported only, not stopped):", out)
        self.assertIn("  CPU top: ", out)
        self.assertIn("  network: nettop not found", out)  # FakeSys has no nettop: reported, not fatal
        self.assertIn("-- leftover report (what still runs): 6 reported in", out)
        self.assertLess(out.index("still running"), out.index("| paused"))
        self.assertFalse(stopall.record().exists())

    def test_stop_stores_the_report_in_the_record_after_the_settle(self):
        self.run_stop()
        out = "\n".join(self.lines)
        self.assertLess(out.index("-- rescan to quiet"), out.index("still running"))
        rec = json.loads(stopall.record().read_text())["important_interrupt"]
        self.assertEqual([i["item"] for i in rec["leftovers"]],
                         ["cpu", "network", "docker", "timemachine", "spotlight", "chrome"])
        self.assertIn("leftovers", [s["step"] for s in rec["steps"]])
        row = json.loads((interrupt.root() / "log.jsonl").read_text().splitlines()[-1])
        self.assertIn("leftovers", [s["step"] for s in row["steps"]])


if __name__ == "__main__":
    unittest.main()
