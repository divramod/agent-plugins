#!/usr/bin/env bash
# Check the tools lookout's bundled checks need. Exit 1 when a required tool is missing; hal2-cli-email is
# optional: only a watch whose check is checks/email.py needs it (or $LOOKOUT_EMAIL_CLI).
missing=0
if command -v python3 >/dev/null 2>&1; then
  echo "ok python3"
else
  echo "MISSING python3 -> brew install python (or: sudo apt-get install -y python3)"
  missing=1
fi
if [ -n "${LOOKOUT_EMAIL_CLI:-}" ] || command -v hal2-cli-email >/dev/null 2>&1; then
  echo "ok hal2-cli-email"
else
  echo "MISSING hal2-cli-email (optional: the e-mail check; hal2 plan 0308) -> cargo install --path code/rust/apps/hal2-cli-email (in ~/a/hal2)"
fi
exit "$missing"
