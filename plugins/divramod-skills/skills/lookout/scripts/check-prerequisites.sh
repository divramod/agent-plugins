#!/usr/bin/env bash
# Check the tools lookout needs, then those of its bundled checks (checks/). Exit 1 when a required tool is missing.
# Optional: claude (only a watch with a judge), a desktop notifier (terminal-notifier or osascript on macOS,
# notify-send on Linux) and hal2-cli-secrets (the Telegram token); without them that step is skipped and logged.
here="$(cd "$(dirname "$0")" && pwd)"
missing=0
if command -v python3 >/dev/null 2>&1; then
  echo "ok python3"
else
  echo "MISSING python3 -> brew install python (or: sudo apt-get install -y python3)"
  missing=1
fi
if [ -n "${LOOKOUT_CLAUDE:-}" ] || command -v claude >/dev/null 2>&1; then
  echo "ok claude"
else
  echo "MISSING claude (optional: the judge) -> npm install -g @anthropic-ai/claude-code"
fi
case "$(uname -s)" in
  Darwin) notifiers="terminal-notifier osascript" ;;
  *) notifiers="notify-send" ;;
esac
found=""
for tool in $notifiers; do
  if command -v "$tool" >/dev/null 2>&1; then found=$tool; break; fi
done
if [ -n "$found" ]; then
  echo "ok $found"
else
  echo "MISSING $notifiers (optional: the desktop notification) -> brew install terminal-notifier (or: sudo apt-get install -y libnotify-bin)"
fi
if command -v hal2-cli-secrets >/dev/null 2>&1; then
  echo "ok hal2-cli-secrets"
else
  echo "MISSING hal2-cli-secrets (optional: Telegram) -> cargo install --path code/rust/apps/hal2-cli-secrets (in ~/a/hal2)"
fi
"$here/checks/check-prerequisites.sh" || missing=1
exit "$missing"
