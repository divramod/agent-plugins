import shlex
import unittest

import collect_os
import findings as fx
import parse_os
from testutil import FakeRunner, data, ok


class Parsers(unittest.TestCase):
    def test_softwareupdate_keeps_recommended_only(self):
        found = parse_os.softwareupdate(data("softwareupdate.txt"))
        self.assertEqual([f.id for f in found], ["macos-update:macOS Sequoia 15.6-24G84",
                                                  "macos-update:Safari18.6SequoiaAuto-18.6"])
        f = found[0]
        self.assertEqual((f.target_kind, f.target, f.package, f.fixed_version, f.source, f.severity),
                         ("os", "macos", "macOS Sequoia 15.6", "15.6", "softwareupdate", "UNKNOWN"))

    def test_softwareupdate_nothing(self):
        self.assertEqual(parse_os.softwareupdate("Software Update Tool\n\nNo new software available.\n"), [])

    def test_brew_is_informational(self):
        found = parse_os.brew_outdated(data("brew.json"))
        self.assertEqual([(f.package, f.version, f.fixed_version, f.severity, f.source) for f in found],
                         [("openssl@3", "3.5.0", "3.5.1", "UNKNOWN", "brew"), ("ghostty", "1.1.0", "1.2.0", "UNKNOWN", "brew")])
        self.assertEqual(parse_os.brew_outdated(""), [])

    def test_apt_only_security_pockets(self):
        found = parse_os.apt_security(data("apt.txt"), "hz01")
        self.assertEqual([f.package for f in found], ["openssl", "libssl3t64", "linux-image-generic"])
        f = found[0]
        self.assertEqual((f.id, f.version, f.fixed_version, f.target, f.source, f.ecosystem),
                         ("apt-security:openssl", "3.0.13-0ubuntu3.4", "3.0.13-0ubuntu3.5", "hz01", "apt", "apt"))

    def test_dnf_security(self):
        found = parse_os.dnf_security(data("dnf.txt"), "az02")
        self.assertEqual([(f.id, f.package, f.fixed_version, f.severity) for f in found], [
            ("RHSA-2026:1234", "openssl", "1:3.0.7-28.el9_4", "HIGH"),
            ("RHSA-2026:2222", "kernel", "5.14.0-427.13.1.el9_4", "CRITICAL"),
            ("FEDORA-2026-abc123", "curl", "8.5.0-2.fc39", "MEDIUM")])

    def test_winget_table(self):
        found = parse_os.winget_upgrade(data("winget.txt"))
        self.assertEqual([(f.id, f.version, f.fixed_version, f.source) for f in found], [
            ("winget-upgrade:Git.Git", "2.45.0", "2.46.0", "winget"),
            ("winget-upgrade:Microsoft.VCRedist.2015", "14.38.33", "14.40.33", "winget")])
        self.assertEqual(parse_os.winget_upgrade("No installed package found matching input criteria."), [])

    def test_windows_update_kb_ids_and_severity(self):
        found = parse_os.windows_update(data("windows_update.txt"))
        self.assertEqual([(f.id, f.severity, f.source) for f in found[:2]],
                         [("KB5044284", "CRITICAL", "windows-update"), ("KB5044900", "HIGH", "windows-update")])
        self.assertEqual(found[2].severity, "UNKNOWN")
        self.assertTrue(found[2].id.startswith("windows-update:"))


class Local(unittest.TestCase):
    def test_macos(self):
        runner = FakeRunner({tuple(collect_os.SOFTWAREUPDATE): ok("", 0, data("softwareupdate.txt")),
                             tuple(collect_os.BREW): ok(data("brew.json"))})
        report = fx.Report()
        collect_os.collect(runner, report, "Darwin")
        self.assertEqual(len(report.findings), 4)  # softwareupdate wrote to stderr: read as well
        self.assertEqual(report.errors, [])

    def test_macos_without_brew_is_a_skip(self):
        runner = FakeRunner({tuple(collect_os.SOFTWAREUPDATE): ok("No new software available.\n")})
        report = fx.Report()
        collect_os.collect(runner, report, "Darwin")
        self.assertEqual(report.skipped, [{"target": "macos", "why": "brew not installed"}])

    def test_linux_apt_then_dnf(self):
        apt = tuple(shlex.split(collect_os.APT))
        report = fx.Report()
        collect_os.collect(FakeRunner({apt: ok(data("apt.txt"))}), report, "Linux")
        self.assertEqual(len(report.findings), 3)
        report = fx.Report()
        collect_os.collect(FakeRunner({tuple(shlex.split(collect_os.DNF)): ok(data("dnf.txt"))}), report, "Linux")
        self.assertEqual(len(report.findings), 3)
        self.assertEqual((report.errors, report.skipped), ([], []))

    def test_linux_neither_is_quiet_skip_of_dnf(self):
        report = fx.Report()
        collect_os.collect(FakeRunner(), report, "Linux")
        self.assertEqual(report.skipped, [{"target": "linux", "why": "dnf not installed"}])

    def test_windows(self):
        runner = FakeRunner({tuple(collect_os.POWERSHELL): ok(data("windows_update.txt")),
                             tuple(collect_os.WINGET): ok(data("winget.txt"))})
        report = fx.Report()
        collect_os.collect(runner, report, "Windows")
        self.assertEqual(len(report.findings), 5)

    def test_failing_check_is_an_error_and_unknown_system_a_skip(self):
        report = fx.Report()
        collect_os.collect(FakeRunner({tuple(collect_os.SOFTWAREUPDATE): ok("", 1, "no network")}), report, "Darwin")
        self.assertIn("no network", report.errors[0]["message"])
        report = fx.Report()
        collect_os.collect(FakeRunner(), report, "Plan9")
        self.assertEqual(report.skipped[0]["target"], "os")

    def test_commands_only_read(self):
        for argv in (collect_os.SOFTWAREUPDATE, collect_os.BREW, collect_os.WINGET, shlex.split(collect_os.APT),
                     shlex.split(collect_os.DNF)):
            self.assertFalse({"install", "-i", "-a", "--install", "--all"} & set(argv), argv)
        self.assertNotIn("Install", collect_os.WINDOWS_UPDATE_PS.replace("IsInstalled", ""))


if __name__ == "__main__":
    unittest.main()
