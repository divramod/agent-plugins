#!/usr/bin/env bash
# Check the tools hal-deploy-to-hal-server's scripts need. Exit 1 when a required tool is missing.
# Required: python3 3.11+. Optional: ssh (status, deploy), docker (check runs hal9k-site-check's caddy adapt).
missing=0
if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
  echo "ok python3"
else
  echo "MISSING python3 3.11+ -> brew install python (or: sudo apt-get install -y python3)"; missing=1
fi
for tool in ssh docker; do
  if command -v "$tool" >/dev/null 2>&1; then echo "ok $tool"; else echo "optional $tool missing (its command is skipped)"; fi
done
exit "$missing"
