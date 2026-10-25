import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import cache
import enrich
import kev
import rank
import report
import table
from findings import Finding, Report
from testutil import data

NOW = 1_000_000.0


def f(id_, target="~/a/io", package="p", version="1", fixed="2", sev="UNKNOWN", cvss=None, aliases=()):
    return Finding(id=id_, target_kind="farm", target=target, package=package, version=version, fixed_version=fixed,
                   severity=sev, cvss=cvss, aliases=list(aliases), source="osv-scanner")


class Fetcher:
    """A fake network: url -> text; counts calls; an unknown url fails like a dead network."""

    def __init__(self, table):
        self.table, self.calls = table, []

    def __call__(self, url):
        self.calls.append(url)
        if url not in self.table:
            raise OSError("no network")
        return self.table[url]


def kev_fetcher():
    return Fetcher({kev.URL: data("kev-fixture.json")})


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)


class KevFeed(Tmp):
    def test_index_and_alias_match(self):
        idx = kev.load(fetch=kev_fetcher(), directory=self.dir, now=NOW)
        self.assertEqual(idx["CVE-2023-4863"], {"added": "2026-10-05", "ransomware": True})
        self.assertIsNotNone(kev.lookup(idx, f("GHSA-xxxx", aliases=["CVE-2021-44228"])))
        self.assertIsNone(kev.lookup(idx, f("CVE-2000-1")))

    def test_cache_is_used_while_fresh_then_refetched(self):
        fetch = kev_fetcher()
        kev.load(fetch=fetch, directory=self.dir, now=NOW)
        os.utime(self.dir / "kev.json", (NOW, NOW))
        kev.load(fetch=fetch, directory=self.dir, now=NOW + 11 * 3600)
        self.assertEqual(len(fetch.calls), 1)
        kev.load(fetch=fetch, directory=self.dir, now=NOW + 13 * 3600)
        self.assertEqual(len(fetch.calls), 2)

    def test_offline_reads_cache_only(self):
        fetch = kev_fetcher()
        with self.assertRaises(FileNotFoundError):
            kev.load(offline=True, fetch=fetch, directory=self.dir)
        kev.load(fetch=fetch, directory=self.dir, now=NOW)
        idx = kev.load(offline=True, fetch=fetch, directory=self.dir, now=NOW + 99 * 3600)
        self.assertIn("CVE-2024-3094", idx)
        self.assertEqual(len(fetch.calls), 1)

    def test_stale_cache_survives_a_dead_network(self):
        kev.load(fetch=kev_fetcher(), directory=self.dir, now=NOW)
        os.utime(self.dir / "kev.json", (NOW, NOW))
        idx = kev.load(fetch=Fetcher({}), directory=self.dir, now=NOW + 99 * 3600)
        self.assertIn("CVE-2021-44228", idx)

    def test_cache_dir_env(self):
        old = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(old)))
        os.environ.pop("HAL2_VULNS_CACHE", None)
        os.environ["XDG_CACHE_HOME"] = "/x"
        self.assertEqual(cache.cache_dir(), Path("/x/hal2/vulns"))
        os.environ["HAL2_VULNS_CACHE"] = "/y"
        self.assertEqual(cache.cache_dir(), Path("/y"))


class Enrich(Tmp):
    def test_kev_marks_and_severity_from_cvss(self):
        r = Report(findings=[f("CVE-2023-4863"), f("GHSA-a", aliases=["CVE-2021-44228"], cvss=9.8), f("CVE-1", cvss=7.5),
                             f("CVE-2", cvss=5.0), f("CVE-3", cvss=2.0), f("CVE-4"), f("CVE-5", sev="LOW", cvss=9.9)])
        enrich.enrich(r, kev.index(json.loads(data("kev-fixture.json"))))
        a, b, *rest = r.findings
        self.assertEqual((a.kev, a.kev_added, a.kev_ransomware), (True, "2026-10-05", True))
        self.assertEqual((b.kev, b.kev_ransomware, b.severity), (True, False, "CRITICAL"))
        self.assertEqual([x.severity for x in rest], ["HIGH", "MEDIUM", "LOW", "UNKNOWN", "LOW"])

    def test_osv_only_online_for_unknown_and_cached(self):
        osv = {enrich.OSV_URL + "GHSA-a": json.dumps({"database_specific": {"severity": "MODERATE"}})}
        fetch = Fetcher(osv)
        mk = lambda: Report(findings=[f("GHSA-a", target="t1"), f("GHSA-a", target="t2"), f("CVE-9", sev="HIGH"),
                                      f("macos-update:x"), f("RUSTSEC-1")])  # noqa: E731
        r = mk()
        enrich.enrich(r, {}, online=False, fetch=fetch, directory=self.dir)
        self.assertEqual(fetch.calls, [])
        r = mk()
        enrich.enrich(r, {}, online=True, fetch=fetch, directory=self.dir)
        self.assertEqual([x.severity for x in r.findings], ["MEDIUM", "MEDIUM", "HIGH", "UNKNOWN", "UNKNOWN"])
        self.assertEqual(fetch.calls, [enrich.OSV_URL + "GHSA-a", enrich.OSV_URL + "RUSTSEC-1"])
        self.assertEqual([e["target"] for e in r.errors], ["RUSTSEC-1"])
        r = mk()
        enrich.enrich(r, {}, online=True, fetch=fetch, directory=self.dir)
        self.assertEqual(fetch.calls.count(enrich.OSV_URL + "GHSA-a"), 1)


