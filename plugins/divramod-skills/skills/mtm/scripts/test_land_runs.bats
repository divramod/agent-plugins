#!/usr/bin/env bats
# land-runs.sh: no reserve or candidate push while a merge-to-main.yml or land.yml run is unfinished.

setup() {
  here="$BATS_TEST_DIRNAME"
  tmp="$(mktemp -d)"
  mkdir -p "$tmp/bin"
  # A fake gh: per call it prints the next line of the asked workflow's runs file (consumed; `|` separates runs),
  # applying no filter: $tmp/runs for land.yml, $tmp/runs-new for merge-to-main.yml. A workflow file named in
  # $tmp/unknown gets GitHub's 404 (gh 2.92's words), one named in $tmp/broken another failure; $tmp/noise makes
  # every call warn on stderr.
  cat > "$tmp/bin/gh" <<EOF
#!/usr/bin/env bash
echo "\$*" >> "$tmp/calls"
[ -f "$tmp/fail" ] && exit 1
workflow=""
while [ \$# -gt 0 ]; do
  if [ "\$1" = --workflow ]; then workflow="\$2"; fi
  shift
done
[ -f "$tmp/noise" ] && echo "warning: gh is out of date" >&2
if grep -qx "\$workflow" "$tmp/unknown" 2>/dev/null; then
  echo "HTTP 404: workflow \$workflow not found on the default branch (https://api.github.com/repos/o/r/actions/workflows/\$workflow)" >&2
  exit 1
fi
if grep -qx "\$workflow" "$tmp/broken" 2>/dev/null; then
  echo "HTTP 502: Bad Gateway (https://api.github.com/repos/o/r/actions/workflows/\$workflow)" >&2
  exit 1
fi
case "\$workflow" in
  land.yml) runs="$tmp/runs" ;;
  merge-to-main.yml) runs="$tmp/runs-new" ;;
  *) exit 0 ;;
esac
if [ -s "\$runs" ]; then head -n 1 "\$runs" | tr '|' '\n'; sed -i.bak 1d "\$runs"; fi
exit 0
EOF
  chmod +x "$tmp/bin/gh"
  : > "$tmp/runs"
  : > "$tmp/runs-new"
  export PATH="$tmp/bin:$PATH"
}

teardown() { rm -rf "$tmp"; }

# A PATH directory with every tool of /usr/bin and /bin except gh: a Linux runner has gh in /usr/bin itself.
path_without_gh() {
  local dir=$1 d f
  mkdir -p "$dir"
  for d in /usr/bin /bin; do
    for f in "$d"/*; do
      [ "${f##*/}" = gh ] || [ -e "$dir/${f##*/}" ] || ln -s "$f" "$dir/${f##*/}"
    done
  done
}

@test "no unfinished run: go at once, both workflow files asked" {
  run bash "$here/land-runs.sh" --once "$tmp"
  [ "$status" -eq 0 ]
  [ -z "$output" ]
  grep -q -- "--workflow land.yml" "$tmp/calls"
  grep -q -- "--workflow merge-to-main.yml" "$tmp/calls"
  [ "$(wc -l < "$tmp/calls")" -eq 2 ]
  [ "$(grep -c 'select(.status != "completed")' "$tmp/calls")" -eq 2 ]
}

@test "--once lists an unfinished run and exits 6" {
  echo "68 land/04 queued" > "$tmp/runs"
  run bash "$here/land-runs.sh" --once "$tmp"
  [ "$status" -eq 6 ]
  [[ "$output" == *"68 land/04 queued"* ]]
}

@test "without --once it waits until the runs are done" {
  printf '%s\n' "68 land/04 in_progress|69 land/02 queued" "68 land/04 queued" > "$tmp/runs"
  run bash "$here/land-runs.sh" --interval 0 "$tmp"
  [ "$status" -eq 0 ]
  [ "$(grep -c -- "--workflow land.yml" "$tmp/calls")" -eq 3 ]
  [ "$(grep -c -- "--workflow merge-to-main.yml" "$tmp/calls")" -eq 3 ]
  [[ "$output" == *"68 land/04 in_progress, 69 land/02 queued"* ]]
}

@test "an unfinished run of merge-to-main.yml is waited for too" {
  printf '%s\n' "70 land/05 in_progress" "70 land/05 queued" > "$tmp/runs-new"
  run bash "$here/land-runs.sh" --once "$tmp"
  [ "$status" -eq 6 ]
  [[ "$output" == *"land runs unfinished: 70 land/05 in_progress"* ]]
  run bash "$here/land-runs.sh" --interval 0 "$tmp"
  [ "$status" -eq 0 ]
  [[ "$output" == *"70 land/05 queued"* ]]
}

