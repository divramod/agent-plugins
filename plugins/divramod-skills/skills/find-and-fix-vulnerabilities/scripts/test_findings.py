import json
import os
import unittest
from unittest import mock

import findings as fx
import parse_osv
import parse_trivy
from testutil import data


class Shape(unittest.TestCase):
    def test_schema_and_keys_are_pinned(self):
        f = fx.Finding(id="CVE-1", target_kind="farm", target="~/a/io", package="p", source="osv-scanner")
        self.assertEqual(sorted(f.to_dict()), sorted([
            "id", "aliases", "target_kind", "target", "package", "ecosystem", "version", "fixed_version", "severity",
            "cvss", "source", "summary", "kev", "kev_added", "kev_ransomware"]))
        d = json.loads(fx.Report(findings=[f]).to_json())
        self.assertEqual(d["schema"], 1)
        self.assertEqual(sorted(d), ["errors", "findings", "generated", "schema", "skipped"])
        self.assertRegex(d["generated"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertIsNone(d["findings"][0]["fixed_version"])

    def test_old_file_without_kev_fields_still_reads(self):
        old = {"schema": 1, "generated": "x", "findings": [{"id": "CVE-1", "target_kind": "os", "target": "m",
                                                           "package": "p", "source": "brew"}]}
        f = fx.Report.from_json(json.dumps(old)).findings[0]
        self.assertEqual((f.kev, f.kev_added, f.kev_ransomware), (False, None, False))

    def test_roundtrip(self):
        r = fx.Report(findings=[fx.Finding(id="CVE-1", target_kind="os", target="macos", package="x", source="brew",
                                           cvss=5.0, aliases=["GHSA-a"])])
        r.add_error("t", "boom")
        r.add_skip("v", "why")
        back = fx.Report.from_json(r.to_json())
        self.assertEqual(back.findings[0].to_dict(), r.findings[0].to_dict())
        self.assertEqual((back.errors, back.skipped), (r.errors, r.skipped))

    def test_other_schema_is_refused(self):
        with self.assertRaises(ValueError):
            fx.Report.from_json('{"schema": 2}')

    def test_dedupe_by_id_target_package_version(self):
        a = fx.Finding(id="CVE-1", target_kind="farm", target="t", package="p", version="1", source="osv-scanner")
        b = fx.Finding(id="CVE-1", target_kind="farm", target="t", package="p", version="1", source="osv-scanner",
                       aliases=["GHSA-x"], fixed_version="2", cvss=8.0, severity="HIGH")
        c = fx.Finding(id="CVE-1", target_kind="farm", target="t", package="p", version="1.1", source="osv-scanner")
        d = fx.Finding(id="CVE-1", target_kind="farm", target="t2", package="p", version="1", source="osv-scanner")
        out = fx.dedupe([a, b, c, d])
        self.assertEqual(len(out), 3)
        self.assertEqual((out[0].aliases, out[0].fixed_version, out[0].severity, out[0].cvss),
                         (["GHSA-x"], "2", "HIGH", 8.0))

    def test_severity_helpers(self):
        self.assertEqual([fx.severity_from_cvss(s) for s in (9.8, 7.0, 5.3, 2.0, 0.0, None)],
                         ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN", "UNKNOWN"])
        self.assertEqual([fx.normalize_severity(s) for s in ("Moderate", "important", "x", None, "critical")],
                         ["MEDIUM", "HIGH", "UNKNOWN", "UNKNOWN", "CRITICAL"])

    def test_tilde(self):
        with mock.patch.dict(os.environ, {"HOME": "/home/test"}):
            self.assertEqual(fx.tilde("/home/test/a/io"), "~/a/io")
            self.assertEqual(fx.tilde("/home/tester/a"), "/home/tester/a")


class OsvParsing(unittest.TestCase):
    def setUp(self):
        with mock.patch.dict(os.environ, {"HOME": "/home/test"}):
            self.found = parse_osv.parse(data("osv_v2.json"))

    def test_one_finding_per_group_with_cve_first(self):
        self.assertEqual([f.id for f in self.found], ["CVE-2021-23337", "CVE-2020-28500", "CVE-2020-26235"])
        f = self.found[0]
        self.assertEqual((f.target_kind, f.target, f.package, f.ecosystem, f.version, f.source),
                         ("farm", "~/a/io/pnpm-lock.yaml", "lodash", "npm", "4.17.20", "osv-scanner"))
        self.assertEqual((f.fixed_version, f.cvss, f.severity), ("4.17.21", 7.2, "HIGH"))
        self.assertEqual(f.aliases, ["GHSA-35jh-r3h4-6jhm"])
        self.assertEqual(f.summary, "Command Injection in lodash")

    def test_group_score_beats_database_severity(self):
        self.assertEqual((self.found[1].cvss, self.found[1].severity), (5.3, "MEDIUM"))

    def test_vulnerability_without_group_uses_database_severity(self):
        f = self.found[2]
        self.assertEqual((f.cvss, f.severity, f.fixed_version, f.ecosystem), (None, "MEDIUM", "0.2.23", "crates.io"))
        self.assertEqual(f.aliases, ["GHSA-wcg3-cvx6-7396", "RUSTSEC-2020-0071"])

    def test_empty_and_v1_output(self):
        self.assertEqual(parse_osv.parse(""), [])
        self.assertEqual(parse_osv.parse('{"results": null}'), [])


class TrivyParsing(unittest.TestCase):
    def test_vulnerabilities(self):
        found = parse_trivy.parse(data("trivy.json"), "image", "node:22-slim")
        self.assertEqual([f.id for f in found], ["CVE-2024-2961", "CVE-2023-31439", "CVE-2024-21538"])
        a, b, c = found
        self.assertEqual((a.package, a.version, a.fixed_version, a.cvss, a.severity, a.ecosystem, a.source),
                         ("libc6", "2.36-9+deb12u4", "2.36-9+deb12u6", 8.8, "HIGH", "debian", "trivy"))
        self.assertEqual((a.target_kind, a.target), ("image", "node:22-slim"))
        self.assertEqual((b.fixed_version, b.cvss, b.severity, b.summary), (None, None, "LOW", "An issue was discovered in systemd 253."))
        self.assertEqual((c.cvss, c.ecosystem), (7.7, "node-pkg"))

    def test_not_json_raises(self):
        with self.assertRaises(ValueError):
            parse_trivy.parse("<html>", "image", "x")
        self.assertEqual(parse_trivy.parse("", "image", "x"), [])


if __name__ == "__main__":
    unittest.main()
