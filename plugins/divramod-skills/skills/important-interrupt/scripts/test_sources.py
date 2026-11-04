"""sources.py's workqueue holders: `freeze all` (undo `thaw all`), the earlier manual freezes kept, the `freeze serve`
holders SIGSTOPped (undo SIGCONT) and done's undo order; the machine and the workqueue CLI are fakes (WqSys), the
stop record is stopall.py's own in a temp root; nothing real is signalled or frozen."""
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

import interrupt  # first: it puts stop-all-agent-work's scripts on sys.path
import resume
import sources
import stopall
from test_freeze import ME, FakeSys, machine

HOLDERS = {
    700: [1, ME, "S", 12.0, "/u/.cargo/bin/hal2-cli-workqueue",
          '/u/.cargo/bin/hal2-cli-workqueue freeze serve --manual {"scope":"all"}'],
    701: [1, ME, "R", 30.0, "/u/.cargo/bin/hal2-cli-workqueue", "hal2-cli-workqueue freeze serve --manual {}"],
    702: [1, ME, "T", 0.0, "/u/.cargo/bin/hal2-cli-workqueue", "hal2-cli-workqueue freeze serve --manual {}"],
    703: [1, 0, "S", 5.0, "/usr/bin/hal2-cli-workqueue", "hal2-cli-workqueue freeze serve --manual {}"],
    704: [1, ME, "S", 5.0, "/u/.cargo/bin/hal2-cli-workqueue", "hal2-cli-workqueue hold serve --class landing"],
    705: [1, ME, "S", 1.0, "/usr/bin/less", "less freeze serve notes.txt"],
}


def hold(scope, session=None, max_min=None, cls="manual"):
    return {"seq": 1, "id": f"h-{scope}-{session}", "pid": 700, "class": cls, "scope": scope, "session": session,
            "field": "all", "by": "farmer-hal2", "reason": "a call", "since": "2026-11-03T07:00:00Z",
            "max_min": max_min, "ends_at": "2026-11-03T08:00:00Z" if max_min else None, "state": "holding",
            "processes": 3, "spared": 1, "held": [], "spared_processes": []}


class WqSys(FakeSys):
    """FakeSys plus the workqueue CLI: `frozen --json` answers `holds`, `freeze all` the given state."""

    def __init__(self, cli, holds=(), frozen_code=0, freeze_state="frozen", freeze_code=0):
        super().__init__({**machine(), **{k: list(v) for k, v in HOLDERS.items()}})
        self.cli, self.holds, self.frozen_code = cli, list(holds), frozen_code
        self.freeze_state, self.freeze_code, self.wq = freeze_state, freeze_code, []

    def run(self, cmd, timeout=60):
        if cmd[0] != self.cli:
            return super().run(cmd, timeout)
        self.wq.append((cmd[1:], timeout))
        if cmd[1] == "frozen":
            return (self.frozen_code, json.dumps({"schema": 1, "holds": self.holds}) if not self.frozen_code
                    else "", "timed out after 15s" if self.frozen_code == 124 else "")
        if cmd[1:3] == ["freeze", "all"]:
            if self.freeze_code:
                return self.freeze_code, "", "boom"
            return 0, json.dumps({"schema": 1, "state": self.freeze_state, "hold": hold("all"), "ignored": []}), ""
        return 0, "", ""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.cli = base / "hal2-cli-workqueue"
        self.cli.write_text("#!/bin/sh\nexit 99\n")  # never run: WqSys answers it
        self.cli.chmod(self.cli.stat().st_mode | stat.S_IXUSR)
        self.env = {"STOP_ALL_AGENT_WORK_ROOT": str(base / "stop"), "IMPORTANT_INTERRUPT_ROOT": str(base / "ii"),
                    "HAL2_CLI_WORKQUEUE": str(self.cli)}
        self.saved = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        self.lines = []
        self.use(WqSys(str(self.cli)))

    def tearDown(self):
        for k, v in self.saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.tmp.cleanup()

    def use(self, sys_):
        self.sys = sys_
        self.d = interrupt.Deps(sys_, None, None, stopall, out=self.lines.append, getpid=lambda: 502)

    def actions(self):
        return json.loads(stopall.record().read_text())["actions"] if stopall.record().exists() else []

    def wq_verbs(self):
        return [" ".join(c[:2]) for c, _ in self.sys.wq]

    def out(self):
        return "\n".join(self.lines)


class ServeRowsTest(Base):
    def test_only_the_users_running_freeze_serve_holders(self):
        table = interrupt.freeze.proc_table(self.sys)
        rows = sources.serve_rows(table, set(), ME)
        self.assertEqual([r["pid"] for r in rows], [700, 701])  # not stopped 702, root's 703, hold serve, less
        self.assertTrue(all(r["kind"] == "holder" for r in rows))
        self.assertEqual(sources.serve_rows(table, {700}, ME)[0]["pid"], 701)