@test "unfinished runs of both workflow files are listed together" {
  echo "68 land/04 queued" > "$tmp/runs"
  echo "70 land/05 in_progress|71 land/06 queued" > "$tmp/runs-new"
  run bash "$here/land-runs.sh" --once "$tmp"
  [ "$status" -eq 6 ]
  [ "$output" = "land runs unfinished: 70 land/05 in_progress, 71 land/06 queued, 68 land/04 queued" ]
}

@test "before the rename GitHub does not know merge-to-main.yml: it has no runs, land.yml's count" {
  echo merge-to-main.yml > "$tmp/unknown"
  run bash "$here/land-runs.sh" --once "$tmp"
  [ "$status" -eq 0 ]
  [ -z "$output" ]
  echo "68 land/04 queued" > "$tmp/runs"
  run bash "$here/land-runs.sh" --once "$tmp"
  [ "$status" -eq 6 ]
  [ "$output" = "land runs unfinished: 68 land/04 queued" ]
}

@test "after the rename GitHub does not know land.yml: it has no runs, merge-to-main.yml's count" {
  echo land.yml > "$tmp/unknown"
  run bash "$here/land-runs.sh" --once "$tmp"
  [ "$status" -eq 0 ]
  [ -z "$output" ]
  echo "70 land/05 in_progress" > "$tmp/runs-new"
  run bash "$here/land-runs.sh" --once "$tmp"
  [ "$status" -eq 6 ]
  [ "$output" = "land runs unfinished: 70 land/05 in_progress" ]
}

@test "an older gh's words for a file GitHub does not know count the same" {
  cat > "$tmp/bin/gh" <<'EOF'
#!/usr/bin/env bash
case "$*" in *merge-to-main.yml*) echo "could not find any workflows named merge-to-main.yml" >&2; exit 1 ;; esac
echo "68 land/04 queued"
EOF
  run bash "$here/land-runs.sh" --once "$tmp"
  [ "$status" -eq 6 ]
  [ "$output" = "land runs unfinished: 68 land/04 queued" ]
}

@test "GitHub knows neither workflow file: nothing is known, no go" {
  printf '%s\n' merge-to-main.yml land.yml > "$tmp/unknown"
  run bash "$here/land-runs.sh" --once "$tmp"
  [ "$status" -eq 1 ]
  [[ "$output" == *"knows neither merge-to-main.yml nor land.yml"* ]]
  [[ "$output" == *"do not push"* ]]
}

@test "a failing gh is no go" {
  touch "$tmp/fail"
  run bash "$here/land-runs.sh" --once "$tmp"
  [ "$status" -eq 1 ]
  [[ "$output" == *"do not push"* ]]
}

@test "one workflow file's list failing for another reason is no go, whatever the other says" {
  echo merge-to-main.yml > "$tmp/broken"
  run bash "$here/land-runs.sh" --once "$tmp"
  [ "$status" -eq 1 ]
  [[ "$output" == *"HTTP 502"* ]]
  [[ "$output" == *"do not push"* ]]
  echo land.yml > "$tmp/broken"
  echo "70 land/05 in_progress" > "$tmp/runs-new"
  run bash "$here/land-runs.sh" --once "$tmp"
  [ "$status" -eq 1 ]
  [[ "$output" == *"do not push"* ]]
}

@test "what gh warns on stderr is no run" {
  touch "$tmp/noise"
  run bash "$here/land-runs.sh" --once "$tmp"
  [ "$status" -eq 0 ]
  [ -z "$output" ]
}

@test "a missing gh exits 2 naming the install" {
  rm "$tmp/bin/gh"
  path_without_gh "$tmp/nogh"
  PATH="$tmp/bin:$tmp/nogh" run bash "$here/land-runs.sh" --once "$tmp"
  [ "$status" -eq 2 ]
  [[ "$output" == *"brew install gh"* ]]
}

@test "a run stuck past --max-wait exits 7 for the farmer" {
  printf '%s\n' "70 land/05 queued" "70 land/05 queued" "70 land/05 queued" > "$tmp/runs"
  run bash "$here/land-runs.sh" --interval 0 --max-wait 0 "$tmp"
  [ "$status" -eq 7 ]
  [[ "$output" == *"tell the farmer"* ]]
}

@test "a --max-wait that is no whole number exits 2" {
  run bash "$here/land-runs.sh" --max-wait 1h "$tmp"
  [ "$status" -eq 2 ]
  [[ "$output" == *"whole numbers, not '1h'"* ]]
}
