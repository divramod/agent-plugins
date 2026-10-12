#!/usr/bin/env bats
# land-runs.sh: no reserve or candidate push while a land.yml run is unfinished.

setup() {
  here="$BATS_TEST_DIRNAME"
  tmp="$(mktemp -d)"
  mkdir -p "$tmp/bin"
  # A fake gh: prints the lines of $tmp/runs (one per call, consumed), applying no filter.
  cat > "$tmp/bin/gh" <<EOF
#!/usr/bin/env bash
echo "\$*" >> "$tmp/calls"
[ -f "$tmp/fail" ] && exit 1
if [ -s "$tmp/runs" ]; then head -n 1 "$tmp/runs" | tr '|' '\n'; sed -i.bak 1d "$tmp/runs"; fi
exit 0
EOF
  chmod +x "$tmp/bin/gh"
  : > "$tmp/runs"
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

@test "no unfinished run: go at once" {
  run bash "$here/land-runs.sh" --once "$tmp"
  [ "$status" -eq 0 ]
  [ -z "$output" ]
  grep -q -- "--workflow land.yml" "$tmp/calls"
  grep -q 'select(.status != "completed")' "$tmp/calls"
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
  [ "$(wc -l < "$tmp/calls")" -eq 3 ]
  [[ "$output" == *"68 land/04 in_progress, 69 land/02 queued"* ]]
}

@test "a failing gh is no go" {
  touch "$tmp/fail"
  run bash "$here/land-runs.sh" --once "$tmp"
  [ "$status" -eq 1 ]
  [[ "$output" == *"do not push"* ]]
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
