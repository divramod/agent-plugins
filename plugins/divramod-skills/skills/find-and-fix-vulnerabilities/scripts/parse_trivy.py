"""trivy JSON (`image` or `rootfs`, `Results[].Vulnerabilities[]`) to Findings."""
import json

import findings as fx


def _cvss(vuln: dict):
    """The NVD v3 score, else the highest v3 score of any source."""
    scores = {k: v.get("V3Score") for k, v in (vuln.get("CVSS") or {}).items() if isinstance(v, dict)}
    if scores.get("nvd") is not None:
        return float(scores["nvd"])
    values = [float(s) for s in scores.values() if s is not None]
    return max(values) if values else None


def _summary(vuln: dict) -> str:
    text = vuln.get("Title") or (vuln.get("Description") or "").split("\n")[0]
    return text[:200]


def parse(text: str, target_kind: str, target: str) -> list:
    data = json.loads(text) if text.strip() else {}
    found = []
    for res in data.get("Results") or []:
        for v in res.get("Vulnerabilities") or []:
            score = _cvss(v)
            sev = fx.normalize_severity(v.get("Severity"))
            found.append(fx.Finding(
                id=v.get("VulnerabilityID", ""), target_kind=target_kind, target=target,
                package=v.get("PkgName", ""), ecosystem=res.get("Type", ""), version=v.get("InstalledVersion", ""),
                fixed_version=v.get("FixedVersion") or None,
                severity=sev if sev != "UNKNOWN" else fx.severity_from_cvss(score), cvss=score, source="trivy",
                summary=_summary(v)))
    return [f for f in found if f.id]
