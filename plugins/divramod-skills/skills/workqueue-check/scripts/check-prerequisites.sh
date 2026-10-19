#!/usr/bin/env bash
# Check the tools the workqueue check needs. Exit 1 when python3 is missing; hal2-cli-workqueue is needed for the
# numbers (without it the check says so and stops), the benchmarks are optional.
missing=0
if command -v python3 >/dev/null 2>&1; then echo "ok python3"; else echo "MISSING python3 -> brew install python (or: sudo apt-get install -y python3)"; missing=1; fi
if command -v hal2-cli-workqueue >/dev/null 2>&1; then echo "ok hal2-cli-workqueue"; else echo "optional hal2-cli-workqueue missing: not installed yet, the check cannot read the journal"; fi
exit "$missing"