class WorkqueueHoldersTest(Base):
    def test_freeze_all_once_then_holders_stopped(self):
        res = sources.workqueue_holders(self.d, False)
        self.assertEqual(res["source"], "workqueue holders")
        self.assertEqual(res["kinds"], ["wq-freeze", "holder", "holder"])
        self.assertEqual(self.wq_verbs(), ["frozen --json", "freeze all"])
        self.assertTrue(all(t <= sources.CALL for _, t in self.sys.wq))
        self.assertEqual(self.sys.kills, [(700, "STOP"), (701, "STOP")])
        acts = self.actions()
        self.assertEqual([a["kind"] for a in acts], ["wq-freeze", "holder", "holder"])
        self.assertEqual(acts[0]["undo"], [str(self.cli), "thaw", "all"])
        self.assertEqual(acts[1]["undo"], ["CONT", 700])
        self.assertEqual(res["note"], {"freeze_all": "set", "hold": "h-all-None", "refreeze": [], "cli": str(self.cli),
                                       "holders": 2})

    def test_done_resumes_holders_then_thaws_then_refreezes(self):
        self.use(WqSys(str(self.cli), holds=[hold("session", "hal2/25"), hold("session", "hal2/26", max_min=30),
                                             hold("runs", cls="landing")]))
        sources.workqueue_holders(self.d, False)
        self.assertIn("earlier freeze of hal2/26 ends by itself", self.out())
        self.sys.wq.clear()
        self.sys.kills.clear()
        kinds = resume.undo_machine(self.d, self.actions(), False)
        self.assertEqual(kinds, ["holder", "holder", "wq-freeze", "wq-refreeze"])
        self.assertEqual(self.sys.kills, [(701, "CONT"), (700, "CONT")])
        self.assertEqual([c for c, _ in self.sys.wq], [["thaw", "all"], ["freeze", "hal2/25", "--reason", "a call",
                                                                         "--by", "farmer-hal2"]])

    def test_an_earlier_freeze_all_stays(self):
        self.use(WqSys(str(self.cli), holds=[hold("all")]))
        res = sources.workqueue_holders(self.d, False)
        self.assertEqual(self.wq_verbs(), ["frozen --json"])  # never froze, so done never thaws
        self.assertFalse(any(a["kind"] in ("wq-freeze", "wq-refreeze") for a in self.actions()))
        self.assertEqual(res["note"]["freeze_all"], "earlier")
        self.assertEqual(self.sys.kills, [(700, "STOP"), (701, "STOP")])  # the spinning holders still stop (D2)

    def test_already_answer_records_no_thaw(self):
        self.use(WqSys(str(self.cli), freeze_state="already"))
        res = sources.workqueue_holders(self.d, False)
        self.assertEqual(res["note"]["freeze_all"], "earlier")
        self.assertEqual([a["kind"] for a in self.actions()], ["holder", "holder"])

    def test_missing_cli_is_reported_not_fatal(self):
        os.environ["HAL2_CLI_WORKQUEUE"] = str(Path(self.tmp.name) / "nope")
        res = sources.workqueue_holders(self.d, False)
        self.assertIn("hal2-cli-workqueue not found", self.out())
        self.assertEqual(self.sys.wq, [])
        self.assertEqual(res["kinds"], ["holder", "holder"])
        self.assertIsNone(res["note"]["cli"])

    def test_failing_freeze_all_is_reported_not_fatal(self):
        self.use(WqSys(str(self.cli), freeze_code=1))
        res = sources.workqueue_holders(self.d, False)
        self.assertIn("workqueue freeze all failed (exit 1: boom)", self.out())
        self.assertEqual(res["note"]["freeze_all"], "failed")
        self.assertEqual([a["kind"] for a in self.actions()], ["holder", "holder"])

    def test_timed_out_probe_is_reported_and_freeze_goes_on(self):
        self.use(WqSys(str(self.cli), frozen_code=124))
        res = sources.workqueue_holders(self.d, False)
        self.assertIn("workqueue holds not readable (exit 124: timed out", self.out())
        self.assertIn("thaw all ends every manual freeze", self.out())
        self.assertEqual(res["note"]["freeze_all"], "set")
        self.assertEqual(self.sys.wq[0][1], sources.PROBE)

    def test_dry_run_changes_nothing(self):
        self.use(WqSys(str(self.cli), holds=[hold("session", "hal2/25")]))
        res = sources.workqueue_holders(self.d, True)
        self.assertEqual(self.wq_verbs(), ["frozen --json"])  # the probe only
        self.assertEqual(self.sys.kills, [])
        self.assertFalse(stopall.record().exists())
        self.assertEqual(res["kinds"], ["wq-freeze", "holder", "holder"])
        for want in ("would freeze every session's work", "thaw all",
                     "would keep the earlier workqueue freeze of hal2/25", "would freeze workqueue holder 700"):
            self.assertIn(want, self.out())

    def test_rescan_takes_only_new_holders(self):
        sources.workqueue_holders(self.d, False)
        self.sys.procs[706] = [1, ME, "S", 9.0, "/u/.cargo/bin/hal2-cli-workqueue",
                               "hal2-cli-workqueue freeze serve --manual {}"]
        self.sys.kills.clear()
        self.assertEqual(sources.serves(self.d, False), ["holder"])
        self.assertEqual(self.sys.kills, [(706, "STOP")])

    def test_sources_lists_the_source(self):
        self.assertEqual([n for n, _ in sources.SOURCES], ["workqueue holders"])


if __name__ == "__main__":
    unittest.main()
