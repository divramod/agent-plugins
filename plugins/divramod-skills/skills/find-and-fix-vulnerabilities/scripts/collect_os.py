"""Operating systems: the pending security updates of the machine this runs on (macOS, Linux, Windows)."""
import platform
import shlex

import parse_os
from findings import Report

APT = "apt list --upgradable"
DNF = "dnf updateinfo list --security"
SOFTWAREUPDATE = ["softwareupdate", "--list"]
BREW = ["brew", "outdated", "--json=v2"]
WINGET = ["winget", "upgrade", "--include-unknown", "--disable-interactivity"]
WINDOWS_UPDATE_PS = (
    "(New-Object -ComObject Microsoft.Update.Session).CreateUpdateSearcher()"
    ".Search(\"IsInstalled=0 and Type='Software'\").Updates | ForEach-Object { \"$($_.MsrcSeverity)`t$($_.Title)\" }")
POWERSHELL = ["powershell", "-NoProfile", "-NonInteractive", "-Command", WINDOWS_UPDATE_PS]


def _try(runner, report: Report, name: str, argv: list, parse, timeout: int = 120, merge_stderr: bool = False,
         skip_missing: bool = True):
    """Run one check and parse it; a missing program is a skip, a failing one an error. Returns the rc."""
    rc, out, err = runner.run(argv, timeout=timeout)
    if rc == 127:
        if skip_missing:
            report.add_skip(name, f"{argv[0]} not installed")
    elif rc != 0:
        report.add_error(name, f"{' '.join(argv[:2])} failed (rc {rc}): {err.strip()[:200]}")
    else:
        try:
            report.findings.extend(parse(out + "\n" + err if merge_stderr else out))
        except ValueError as e:
            report.add_error(name, f"{argv[0]} output not understood: {e}")
    return rc


def macos(runner, report: Report) -> None:
    # softwareupdate writes its list to stderr on some macOS versions: both are read
    _try(runner, report, "macos", SOFTWAREUPDATE, parse_os.softwareupdate, timeout=300, merge_stderr=True)
    _try(runner, report, "macos", BREW, parse_os.brew_outdated, timeout=120)


def linux(runner, report: Report) -> None:
    rc = _try(runner, report, "linux", shlex.split(APT), lambda t: parse_os.apt_security(t, "linux"),
              skip_missing=False)
    if rc == 127:
        _try(runner, report, "linux", shlex.split(DNF), lambda t: parse_os.dnf_security(t, "linux"))


def windows(runner, report: Report) -> None:
    _try(runner, report, "windows", POWERSHELL, parse_os.windows_update, timeout=300)
    _try(runner, report, "windows", WINGET, parse_os.winget_upgrade, timeout=120)


def collect(runner, report: Report, system: str = None) -> None:
    system = system or platform.system()
    handler = {"Darwin": macos, "Linux": linux, "Windows": windows}.get(system)
    if handler is None:
        report.add_skip("os", f"no OS check for {system}")
        return
    handler(runner, report)
