#!/usr/bin/env bash
# Check the tools /hv needs: hal2-cli-halverse (ontology, check, learn's pair check) and hal2-cli-voiceink (voiceink). Exit 1
# when a required tool is missing.
missing=0
if command -v python3 >/dev/null 2>&1; then
  echo "ok python3"
else
  echo "MISSING python3 -> brew install python3 (or: sudo apt-get install -y python3)"
  missing=1
fi
if command -v hal2-cli-voiceink >/dev/null 2>&1; then
  echo "ok hal2-cli-voiceink"
else
  echo "MISSING hal2-cli-voiceink (only /hv voiceink needs it) -> cargo install --path apps/hal2-cli-voiceink, run in hal2's code/rust folder"
  missing=1
fi
if command -v hal2-cli-halverse >/dev/null 2>&1; then
  echo "ok hal2-cli-halverse"
else
  echo "MISSING hal2-cli-halverse (/hv ontology and /hv check need it) -> cargo install --path apps/hal2-cli-halverse, run in hal2's code/rust folder"
  missing=1
fi
exit "$missing"
