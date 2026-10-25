"""Images: Docker images on this machine and the base images of the farms' Dockerfiles, scanned by trivy; Tart VMs."""
import json
from pathlib import Path

import dockerfiles
import parse_trivy
from findings import Report, tilde

TRIVY_IMAGE = ["trivy", "image", "--format", "json", "--quiet", "--scanners", "vuln"]
TRIVY_ROOTFS = ["trivy", "rootfs", "--format", "json", "--quiet", "--scanners", "vuln"]
VM_NEEDS = "vm scan needs a running VM: use the server collector over ssh"


def docker_images(runner, report: Report) -> list:
    rc, out, err = runner.run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"], timeout=30)
    if rc == 127:
        report.add_error("docker", "docker not installed")
        return []
    if rc != 0:
        report.add_error("docker", f"docker images failed (rc {rc}): {err.strip()[:200]}")
        return []
    return [i.strip() for i in out.splitlines() if i.strip() and "<none>" not in i]


def farm_images(farms: list, report: Report) -> list:
    images = []
    for farm in farms:
        for path in dockerfiles.find_dockerfiles(Path(farm)):
            try:
                found, unresolved = dockerfiles.parse(path.read_text(errors="replace"))
            except OSError as e:
                report.add_error(tilde(str(path)), f"cannot read: {e}")
                continue
            images += found
            for ref in unresolved:
                report.add_skip(f"{tilde(str(path))}: FROM {ref}", "a variable without a default")
    return images


def _scan(runner, report: Report, argv: list, kind: str, target: str) -> bool:
    """Run one trivy scan; False when trivy is not installed (the caller stops asking)."""
    rc, out, err = runner.run(argv, timeout=900)
    if rc == 127:
        report.add_error("trivy", "trivy not installed")
        return False
    if rc != 0:
        report.add_error(target, f"trivy failed (rc {rc}): {err.strip()[:200]}")
        return True
    try:
        report.findings.extend(parse_trivy.parse(out, kind, target))
    except ValueError as e:
        report.add_error(target, f"trivy output is not JSON: {e}")
    return True


def tart_vms(runner, report: Report) -> list:
    rc, out, err = runner.run(["tart", "list", "--format", "json"], timeout=30)
    if rc == 127:
        report.add_skip("tart", "tart not installed")
        return []
    if rc != 0:
        report.add_error("tart", f"tart list failed (rc {rc}): {err.strip()[:200]}")
        return []
    try:
        return [v["Name"] for v in json.loads(out) if v.get("Source", "local") == "local" and v.get("Name")]
    except (ValueError, TypeError, KeyError) as e:
        report.add_error("tart", f"tart list output is not JSON: {e}")
        return []


def collect(runner, report: Report, farms: list, vm_mounts: dict = None, only: list = ()) -> None:
    """`only` names the images to scan (instead of every local and Dockerfile image)."""
    vm_mounts = vm_mounts or {}
    images = sorted(only) if only else sorted(set(docker_images(runner, report)) | set(farm_images(farms, report)))
    for image in images:
        if not _scan(runner, report, TRIVY_IMAGE + [image], "image", image):
            break
    for vm in tart_vms(runner, report):
        if vm in vm_mounts:
            if not _scan(runner, report, TRIVY_ROOTFS + [vm_mounts[vm]], "vm", vm):
                break
        else:
            report.add_skip(vm, VM_NEEDS)
