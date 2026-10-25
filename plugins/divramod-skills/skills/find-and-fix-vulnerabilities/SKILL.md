---
name: find-and-fix-vulnerabilities
description: Find the vulnerabilities in everything the user runs and write the fix plan — `scripts/scan.py` scans every farm in ~/a with osv-scanner, Dockerfile base images, Docker images and VM disks with trivy, the pending security updates of this Mac, Linux or Windows machine, and the servers read-only over ssh; the findings are matched against CISA KEV first, then NVD, GHSA/OSV and the vendors' pages, and printed as one table (one row per vulnerability: CVE, where, version, fixed version, KEV, severity); then it writes one fix plan with a step per fix, KEV first. Read-only until that plan runs: the skill never fixes anything itself. Use when the user says /find-and-fix-vulnerabilities, "find vulnerabilities", "are we affected", "security scan", "CVE check" or "is anything exploited". `/find-and-fix-vulnerabilities h` shows help.
---

# find-and-fix-vulnerabilities

Thin by the record deterministic-first: the scripts collect, enrich, rank and write the plan as code; you only judge.
`S=scripts/scan.py` of this skill (run from the repository the plan goes into; `--repo <path>` names another).

| Call | Does |
|---|---|
| `/find-and-fix-vulnerabilities` | `python3 $S --plan`: collect, enrich, rank, print the table, write the fix plan |
| `/find-and-fix-vulnerabilities list` | `python3 $S`: the table only, no plan |
| `... --only farms,images,os,servers` | scan only those parts (`--root`, `--worktree`, `--image`, `--vm-mount NAME=PATH`, `--servers-config`) |
| `... --all` | also list the outdated packages without a vulnerability id (brew); by default the header counts them as "N outdated packages hidden (--all)" and neither table nor plan has them |
| `... --offline` | the caches only, no network (needs one earlier online run for the KEV feed) |
| `/find-and-fix-vulnerabilities h` | print this table and stop |

`--json` prints the enriched report; `--plan --dry-run` prints the plan it would write. First time on a machine:
`scripts/check-prerequisites.sh`; `scripts/install-prerequisites.sh` is for the user to run, never for you.

## Exit codes

0 the scan ran (also with findings; the first table line counts them); 2 bad arguments, bad input or no `plan.py`. A
part whose tool is missing (osv-scanner, trivy, docker, tart, ssh) is an error line under the table ("not installed"):
report it, never use another tool, never install one. A failed KEV feed leaves the KEV column empty and says so.

## Judge

Read the table; do not recompute it. Before the plan is written (run `list` first, then `--plan`) drop a false
positive only with a reason (dev-only dependency never shipped, a base image no longer used) by removing its row
from the JSON; otherwise leave the output as it is. Ask nothing before writing the plan: the plan is the output.
Image OS packages with no fix are one "rebuild <image> on a newer base" step per image. Then say in two lines how many, how many KEV, and the plan's path.

## Sources

CISA KEV (cisa.gov feed): what is exploited now, ranks "patch first". NVD: the official CVE list with CVSS, broadest,
enrichment lags. OSV.dev: open-source packages by ecosystem and exact version (also mirrors GHSA). GitHub Advisory
Database (GHSA): reviewed and malware advisories, items without a CVE. Vendor pages (php.net, nodejs.org, GitLab...):
the truth for affected and fixed versions. Details: `research/0107-security-week/research.md`.

## servers.toml

`~/.config/hal2/vulns/servers.toml` (`XDG_CONFIG_HOME` moves it), one entry per server, `host` an ssh alias:

```toml
[[server]]
name = "hz01"
host = "hal2-ci-hz01"
```

Without the file the defaults are hz01, az02 and hub. Only four fixed read-only commands are sent over ssh.

## Never fix here

No bump, install, upgrade, restart or commit in this skill. Fixing is the generated plan's job, run by its foreman.
