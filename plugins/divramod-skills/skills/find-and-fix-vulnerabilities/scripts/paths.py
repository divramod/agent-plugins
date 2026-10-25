"""Where find-and-fix-vulnerabilities keeps its files: the config root (servers.toml) and the cache root (KEV, OSV).
`XDG_CONFIG_HOME`/`XDG_CACHE_HOME` move the roots; `HAL2_VULNS_CONFIG` and `HAL2_VULNS_CACHE` override them (tests)."""
import os
from pathlib import Path


def _xdg(name: str, default: str) -> Path:
    value = os.environ.get(name)
    return Path(value) if value else Path.home() / default


def config_root() -> Path:
    if os.environ.get("HAL2_VULNS_CONFIG"):
        return Path(os.environ["HAL2_VULNS_CONFIG"])
    return _xdg("XDG_CONFIG_HOME", ".config") / "hal2" / "vulns"


def cache_root() -> Path:
    if os.environ.get("HAL2_VULNS_CACHE"):
        return Path(os.environ["HAL2_VULNS_CACHE"])
    return _xdg("XDG_CACHE_HOME", ".cache") / "hal2" / "vulns"


def servers_config() -> Path:
    return config_root() / "servers.toml"
