"""`check`: hal2's own validation of the declaration, the generated route through `hal9k-site-check`, then every
check of `checks/`. Nothing leaves the machine and nothing is written outside a scratch folder."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

import checks
import hal2
from checks import apex_host

SCHEMA = 1


def run_checker(root: Path, site: str, site_json: dict, fragment: str, adapted: str | None, image: str | None) -> dict:
    """The checker's own JSON verdict; exit 2 (no docker, bad input) is an `error` with its message."""
    with tempfile.TemporaryDirectory(prefix="hal-deploy-to-hal-server-") as scratch:
        sj, fr = Path(scratch, f"{site}.json"), Path(scratch, "Caddyfile")
        sj.write_text(json.dumps(site_json))
        fr.write_text(fragment)
        argv = [sys.executable, str(root / hal2.SITE_CHECK), "check", "--site", site, "--site-json", str(sj),
                "--fragment", str(fr), "--json"]
        if adapted:
            argv += ["--adapted", adapted]
        if image:
            argv += ["--image", image]
        proc = subprocess.run(argv, capture_output=True, text=True)
    if proc.returncode in (0, 1):
        return json.loads(proc.stdout)
    if proc.returncode == 3:  # the checker's no-verdict: its adapt timed out, a busy machine says nothing about the route
        detail = (json.loads(proc.stdout).get("reasons") or [{}])[0].get("detail", "adapt timed out")
        return {"verdict": "error", "reasons": [], "error": f"no verdict, rerun on a quieter machine: {detail}"}
    return {"verdict": "error", "reasons": [], "error": (proc.stderr.strip() or "the checker failed")[-400:]}


def check(declaration: Path, root: Path, repo: Path | None = None, adapted: str | None = None,
          image: str | None = None) -> dict:
    sites, site_container, shell = hal2.load_modules(root)
    result = {"schema": SCHEMA, "declaration": str(declaration), "validation": {"ok": False}, "route": None,
              "findings": [], "ok": False}
    try:
        data = tomllib.loads(declaration.read_text())
    except (OSError, ValueError) as err:
        result["validation"]["error"] = f"cannot read the declaration: {err}"
        return result
    config = shell.load_config()
    zone = config.get("zones", {}).get(data.get("zone"), {}) if isinstance(data.get("zone"), str) else {}
    context = {"site": declaration.stem, "container": data.get("container", {}), "inspect": None,
               "hosts": data.get("hosts") if isinstance(data.get("hosts"), list) else [], "domain": zone.get("name"),
               "zone": data.get("zone"), "other_sites": [],
               "limits": {"default_max_image": site_container.DEFAULT_MAX_IMAGE, "max_image_cap": site_container.MAX_IMAGE_CAP}}
    try:
        site = sites.validate(declaration, data, config)
        if not site.get("container"):
            raise shell.Failed(f"{declaration.name}: a [container] table is required: this skill deploys containers")
        # Against every site the next deploy would load, as `load_all` does: the cap and the secret names are over all.
        others = [s for s in sites.load_all(config) if s["name"] != site["name"]]
        context["other_sites"] = [{"name": s["name"], "zone": s.get("zone"), "hosts": s.get("hosts", []),
                                   "static": not s.get("container")} for s in others]
        site_container.check_memory([*others, site], config)
        site_container.check_secret_names([*others, site])
    except shell.Failed as err:
        result["validation"]["error"] = str(err)
        result["findings"] = apex_host.run(context)
        return result
    result["validation"]["ok"] = True
    result["route"] = run_checker(root, site["name"], sites.server_json(site, config),
                                  site_container.fragment(site, config), adapted, image)
    if repo is not None:
        import inspect_repo
        context["inspect"] = inspect_repo.inspect(repo)
    result["findings"] = checks.run_all(context)
    result["ok"] = (result["route"]["verdict"] == "accepted"
                    and not any(f["severity"] == "error" for f in result["findings"]))
    return result
