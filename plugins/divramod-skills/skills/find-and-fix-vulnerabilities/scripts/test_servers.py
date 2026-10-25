import tempfile
import unittest
from pathlib import Path

import collect_os
import collect_servers as cs
import findings as fx
from testutil import FakeRunner, data, ok, ssh_argv


def reachable(host, apt=True, trivy=True):
    table = {}
    if apt:
        table[ssh_argv(host, cs.collect_os.APT)] = ok(data("apt.txt"))
    else:
        table[ssh_argv(host, cs.collect_os.APT)] = ok("", 127, "bash: apt: command not found")
        table[ssh_argv(host, cs.collect_os.DNF)] = ok(data("dnf.txt"))
    table[ssh_argv(host, cs.TRIVY_WHICH)] = ok("/usr/bin/trivy\n") if trivy else ok("", 1)
    table[ssh_argv(host, cs.TRIVY_ROOTFS)] = ok(data("trivy.json"))
    return table


class Config(unittest.TestCase):
    def test_defaults_when_no_file(self):
        self.assertEqual([n for n, _ in cs.load_servers(Path("/nonexistent/servers.toml"))], ["hz01", "az02", "hub"])

    def test_toml(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "servers.toml"
            p.write_text('[[server]]\nname = "box"\nhost = "root@10.0.0.5"\n\n[[server]]\nname = "pi"\n')
            self.assertEqual(cs.load_servers(p), [("box", "root@10.0.0.5"), ("pi", "pi")])
            p.write_text("not [valid")
            with self.assertRaises(ValueError):
                cs.load_servers(p)
            report = fx.Report()
            cs.collect(FakeRunner(), report, p)
            self.assertEqual(report.errors[0]["target"], "servers")


class Collect(unittest.TestCase):
    def config(self, d, names):
        p = Path(d) / "servers.toml"
        p.write_text("".join(f'[[server]]\nname = "{n}"\nhost = "h-{n}"\n' for n in names))
        return p

    def test_os_check_and_trivy_rootfs(self):
        with tempfile.TemporaryDirectory() as d:
            runner = FakeRunner(reachable("h-a"))
            report = fx.Report()
            cs.collect(runner, report, self.config(d, ["a"]))
        kinds = {(f.target_kind, f.source) for f in report.findings}
        self.assertEqual(kinds, {("os", "apt"), ("server", "trivy")})
        self.assertEqual({f.target for f in report.findings}, {"a"})
        self.assertEqual(report.errors, [])

    def test_dnf_when_apt_is_missing_and_no_trivy_is_a_skip(self):
        with tempfile.TemporaryDirectory() as d:
            report = fx.Report()
            cs.collect(FakeRunner(reachable("h-a", apt=False, trivy=False)), report, self.config(d, ["a"]))
        self.assertEqual({f.source for f in report.findings}, {"dnf"})
        self.assertIn("trivy not installed on the server", report.skipped[0]["why"])

    def test_unreachable_server_is_an_error_and_the_next_one_goes_on(self):
        with tempfile.TemporaryDirectory() as d:
            table = {ssh_argv("h-a", collect_os.APT): ok("", 255, "ssh: connect to host h-a port 22: Connection refused")}
            table.update(reachable("h-b"))
            runner = FakeRunner(table)
            report = fx.Report()
            cs.collect(runner, report, self.config(d, ["a", "b"]))
        self.assertEqual(report.errors[0]["target"], "a")
        self.assertIn("unreachable", report.errors[0]["message"])
        self.assertTrue(all(f.target == "b" for f in report.findings))
        self.assertFalse(any(c[-2] == "h-a" and c[-1] != collect_os.APT for c in runner.calls))

    def test_only_allowlisted_commands_are_ever_sent(self):
        with tempfile.TemporaryDirectory() as d:
            runner = FakeRunner({**reachable("h-a"), **reachable("h-b", apt=False, trivy=False)})
            cs.collect(runner, fx.Report(), self.config(d, ["a", "b"]))
        self.assertTrue(runner.calls)
        for call in runner.calls:
            self.assertEqual(call[:len(cs.SSH)], cs.SSH)
            self.assertEqual(len(call), len(cs.SSH) + 2)
            self.assertIn(call[-1], cs.ALLOWED)
            self.assertEqual(call[0], "ssh")

    def test_a_command_outside_the_allowlist_is_refused(self):
        runner = FakeRunner()
        for bad in ("rm -rf /", "apt upgrade -y", "apt list --upgradable; touch x", "trivy rootfs /"):
            with self.assertRaises(ValueError):
                cs.remote(runner, "h", bad)
        self.assertEqual(runner.calls, [])

    def test_allowlist_is_read_only_text(self):
        self.assertEqual(cs.ALLOWED, {"apt list --upgradable", "dnf updateinfo list --security", "command -v trivy",
                                      "trivy rootfs --format json --quiet --scanners vuln /"})
        for cmd in cs.ALLOWED:
            self.assertFalse(any(w in cmd for w in (";", "&", "|", ">", "sudo", "install", "upgrade -y", "rm ")))
        self.assertIn("BatchMode=yes", cs.SSH)
        self.assertIn("ConnectTimeout=10", cs.SSH)


if __name__ == "__main__":
    unittest.main()
