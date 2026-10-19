"""freeze.py finds the build/test processes, hal2-daemon and the running tart VMs, and freezes them; every process,
command and signal here is a fake (FakeSys), nothing real is ever signalled."""
import json
import os
import unittest

import freeze

ME = os.getuid()


class FakeSys:
    """A fake machine: a process table (pid -> [ppid, uid, stat, cpu, comm, args]), tart, top, lsof; records calls."""

    def __init__(self, procs=None, idle=(95.0,), vms=None, cwds=None, fail=()):
        self.procs = dict(procs or {})
        self.idle, self.vms, self.cwds, self.fail = list(idle), vms, cwds or {}, set(fail)
        self.calls, self.kills = [], []

    def run(self, cmd, timeout=60):
        self.calls.append(cmd)
        if cmd[:2] == ["ps", "-axo"] and cmd[2].endswith("comm="):
            return 0, "".join(f"{pid} {p[0]} {p[1]} {p[2]} {p[3]} {p[4]}\n" for pid, p in self.procs.items()), ""
        if cmd[:2] == ["ps", "-axo"]:
            return 0, "".join(f"{pid} {p[5]}\n" for pid, p in self.procs.items()), ""
        if cmd[0] == "top":
            idle = self.idle.pop(0) if len(self.idle) > 1 else self.idle[0]
            return 0, f"CPU usage: 50.0% user, 10.0% sys, 40.0% idle\nCPU usage: 1% user, 1% sys, {idle}% idle\n", ""
        if cmd[:2] == ["tart", "list"]:
            return (127, "", "no tart") if self.vms is None else (0, json.dumps(self.vms), "")
        if cmd[:2] == ["tart", "stop"]:
            return (1 if cmd[2] in self.fail else 0), "", ""
        if cmd[:2] == ["git", "rev-parse"]:
            return 0, "/w/yard\n", ""
        return 127, "", "unknown"

    def kill(self, pid, sig):
        self.kills.append((pid, sig))
        if pid not in self.procs:
            return False
        self.procs[pid][2] = "T" if sig == "STOP" else "S"
        return True

    def cwd(self, pid):
        return self.cwds.get(pid, "/w/other")


def machine():
    return {
        1: [0, 0, "Ss", 0.1, "/sbin/launchd", "/sbin/launchd"],
        500: [1, ME, "S", 5.0, "claude", "claude --dangerously-skip-permissions"],
        501: [500, ME, "S", 0.0, "/bin/zsh", "/bin/zsh -c python3 interrupt.py"],
        502: [501, ME, "R", 1.0, "/usr/bin/python3", "python3 interrupt.py stop"],
        503: [500, ME, "R", 90.0, "/x/cargo", "cargo nextest run -p hal2-core"],  # the caller's own: kept
        100: [1, ME, "R", 80.0, "/u/.rustup/bin/cargo", "cargo build -p hal2-daemon"],
        101: [100, ME, "R", 99.0, "/u/.rustup/bin/rustc", "rustc --crate-name hal2_core"],
        102: [101, ME, "R", 40.0, "/usr/bin/clang", "clang -c x.c"],
        103: [100, ME, "T", 0.0, "/u/.rustup/bin/rustc", "rustc --crate-name frozen"],
        200: [1, ME, "R", 100.0, "/Applications/Xcode.app/Contents/MacOS/Xcode", "/Applications/Xcode.app/..."],
        201: [200, ME, "R", 100.0, "/Applications/Xcode.app/Contents/Developer/usr/bin/xcodebuild", "xcodebuild test"],
        300: [1, ME, "R", 60.0, "/opt/bin/node", "node node_modules/.bin/vitest run"],
        301: [1, ME, "R", 60.0, "/opt/bin/node", "node server.js"],
        304: [1, ME, "S", 9.0, "/opt/bin/node", "node /n/bin/playwright-mcp --browser chrome"],  # an agent's MCP
        305: [1, ME, "R", 50.0, "/opt/bin/node", "node /n/node_modules/playwright/cli.js test --workers 4"],
        302: [1, ME, "R", 30.0, "/usr/local/bin/docker", "docker build -t x ."],
        303: [1, ME, "R", 30.0, "/usr/bin/python3.12", "python3.12 -m pytest tests"],
        400: [1, 0, "R", 50.0, "/usr/bin/cargo", "cargo build"],  # another user's: never touched
        600: [1, ME, "S", 2.0, "/Users/mod/.cargo/bin/hal2-daemon", "/Users/mod/.cargo/bin/hal2-daemon"],
        601: [600, ME, "S", 20.0, "/Users/mod/.local/bin/tart", "tart run hal2-ci-runner-macos"],
    }


