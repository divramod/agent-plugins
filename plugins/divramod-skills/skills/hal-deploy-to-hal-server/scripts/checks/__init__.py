"""One module per known problem (`learn <slug>` scaffolds it). A check has `SLUG` (kebab-case), `WHY` (one line) and
`run(ctx) -> list[finding]`; ctx is `{"site": name, "container": the [container] table, "inspect": inspect's findings or
None, "hosts": the declared hosts, "domain": the zone's name, "limits": site_container's image limits}` (the last three
absent in a bare test); a finding is `{"check": SLUG, "severity": "error"|"warn", "detail": str}`. A check that needs the repository
returns [] when `ctx["inspect"]` is None. Each check has `test_check_<module>.py` beside `main.py`."""

from __future__ import annotations

import importlib
import pkgutil


def modules() -> list:
    return [importlib.import_module(f"{__name__}.{m.name}")
            for m in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name) if not m.name.startswith("_")]


def finding(slug: str, severity: str, detail: str) -> dict:
    return {"check": slug, "severity": severity, "detail": detail}


def run_all(ctx: dict) -> list[dict]:
    found = []
    for module in modules():
        found += module.run(ctx)
    return found
