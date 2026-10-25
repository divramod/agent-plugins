"""The one findings shape (schema 1; the KEV fields are optional, a reader of older files defaults them): a Finding per vulnerability on a target, a Report of all of them."""
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

SCHEMA = 1
TARGET_KINDS = ("farm", "image", "vm", "server", "os")
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")
SOURCES = ("osv-scanner", "trivy", "softwareupdate", "apt", "dnf", "winget", "windows-update", "brew")


def severity_from_cvss(score) -> str:
    if score is None:
        return "UNKNOWN"
    if score >= 9.0:
        return "CRITICAL"
    if score >= 7.0:
        return "HIGH"
    if score >= 4.0:
        return "MEDIUM"
    return "LOW" if score > 0 else "UNKNOWN"


def normalize_severity(text) -> str:
    t = str(text or "").strip().upper()
    t = {"MODERATE": "MEDIUM", "IMPORTANT": "HIGH", "NEGLIGIBLE": "LOW", "MINOR": "LOW"}.get(t, t)
    return t if t in SEVERITIES else "UNKNOWN"


OS_ECOSYSTEMS = ("debian", "ubuntu", "alpine", "redhat", "centos", "rocky", "alma", "amazon", "oracle", "suse",
                 "opensuse", "sles", "photon", "fedora", "wolfi", "chainguard", "cbl-mariner", "azurelinux")


def is_outdated(f) -> bool:
    """An informational row without a vulnerability id (brew-outdated:<name>): outdated, not known vulnerable."""
    return str(f.id).startswith("brew-outdated:")


def tilde(path: str) -> str:
    """A path under the home folder as ~/..."""
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path == home or path.startswith(home + os.sep) else path


@dataclass
class Finding:
    id: str
    target_kind: str
    target: str
    package: str
    source: str
    ecosystem: str = ""
    version: str = ""
    fixed_version: object = None
    severity: str = "UNKNOWN"
    cvss: object = None
    aliases: list = field(default_factory=list)
    summary: str = ""
    kev: bool = False  # step 2: on CISA's known-exploited list
    kev_added: object = None  # the KEV dateAdded, YYYY-MM-DD
    kev_ransomware: bool = False  # KEV: used in ransomware campaigns

    def key(self) -> tuple:
        return (self.id, self.target, self.package, self.version)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Finding":
        names = Finding.__dataclass_fields__
        return Finding(**{k: v for k, v in d.items() if k in names})


def dedupe(findings: list) -> list:
    """One finding per (id, target, package, version); the first stays, gaps in it are filled from the later ones."""
    seen = {}
    for f in findings:
        old = seen.get(f.key())
        if old is None:
            seen[f.key()] = f
            continue
        old.aliases = sorted(set(old.aliases) | set(f.aliases))
        old.fixed_version = old.fixed_version or f.fixed_version
        if old.cvss is None and f.cvss is not None:
            old.cvss, old.severity = f.cvss, f.severity
        elif old.severity == "UNKNOWN":
            old.severity = f.severity
        old.summary = old.summary or f.summary
    return list(seen.values())


@dataclass
class Report:
    findings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    generated: str = ""

    def add_error(self, target: str, message: str) -> None:
        self.errors.append({"target": target, "message": message})

    def add_skip(self, target: str, why: str) -> None:
        self.skipped.append({"target": target, "why": why})

    def to_json(self) -> str:
        findings = dedupe(self.findings)
        return json.dumps({
            "schema": SCHEMA,
            "generated": self.generated or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "findings": [f.to_dict() for f in findings],
            "errors": self.errors,
            "skipped": self.skipped,
        }, indent=2)

    @staticmethod
    def from_json(text: str) -> "Report":
        d = json.loads(text)
        if d.get("schema") != SCHEMA:
            raise ValueError(f"findings schema {d.get('schema')!r}: this reader knows schema {SCHEMA}")
        return Report(findings=[Finding.from_dict(x) for x in d.get("findings", [])], errors=d.get("errors", []),
                      skipped=d.get("skipped", []), generated=d.get("generated", ""))