class FreezeTest(unittest.TestCase):
    def setUp(self):
        self.sys = FakeSys(machine())
        self.table = freeze.proc_table(self.sys)

    def test_proc_table_joins_comm_and_args(self):
        self.assertEqual(self.table[101]["comm"], "/u/.rustup/bin/rustc")
        self.assertEqual(self.table[101]["args"], "rustc --crate-name hal2_core")
        self.assertEqual(self.table[400]["uid"], 0)

    def test_caller_tree_is_everything_below_its_claude(self):
        tree = freeze.caller_tree(self.table, 502)
        self.assertTrue({500, 501, 502, 503} <= tree)
        self.assertNotIn(100, tree)
        self.assertEqual(freeze.caller_tree(self.table, 301), {301})  # no claude above: only the chain

    def test_builds_freezes_roots_and_all_below_parents_first(self):
        rows = freeze.builds(self.table, freeze.caller_tree(self.table, 502), [], self.sys)
        pids = [r["pid"] for r in rows]
        self.assertEqual(pids[:3], [100, 101, 102])  # cargo, its rustc, the clang below rustc
        self.assertEqual(sorted(pids), [100, 101, 102, 201, 300, 302, 303, 305])
        self.assertTrue(all(r["kind"] == "build" for r in rows))

    def test_builds_keeps_the_caller_frozen_apps_and_other_users(self):
        pids = {r["pid"] for r in freeze.builds(self.table, freeze.caller_tree(self.table, 502), [], self.sys)}
        for kept in (503, 103, 200, 301, 304, 400, 600):
            self.assertNotIn(kept, pids)

    def test_builds_keeps_a_root_in_a_kept_checkout(self):
        self.sys.cwds[100] = "/w/yard/code/rust"
        pids = {r["pid"] for r in freeze.builds(self.table, set(), ["/w/yard"], self.sys)}
        self.assertFalse(pids & {100, 101, 102})
        self.assertIn(201, pids)

    def test_daemon_and_vms(self):
        self.assertEqual([r["pid"] for r in freeze.daemon(self.table)], [600])
        self.assertEqual(freeze.vms(self.sys), [])  # tart missing
        self.sys.vms = [{"Name": "a", "Running": True}, {"Name": "b", "State": "stopped", "Running": False},
                        {"Name": "c", "State": "running"}]
        self.assertEqual([v["name"] for v in freeze.vms(self.sys)], ["a", "c"])

    def test_apply_dry_run_signals_nothing(self):
        lines = []
        rows = freeze.daemon(self.table) + [{"kind": "vm", "name": "a", "what": "tart VM a"}]
        self.assertEqual(freeze.apply(rows, self.sys, True, lines.append), [])
        self.assertEqual(self.sys.kills, [])
        self.assertFalse(any(c[:2] == ["tart", "stop"] for c in self.sys.calls))
        self.assertTrue(lines[0].startswith("would freeze hal2-daemon 600"))
        self.assertTrue(lines[1].startswith("would stop tart VM a: tart stop a"))

    def test_apply_records_each_action_with_its_undo(self):
        self.sys.fail.add("b")
        rows = freeze.daemon(self.table) + [{"kind": "vm", "name": "a", "what": "tart VM a"},
                                            {"kind": "vm", "name": "b", "what": "tart VM b"}]
        lines = []
        done = freeze.apply(rows, self.sys, False, lines.append)
        self.assertEqual(self.sys.kills, [(600, "STOP")])
        self.assertEqual(done[0]["do"], ["STOP", 600])
        self.assertEqual(done[0]["undo"], ["CONT", 600])
        self.assertEqual(done[1], {"text": "stop tart VM a", "kind": "vm", "do": ["tart", "stop", "a"], "undo": None})
        self.assertEqual(len(done), 2)  # the failed stop of b is not recorded
        self.assertTrue(lines[2].endswith("(failed)"))

    def test_cpu_idle_reads_the_second_sample(self):
        self.assertEqual(freeze.cpu_idle(FakeSys(idle=(87.5,))), 87.5)

        class Silent(FakeSys):
            def run(self, cmd, timeout=60):
                return 1, "", ""
        self.assertIsNone(freeze.cpu_idle(Silent()))

    def test_busiest(self):
        self.assertTrue(freeze.busiest(self.table, 2)[0].startswith("200 100%") or
                        freeze.busiest(self.table, 2)[0].startswith("201 100%"))


if __name__ == "__main__":
    unittest.main()
