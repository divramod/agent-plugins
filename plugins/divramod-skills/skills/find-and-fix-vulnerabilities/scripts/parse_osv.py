"""osv-scanner JSON (v2 `--format json`, v1 `--json`: the same `results[].packages[].vulnerabilities[]` shape) to Findings."""
import json

import findings as fx


def _float(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _fixed(vulns: list, package: str):
    """The first `fixed` event of an affected range for this package, over the group's vulnerabilities."""
    for v in vulns:
        for a in v.get("affected", []):
            if a.get("package", {}).get("name") not in (package, None):
                continue
            for r in a.get("ranges", []):
                for e in r.get("events", []):
                    if e.get("fixed"):
                        return e["fixed"]
    return None


def _primary(ids: list, aliases: list) -> str:
    for cand in ids + aliases:
        if cand.startswith("CVE-"):
            return cand
    return ids[0]


def _groups(pkg: dict, by_id: dict) -> list:
    """(ids, max_severity) per group; a vulnerability in no group is its own group."""
    out, seen = [], set()
    for g in pkg.get("groups", []):
        ids = [i for i in g.get("ids", []) if i in by_id]
        if ids:
            out.append((ids, _float(g.get("max_severity")), g.get("aliases", [])))
            seen.update(ids)
    for i in by_id:
        if i not in seen:
            out.append(([i], None, by_id[i].get("aliases", [])))
    return out


def _severity(vulns: list, score):
    if score is not None:
        return fx.severity_from_cvss(score)
    for v in vulns:
        s = fx.normalize_severity(v.get("database_specific", {}).get("severity"))
        if s != "UNKNOWN":
            return s
    return "UNKNOWN"


def parse(text: str) -> list:
    data = json.loads(text) if text.strip() else {}
    found = []
    for res in data.get("results") or []:
        target = fx.tilde(res.get("source", {}).get("path", ""))
        for pkg in res.get("packages") or []:
            p = pkg.get("package", {})
            by_id = {v["id"]: v for v in pkg.get("vulnerabilities") or [] if v.get("id")}
            for ids, score, g_aliases in _groups(pkg, by_id):
                vulns = [by_id[i] for i in ids]
                aliases = set(g_aliases) | {a for v in vulns for a in v.get("aliases", [])} | set(ids)
                primary = _primary(ids, sorted(aliases))
                found.append(fx.Finding(
                    id=primary, aliases=sorted(aliases - {primary}), target_kind="farm", target=target,
                    package=p.get("name", ""), ecosystem=p.get("ecosystem", ""), version=p.get("version", ""),
                    fixed_version=_fixed(vulns, p.get("name", "")), severity=_severity(vulns, score), cvss=score,
                    source="osv-scanner", summary=(vulns[0].get("summary") or "")[:200]))
    return found
