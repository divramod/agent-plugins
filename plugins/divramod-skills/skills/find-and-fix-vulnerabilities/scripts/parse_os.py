"""Pending-update output of the operating systems' tools to Findings. Pure text parsers, no program is started."""
import json
import re

import findings as fx

LABEL = re.compile(r"^\s*\*\s*Label:\s*(.+?)\s*$")
FIELD = re.compile(r"(Title|Version|Recommended|Action):\s*([^,]*)")
APT = re.compile(r"^(?P<pkg>[^/\s]+)/(?P<pockets>\S+)\s+(?P<new>\S+)\s+\S+\s+\[upgradable from:\s*(?P<old>[^\]]+)\]")
DNF = re.compile(r"^(?P<id>[A-Z]+-\S+)\s+(?P<sev>\S+?)/Sec\.\s+(?P<nvr>\S+)\s*$")
NVR = re.compile(r"^(?P<name>.+)-(?P<ver>[^-]+-[^-]+?)\.(?P<arch>[A-Za-z0-9_]+)$")
KB = re.compile(r"\bKB\d{6,8}\b")


def _os(kind_id, target, package, source, ecosystem, **kw) -> fx.Finding:
    return fx.Finding(id=kind_id, target_kind="os", target=target, package=package, source=source,
                      ecosystem=ecosystem, **kw)


def softwareupdate(text: str, target: str = "macos") -> list:
    """`softwareupdate --list`: a `* Label:` line, then its `Title: .., Version: .., Recommended: YES` line."""
    found, label = [], None
    for line in text.splitlines():
        m = LABEL.match(line)
        if m:
            label = m.group(1)
            continue
        fields = dict(FIELD.findall(line)) if label else {}
        if label and "Title" in fields:
            if fields.get("Recommended", "").strip().upper() == "YES":
                found.append(_os(f"macos-update:{label}", target, fields["Title"].strip(), "softwareupdate", "macos",
                                 fixed_version=fields.get("Version", "").strip() or None,
                                 summary=f"recommended update {fields['Title'].strip()}"))
            label = None
    return found


def brew_outdated(text: str, target: str = "macos") -> list:
    """`brew outdated --json=v2`: informational (no CVE is known from it), severity UNKNOWN."""
    data = json.loads(text) if text.strip() else {}
    found = []
    for kind in ("formulae", "casks"):
        for item in data.get(kind) or []:
            installed = item.get("installed_versions") or []
            found.append(_os(f"brew-outdated:{item.get('name', '')}", target, item.get("name", ""), "brew", "homebrew",
                             version=installed[-1] if installed else "",
                             fixed_version=item.get("current_version") or None,
                             summary=f"outdated {kind[:-1] if kind == 'casks' else 'formula'}, no CVE known"))
    return found


def apt_security(text: str, target: str) -> list:
    """`apt list --upgradable`, only the packages whose newer version comes from a `-security` pocket."""
    found = []
    for line in text.splitlines():
        m = APT.match(line)
        if m and "-security" in m.group("pockets"):
            found.append(_os(f"apt-security:{m.group('pkg')}", target, m.group("pkg"), "apt", "apt",
                             version=m.group("old").strip(), fixed_version=m.group("new"),
                             summary=f"security update from {m.group('pockets').split(',')[-1]}"))
    return found


def dnf_security(text: str, target: str) -> list:
    """`dnf updateinfo list --security`: `RHSA-2024:1234 Important/Sec. openssl-3.0.7-1.el9.x86_64`."""
    found = []
    for line in text.splitlines():
        m = DNF.match(line.strip())
        if not m:
            continue
        nvr = NVR.match(m.group("nvr"))
        name, ver = (nvr.group("name"), nvr.group("ver")) if nvr else (m.group("nvr"), "")
        found.append(_os(m.group("id"), target, name, "dnf", "rpm", fixed_version=ver or None,
                         severity=fx.normalize_severity(m.group("sev")), summary=f"security advisory {m.group('id')}"))
    return found


def _columns(header: str) -> list:
    names = ["Name", "Id", "Version", "Available", "Source"]
    starts = [header.find(n) for n in names]
    return [s for s in starts if s >= 0]


def winget_upgrade(text: str, target: str = "windows") -> list:
    """`winget upgrade`: a table cut at its header's column starts; rows below the dashes line."""
    lines = text.splitlines()
    head = next((i for i, ln in enumerate(lines) if ln.lstrip().startswith("Name") and "Available" in ln), None)
    if head is None:
        return []
    starts = _columns(lines[head])
    found = []
    for ln in lines[head + 2:]:
        if len(ln) < starts[-1] or not ln.strip() or ln.lstrip().startswith(("-", "\\", "/", "|")):
            continue
        if "upgrades available" in ln or "upgrade available" in ln:
            break
        cells = [ln[a:b].strip() for a, b in zip(starts, starts[1:] + [None])]
        if len(cells) >= 4 and cells[1]:
            found.append(_os(f"winget-upgrade:{cells[1]}", target, cells[1], "winget", "winget", version=cells[2],
                             fixed_version=cells[3] or None, summary=f"{cells[0]} can be upgraded"))
    return found


def windows_update(text: str, target: str = "windows") -> list:
    """The PowerShell lines `<MsrcSeverity><TAB><Title>`; an update with a KB id in its title is a finding."""
    found = []
    for line in text.splitlines():
        sev, _, title = line.partition("\t")
        if not title.strip():
            continue
        kb = KB.search(title)
        found.append(_os(kb.group(0) if kb else f"windows-update:{title.strip()[:60]}", target, title.strip(),
                         "windows-update", "windows", severity=fx.normalize_severity(sev),
                         summary=title.strip()[:200]))
    return found
