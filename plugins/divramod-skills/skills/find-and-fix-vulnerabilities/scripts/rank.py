"""Rank findings and group identical ones across targets into rows with a `where` list."""
from findings import SEVERITIES

ROW_FIELDS = ("id", "aliases", "package", "ecosystem", "version", "fixed_version", "severity", "cvss", "kev",
              "kev_added", "kev_ransomware", "summary")


def sort_key(row: dict) -> tuple:
    return (not row["kev"], not row["kev_ransomware"], SEVERITIES.index(row["severity"]),
            -(row["cvss"] or 0.0), row["id"], row["package"], row["version"])


def group(findings: list) -> list:
    """One row per (id, package, version, fixed_version); `where` lists the targets, sorted."""
    rows = {}
    for f in findings:
        k = (f.id, f.package, f.version, f.fixed_version)
        d = f.to_dict()
        row = rows.get(k)
        if row is None:
            row = rows[k] = {x: d[x] for x in ROW_FIELDS}
            row["where"] = []
        else:
            if SEVERITIES.index(f.severity) < SEVERITIES.index(row["severity"]):
                row["severity"] = f.severity
            row["cvss"] = max(row["cvss"] or 0.0, f.cvss or 0.0) or None
            row["kev"], row["kev_ransomware"] = row["kev"] or f.kev, row["kev_ransomware"] or f.kev_ransomware
        if f.target not in row["where"]:
            row["where"].append(f.target)
    for row in rows.values():
        row["where"].sort()
    return sorted(rows.values(), key=sort_key)


def sort_findings(findings: list) -> list:
    return sorted(findings, key=lambda f: sort_key({**f.to_dict(), "where": []}))
