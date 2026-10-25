#!/usr/bin/env python3
"""find-and-fix-vulnerabilities, step 2: enrich and rank a collect.py report (CISA KEV, severity), print the table.
Input: --input report.json or stdin. --offline reads the caches only; --online also asks OSV for unknown severities.
--json prints the enriched report (schema 1, findings ranked, plus `rows` grouped across targets). Exit 0, 2 on bad input."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cache  # noqa: E402
import enrich  # noqa: E402
import kev  # noqa: E402
import rank  # noqa: E402
import table  # noqa: E402
from findings import SCHEMA, Report, is_outdated  # noqa: E402


def build(report: Report, offline: bool, online: bool, fetch, directory=None, now=None, show_all: bool = False) -> dict:
    try:
        idx = kev.load(offline=offline, fetch=fetch, directory=directory, now=now)
    except (OSError, ValueError) as e:
        idx = {}
        report.add_error("kev", f"CISA KEV feed not available, KEV marks missing: {e}")
    enrich.enrich(report, idx, online=online and not offline, fetch=fetch, directory=directory)
    hidden = [f for f in report.findings if is_outdated(f)]
    if not show_all:
        report.findings = [f for f in report.findings if not is_outdated(f)]
    report.findings = rank.sort_findings(report.findings)
    return {"schema": SCHEMA, "generated": report.generated, "findings": [f.to_dict() for f in report.findings],
            "rows": rank.group(report.findings), "hidden_outdated": 0 if show_all else len(hidden), "errors": report.errors, "skipped": report.skipped}


def main(argv=None, stdin=None, fetch=None) -> int:
    p = argparse.ArgumentParser(prog="report.py", description=__doc__)
    p.add_argument("--input", help="a collect.py --json file (default: stdin)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="use the caches only, no network")
    mode.add_argument("--online", action="store_true", help="also look unknown severities up at OSV")
    p.add_argument("--all", action="store_true", help="also show outdated packages without a vulnerability id")
    p.add_argument("--json", action="store_true", help="print the enriched ranked JSON instead of the table")
    args = p.parse_args(argv)
    try:
        text = Path(args.input).read_text() if args.input else (stdin or sys.stdin).read()
        report = Report.from_json(text)
    except (OSError, ValueError) as e:
        print(f"report.py: {e}", file=sys.stderr)
        return 2
    out = build(report, args.offline, args.online, fetch or cache.http_get, show_all=args.all)
    print(json.dumps(out, indent=2) if args.json else table.render(out["rows"], out["errors"], out["skipped"], out["hidden_outdated"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
