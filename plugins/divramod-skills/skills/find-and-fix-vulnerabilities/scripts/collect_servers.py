"""Servers: read-only checks over ssh. Only the commands of ALLOWED are ever sent; nothing writes remotely
(trivy fills its own cache folder on the server, the one thing it writes)."""
import tomllib
from pathlib import Path

import collect_os
import paths
import parse_os
import parse_trivy
from findings import Report

# name -> ssh alias (research 0107; docs/ci.md: hal2-ci-<machine> are the CI servers' aliases, the hub is the production host)
DEFAULTS = [("hz01", "hal2-ci-hz01"), ("az02", "hal2-ci-az02"), ("hub", "hal2-hub")]
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
TRIVY_WHICH = "command -v trivy"
TRIVY_ROOTFS = "trivy rootfs --format json --quiet --scanners vuln /"
ALLOWED = frozenset({collect_os.APT, collect_os.DNF, TRIVY_WHICH, TRIVY_ROOTFS})
UNREACHABLE = 255  # ssh's own failure: no connection, no key, a refused host


def load_servers(config: Path = None) -> list:
    """[(name, ssh host)] from `[[server]] name = .. host = ..` entries; the defaults when there is no file."""
    config = config or paths.servers_config()
    try:
        data = tomllib.loads(Path(config).read_text())
    except FileNotFoundError:
        return list(DEFAULTS)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ValueError(f"{config}: {e}")
    out = [(s["name"], s.get("host", s["name"])) for s in data.get("server", []) if s.get("name")]
    return out


def remote(runner, host: str, cmd: str, timeout: int = 120) -> tuple:
    if cmd not in ALLOWED:
        raise ValueError(f"not an allowed remote command: {cmd!r}")
    return runner.run(SSH + [host, cmd], timeout=timeout)


def _os_check(runner, report: Report, name: str, host: str) -> bool:
    """The Linux update check on the server; False when the server could not be reached."""
    rc, out, err = remote(runner, host, collect_os.APT)
    if rc == UNREACHABLE:
        report.add_error(name, f"ssh {host} unreachable: {err.strip()[:200]}")
        return False
    if rc == 0:
        report.findings.extend(parse_os.apt_security(out, name))
        return True
    rc, out, err = remote(runner, host, collect_os.DNF)
    if rc == 0:
        report.findings.extend(parse_os.dnf_security(out, name))
    else:
        report.add_error(name, f"no apt or dnf update list (rc {rc}): {err.strip()[:200]}")
    return True


def _trivy(runner, report: Report, name: str, host: str) -> None:
    rc, out, _ = remote(runner, host, TRIVY_WHICH)
    if rc != 0 or not out.strip():
        report.add_skip(name, "trivy not installed on the server: only the OS update check ran")
        return
    rc, out, err = remote(runner, host, TRIVY_ROOTFS, timeout=1200)
    if rc != 0:
        report.add_error(name, f"trivy rootfs failed (rc {rc}): {err.strip()[:200]}")
        return
    try:
        report.findings.extend(parse_trivy.parse(out, "server", name))
    except ValueError as e:
        report.add_error(name, f"trivy output is not JSON: {e}")


def collect(runner, report: Report, config: Path = None) -> None:
    try:
        servers = load_servers(config)
    except ValueError as e:
        report.add_error("servers", str(e))
        return
    for name, host in servers:
        if _os_check(runner, report, name, host):
            _trivy(runner, report, name, host)