class Rank(unittest.TestCase):
    def test_order_and_grouping(self):
        kev_r = f("CVE-A", sev="LOW")
        kev_r.kev = kev_r.kev_ransomware = True
        kev_p = f("CVE-B", sev="LOW")
        kev_p.kev = True
        rows = rank.group([f("CVE-C", sev="HIGH", cvss=7.0), f("CVE-D", sev="CRITICAL", cvss=9.0), kev_p, kev_r,
                           f("CVE-E", sev="HIGH", cvss=8.0), f("CVE-F", sev="HIGH", cvss=8.0),
                           f("CVE-C", target="~/a/hal2", sev="HIGH", cvss=7.0), f("CVE-C", version="9")])
        self.assertEqual([r["id"] for r in rows], ["CVE-A", "CVE-B", "CVE-D", "CVE-E", "CVE-F", "CVE-C", "CVE-C"])
        c = [r for r in rows if r["id"] == "CVE-C" and r["version"] == "1"][0]
        self.assertEqual(c["where"], ["~/a/hal2", "~/a/io"])


class Output(Tmp):
    def rows(self):
        return [dict(rank.group([f("CVE-2023-4863", target=f"t{i}", sev="HIGH") for i in range(5)])[0], kev=True)]

    def test_table(self):
        out = table.render(self.rows(), [{"target": "trivy", "message": "boom"}], [{"target": "vm1", "why": "no mount"}])
        lines = out.splitlines()
        self.assertEqual(lines[0], "1 vulnerabilities, 1 KEV, 0 critical, 1 high")
        self.assertEqual(lines[2], table.HEAD)
        self.assertEqual(lines[4], "| CVE-2023-4863 | t0, t1, t2 +2 | p | 1 | 2 | KEV | HIGH |")
        self.assertIn("- trivy: boom", out)
        self.assertIn("- vm1: no mount", out)

    def run_cli(self, args, rep):
        path = self.dir / "r.json"
        path.write_text(rep.to_json())
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = report.main(["--input", str(path), *args], fetch=kev_fetcher())
        return rc, buf.getvalue()

    def test_cli_json_and_table(self):
        old = os.environ.get("HAL2_VULNS_CACHE")
        os.environ["HAL2_VULNS_CACHE"] = str(self.dir / "c")
        self.addCleanup(lambda: os.environ.pop("HAL2_VULNS_CACHE") if old is None else os.environ.update(
            HAL2_VULNS_CACHE=old))
        rep = Report(findings=[f("CVE-1", cvss=9.5), f("GHSA-q", aliases=["CVE-2021-44228"], target="b")])
        rc, out = self.run_cli(["--json"], rep)
        d = json.loads(out)
        self.assertEqual((rc, d["schema"], [x["id"] for x in d["findings"]]), (0, 1, ["GHSA-q", "CVE-1"]))
        self.assertTrue(d["rows"][0]["kev"])
        self.assertEqual(Report.from_json(out).findings[0].kev_added, "2026-10-10")
        rc, out = self.run_cli(["--offline"], rep)
        self.assertIn("| GHSA-q | b |", out)
        self.assertTrue(out.startswith("2 vulnerabilities, 1 KEV, 1 critical"))

    def test_offline_without_cache_reports_error_but_ranks(self):
        os.environ["HAL2_VULNS_CACHE"] = str(self.dir / "none")
        self.addCleanup(os.environ.pop, "HAL2_VULNS_CACHE")
        rc, out = self.run_cli(["--offline"], Report(findings=[f("CVE-1", sev="HIGH")]))
        self.assertEqual(rc, 0)
        self.assertIn("KEV feed not available", out)

    def test_bad_input_exit_2(self):
        self.assertEqual(report.main(["--input", str(self.dir / "missing.json")]), 2)


if __name__ == "__main__":
    unittest.main()
