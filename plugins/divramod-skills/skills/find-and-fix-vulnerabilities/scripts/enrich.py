"""Enrich a Report: KEV marks, severity from the cvss score, optional OSV lookup for the still unknown severities."""
import re

import cache
import kev
from findings import normalize_severity, severity_from_cvss

OSV_URL = "https://api.osv.dev/v1/vulns/"
OSV_ID = re.compile(r"^(CVE-|GHSA-|RUSTSEC-|GO-|PYSEC-|OSV-)", re.I)


def mark_kev(findings: list, idx: dict) -> int:
    n = 0
    for f in findings:
        hit = kev.lookup(idx, f)
        if hit:
            f.kev, f.kev_added, f.kev_ransomware = True, hit["added"], hit["ransomware"]
            n += 1
    return n


def fill_severity(findings: list) -> None:
    for f in findings:
        if f.severity == "UNKNOWN" and f.cvss is not None:
            f.severity = severity_from_cvss(f.cvss)


def osv_lookup(vuln_id: str, fetch, directory, offline: bool = False) -> str:
    """The severity OSV states for an id (database_specific.severity), UNKNOWN if none."""
    data = cache.load(OSV_URL + vuln_id, directory / f"osv-{vuln_id}.json", offline=offline, fetch=fetch, max_age=86400)
    return normalize_severity((data.get("database_specific") or {}).get("severity"))


def fill_from_osv(report, fetch=cache.http_get, directory=None, offline: bool = False) -> None:
    """Ask OSV once per distinct id with UNKNOWN severity; failures go to report.errors."""
    directory = directory or cache.cache_dir()
    found = {}
    for f in report.findings:
        if f.severity != "UNKNOWN" or not OSV_ID.match(f.id):
            continue
        if f.id not in found:
            try:
                found[f.id] = osv_lookup(f.id, fetch, directory, offline)
            except (OSError, ValueError) as e:
                found[f.id] = "UNKNOWN"
                report.add_error(f.id, f"osv lookup failed: {e}")
        f.severity = found[f.id]


def enrich(report, kev_index: dict, online: bool = False, fetch=cache.http_get, directory=None) -> None:
    mark_kev(report.findings, kev_index)
    fill_severity(report.findings)
    if online:
        fill_from_osv(report, fetch, directory)
        fill_severity(report.findings)
