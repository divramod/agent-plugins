#!/usr/bin/env bash
# Writes the CLI's answers for the skill's sample files (../sources) and copies its expected files (the contract),
# then records the writing calls (term/, term-refused/) on a scratch copy of the CLI's own nine fixture files.
# Run it from here with the built hal2-cli-halverse and hal2-cli-voiceink (HAL2_CLI_HALVERSE, HAL2_CLI_VOICEINK, else
# PATH) after the CLI's JSON changed. The files are made by the CLI, never by hand; the paths are relative.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
here="$PWD"
root="$here"; until [ -e "$root/.git" ] || [ "$root" = / ]; do root="$(dirname "$root")"; done  # any depth
cli="${HAL2_CLI_HALVERSE:-hal2-cli-halverse}"
voiceink="${HAL2_CLI_VOICEINK:-hal2-cli-voiceink}"
tests="$root/code/rust/apps/hal2-cli-halverse/tests/fixtures"
store_builder="$root/research/0075-halverse-plugin-the-voiceink-dictionary-store-and-the-plugin/fixture.py"
(cd ../sources && for command in terms ontology check; do
  "$cli" "$command" --json --glossary GLOSSARY.md --ontology ontology.md --dictation dictation.md \
    > "../cli/sources/$command.json" || [ "$command" = check ]
done)
for name in terms terms-de ontology check; do cp "$tests/expected/$name.json" "contract/$name.json"; done

# The scene: the nine fixtures under their real names, a fixture store, a home and a state root of its own. No call
# names a path outside it, and the environment's overrides are taken away.
scene="$(mktemp -d)"
trap 'rm -rf "$scene"' EXIT
cp "$tests/glossary.md" "$scene/GLOSSARY.md"
cp "$tests/ontology.md" "$scene/HALVERSE-ONTOLOGY.md"
cp "$tests/dictation.md" "$scene/DICTATION.md"
for tag in de nl pt-PT; do
  cp "$tests/glossary/$tag.md" "$scene/GLOSSARY.$tag.md"
  cp "$tests/ontology/$tag.md" "$scene/HALVERSE-ONTOLOGY.$tag.md"
done
python3 "$store_builder" "$scene/voiceink.store" > /dev/null
files=(--glossary GLOSSARY.md --ontology HALVERSE-ONTOLOGY.md --dictation DICTATION.md)
writing=(--state state --store voiceink.store --backups voiceink-backups)
mkdir -p term term-refused

# in_scene <program> <args>...: one run inside the scene.
in_scene() {
  (cd "$scene" && env -u HALVERSE_GLOSSARY -u HALVERSE_ONTOLOGY -u HALVERSE_DICTATION -u XDG_STATE_HOME \
    -u HAL2_CONFIG_DIR HOME="$scene/home" HAL2_HOME="$scene/home" HAL2_STATE_DIR="$scene/state" \
    HAL2_VOICEINK_APP_RUNNING=0 "$@")
}
# reads <file> <exit> <args>...: a reading call's answer; writes <file> <exit> <args>...: a writing call's (the
# document, where it has one, on stdin). The exit code must be the one named.
record() {
  local out="$here/$1" want="$2" got=0
  shift 2
  in_scene "$cli" "$@" --json > "$out" || got=$?
  [ "$got" = "$want" ] || { echo "make.sh: $* exited $got, not $want" >&2; exit 1; }
}
reads() { local out="$1" want="$2"; shift 2; record "$out" "$want" "$@" "${files[@]}"; }
writes() { local out="$1" want="$2"; shift 2; record "$out" "$want" "$@" "${files[@]}" "${writing[@]}"; }

reads term/term-check.json 0 term check lashing berth
writes term/term-add-dry.json 0 term add --from - --dry-run < documents/lashing.json
writes term/term-add.json 0 term add --from - < documents/lashing.json
writes term-refused/term-add.json 3 term add --from - < documents/lashing.json
writes term/term-change-dry.json 0 term change --from - --dry-run < documents/lashing-changed.json
writes term/term-change.json 0 term change --from - < documents/lashing-changed.json
writes term/term-retire-dry.json 0 term retire shipmaster --by pilot --dry-run
writes term/term-retire.json 0 term retire shipmaster --by pilot
reads term/term-short-list.json 0 term short list
writes term/term-short-set.json 0 term short set kn knot --spoken
writes term/term-short-rm.json 0 term short rm kn
writes term-refused/term-add-dry.json 3 term add --from - --dry-run < documents/refused.json
writes term-refused/term-change-dry.json 3 term change --from - --dry-run < documents/invalid.json
writes term-refused/term-retire-dry.json 3 term retire berth --dry-run
writes term-refused/term-short-set.json 3 term short set dock berth
writes term-refused/term-short-rm.json 3 term short rm zz
reads term/prompt.json 0 prompt
in_scene "$voiceink" export --out voiceink-import.json "${files[@]}" --json > term/export.json
