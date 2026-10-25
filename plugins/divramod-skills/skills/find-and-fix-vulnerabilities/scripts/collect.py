#!/usr/bin/env python3
"""find-and-fix-vulnerabilities, step 1: the collectors. Runs osv-scanner over the farms, trivy over Docker and VM
images, the OS update checks and the read-only ssh scans of the servers, and prints one Report (schema 1).
Read-only: nothing is installed, fixed or written. Exit 0 also with findings, 2 on bad arguments."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_farms  # noqa: E402
import collect_images  # noqa: E402
import collect_os  # noqa: E402
import collect_servers  # noqa: E402
from findings import Report, dedupe  # noqa: E402
from run import Runner  # noqa: E402

PARTS = ("farms", "images", "os", "servers")


def parse_args(argv):
    p = argparse.ArgumentParser(prog="collect.py", description=__doc__)
    p.add_argument("--root", default="~/a", help="the folder of the farms (default ~/a)")
    p.add_argument("--only", default=",".join(PARTS), help="comma list of: " + ", ".join(PARTS))
    p.add_argument("--worktree", help="a worktree to scan instead of its repository's main checkout under --root")
    p.add_argument("--servers-config", help="servers.toml (default: vulns/servers.toml in the hal2 config folder)")
    p.add_argument("--vm-mount", action="append", default=[], metavar="NAME=PATH",
                   help="a mounted VM disk to scan with trivy rootfs (repeatable)")
    p.add_argument("--image", action="append", default=[], metavar="IMAGE",
                   help="scan only this image with trivy (repeatable), not every local and Dockerfile image")
    p.add_argument("--json", action="store_true", help="print the Report as JSON (the default prints a summary)")
    args = p.parse_args(argv)
    args.parts = [x for x in args.only.split(",") if x]
    bad = [x for x in args.parts if x not in PARTS]
    if bad or not args.parts:
        p.error(f"--only: unknown part {bad or args.only!r}, use {', '.join(PARTS)}")
    args.mounts = {}
    for item in args.vm_mount:
        name, sep, path = item.partition("=")
        if not sep or not name or not path:
            p.error(f"--vm-mount {item!r}: use NAME=PATH")
        args.mounts[name] = path
    return args


def run_all(runner, args) -> Report:
    report = Report()
    root = Path(args.root).expanduser()
    worktree = Path(args.worktree).expanduser() if args.worktree else None
    farms = []
    if "farms" in args.parts or "images" in args.parts:
        farms = collect_farms.discover_farms(root, worktree)
    if "farms" in args.parts:
        collect_farms.collect(runner, report, root, worktree)
    if "images" in args.parts:
        collect_images.collect(runner, report, farms, args.mounts, args.image)
    if "os" in args.parts:
        collect_os.collect(runner, report)
    if "servers" in args.parts:
        cfg = Path(args.servers_config).expanduser() if args.servers_config else None
        collect_servers.collect(runner, report, cfg)
    return report


def summary(report: Report) -> str:
    found = dedupe(report.findings)
    by = {}
    for f in found:
        by[f.severity] = by.get(f.severity, 0) + 1
    counts = ", ".join(f"{n} {s}" for s, n in sorted(by.items())) or "none"
    return (f"{len(found)} findings ({counts}); {len(report.errors)} errors; {len(report.skipped)} skipped\n"
            + "".join(f"error: {e['target']}: {e['message']}\n" for e in report.errors)
            + "".join(f"skipped: {s['target']}: {s['why']}\n" for s in report.skipped))


def main(argv=None, runner=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = run_all(runner or Runner(), args)
    print(report.to_json() if args.json else summary(report), end="\n" if args.json else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
