#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# The facts /mtm-fastlane configure judges from, as JSON on stdout, for the
# repository of <dir> (default .):
#   scan.sh [<dir>]
# host (os, arch), default branch, provider; workflows (file, land: whether it runs
# on land refs, jobs with runs_on, uses and run lines; jobs need yq, without it
# only their names and runs-on); change_maps; units (code/<lang>/{apps,libs,scripts}/<name>
# with manifests, package.json scripts, tests); root_manifests; lockfiles; utils;
# deliveries (scripts named deliver, install, release or ship); fingerprint_inputs
# (the pathspecs whose change makes the scripts stale).
# Exit 0, 2 a missing tool.
set -euo pipefail
FASTLANE_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=fastlane-lib.sh
. "$FASTLANE_HERE/fastlane-lib.sh"
dir="${1:-.}"
need git
need jq
repo_paths
cd "$top"
# shellcheck source=ci-providers.sh
. "$FASTLANE_HERE/ci-providers.sh"

lines_json() { jq -R . | jq -sc 'map(select(. != ""))'; }
existing() { local p; for p in "$@"; do [ -e "$p" ] && echo "$p"; done; return 0; }

workflow_jobs() { # <file>: [{name, runs_on, uses, run}]
  if command -v yq >/dev/null 2>&1 && [ "${FASTLANE_NO_YQ:-0}" != 1 ]; then
    yq -o=json '.' "$1" | jq -c '.jobs // {} | to_entries | map({name: .key, runs_on: (.value."runs-on" // null),
      uses: (.value.uses // null), run: [(.value.steps // [])[] | select(has("run")) | .run]})'
  else
    awk '/^jobs:/ {in_jobs = 1; next} in_jobs && /^[^ #]/ {in_jobs = 0}
         in_jobs && /^  [A-Za-z0-9_-]+:[ ]*$/ {sub(/^  /, ""); sub(/:.*/, ""); job = $0; print job "\t"}
         in_jobs && job != "" && /^    runs-on:/ {sub(/^    runs-on:[ ]*/, ""); print job "\t" $0}' "$1" \
      | jq -R 'split("\t")' | jq -sc 'reduce .[] as [$n, $r] ([]; if $r == "" then . + [{name: $n, runs_on: null}]
          else map(if .name == $n then .runs_on = $r else . end) end)'
  fi
}

workflows() {
  local f land
  for f in .github/workflows/*.yml .github/workflows/*.yaml; do
    [ -f "$f" ] || continue
    land=false
    grep -q "land/" "$f" && land=true
    jq -nc --arg file "$f" --argjson land "$land" --argjson jobs "$(workflow_jobs "$f")" \
      '{file: $file, land: $land, jobs: $jobs}'
  done
  if [ -f .gitlab-ci.yml ]; then
    jq -nc '{file: ".gitlab-ci.yml", land: true, jobs: []}'
  fi
}

unit() { # <dir>: one unit's facts
  local d=$1 manifests tests scripts="{}"
  manifests=$(cd "$d" && existing Cargo.toml package.json pyproject.toml go.mod Package.swift ./*.rockspec \
    pubspec.yaml main.py main.sh main.ts | sed 's|^\./||' | lines_json)
  tests=$(cd "$d" && existing tests test spec test_* ./*.bats ./*_test.* | sed 's|^\./||' | sort -u | lines_json)
  [ -f "$d/package.json" ] && scripts=$(jq -c '.scripts // {}' "$d/package.json")
  jq -nc --arg path "$d" --argjson manifests "$manifests" --argjson tests "$tests" --argjson scripts "$scripts" \
    '($path | split("/")) as $p | {path: $path, lang: $p[1], kind: $p[2], name: $p[3],
      manifests: $manifests, tests: $tests, package_scripts: $scripts}'
}

units() {
  local d
  for d in code/*/apps/* code/*/libs/* code/*/scripts/*; do
    [ -d "$d" ] && unit "$d"
  done
  return 0
}

host=$(jq -nc --arg os "$(uname -s)" --arg arch "$(uname -m)" '{os: $os, arch: $arch}')
change_maps=$(existing .github/hal2-changes.toml .github/labeler.yml .github/CODEOWNERS | lines_json)
root_manifests=$(existing Cargo.toml package.json pyproject.toml go.mod Package.swift Makefile justfile Taskfile.yml \
  code/*/Cargo.toml code/*/package.json | lines_json)
lockfiles=$(git ls-files -- '*Cargo.lock' '*bun.lock' '*bun.lockb' '*package-lock.json' '*pnpm-lock.yaml' \
  '*yarn.lock' '*uv.lock' '*poetry.lock' '*go.sum' '*Package.resolved' | lines_json)
utils=$(existing utils/* | lines_json)
deliveries=$(git ls-files | { grep -E '(^|/)(deliver|install|release|ship)[^/]*/(main\.[a-z]+)$|(^|/)(deliver|install|release|ship)[^/]*\.(sh|py|ts)$' || true; } \
  | { grep -v -E '(^|/)test_' || true; } | lines_json)
inputs=$(existing .github/workflows .gitlab-ci.yml .github/hal2-changes.toml \
  | sed 's|^\.github/workflows$|.github/workflows/*|' | lines_json)

jq -n --argjson host "$host" --arg top "$top" --arg default "$default" --arg provider "$(provider_of)" \
  --argjson workflows "$(workflows | jq -sc .)" --argjson change_maps "$change_maps" \
  --argjson units "$(units | jq -sc .)" --argjson root_manifests "$root_manifests" \
  --argjson lockfiles "$lockfiles" --argjson utils "$utils" --argjson deliveries "$deliveries" \
  --argjson inputs "$inputs" \
  '{repo: $top, host: $host, default: $default, provider: $provider, workflows: $workflows,
    land_workflows: [$workflows[] | select(.land) | .file], change_maps: $change_maps, units: $units,
    root_manifests: $root_manifests, lockfiles: $lockfiles, utils: $utils, deliveries: $deliveries,
    fingerprint_inputs: $inputs}'
