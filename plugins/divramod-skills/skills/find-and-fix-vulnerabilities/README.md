# find-and-fix-vulnerabilities

Scans every farm, image, VM, OS and server for known vulnerabilities, ranks them (CISA KEV first) and writes one fix
plan with a step per fix. Read-only until that plan runs. Usage: [SKILL.md](SKILL.md). Stdlib Python 3.11+; tests:
`python3 -m unittest` in `scripts/`.

## Module map (`scripts/`)

| File | What |
|---|---|
| `scan.py` | the one command: collect, report, table, `--plan` the planwriter |
| `collect.py` | the collectors' CLI (`--only farms,images,os,servers`, `--image`, `--json`) |
| `collect_farms.py`, `collect_images.py`, `collect_os.py`, `collect_servers.py` | osv-scanner per farm; trivy over Docker and VM images; OS updates; read-only ssh |
| `parse_osv.py`, `parse_trivy.py`, `parse_os.py`, `dockerfiles.py` | pure parsers |
| `findings.py`, `run.py`, `paths.py` | the `Finding`/`Report` shape (schema 1), the process runner, config and cache roots |
| `report.py`, `enrich.py`, `kev.py`, `cache.py`, `rank.py`, `table.py` | KEV and OSV enrichment, ranking, the table |
| `planwriter.py`, `fixsteps.py` | the fix plan through the plan skill's `plan.py new` |
| `check-prerequisites.sh`, `install-prerequisites.sh` | python3; osv-scanner, trivy; optional docker, tart, ssh |
| `test_*.py`, `testutil.py`, `testdata/` | unittest on fixtures and a fake runner |
