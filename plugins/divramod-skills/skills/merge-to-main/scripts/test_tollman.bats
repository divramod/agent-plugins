#!/usr/bin/env bats
# enforces .adr/tollman.md
# tollman.sh: `yes` only on a farm with a working tollman (hal2 plan 0294, D13): its worktree, its timer
# loaded in mode `timer`, a round in the last 30 minutes, a hal2-cli-git that knows the hitch. Every doubt is `no`.
# The tollman skill's own `tollman.py status` is run over a scratch HOME; launchctl, systemctl and
# hal2-cli-git are fakes on PATH: no real timer, queue or session is read.

load test_helper

# The template (test_helper.bash): a scratch HOME, origin, the main checkout a/demo with its worktree 07 in the
# HOME's fields, and the fakes on PATH.
build() {
  mkdir -p "$tmp/home" "$tmp/bin" "$tmp/a"
  git init -q --bare -b main "$tmp/demo.git"
  git clone -q "$tmp/demo.git" "$tmp/a/demo" 2>/dev/null
  git -C "$tmp/a/demo" -c user.name=t -c user.email=t@t commit -q --allow-empty -m init
  git -C "$tmp/a/demo" push -q origin HEAD:main
  git -C "$tmp/a/demo" worktree add -q -b 07 "$tmp/home/.hal/git/worktree/demo/07"
  # The timer's probe: loaded while $tmp/loaded exists (macOS: launchctl print, Linux: systemctl is-active).
  for tool in launchctl systemctl; do
    printf '#!/usr/bin/env bash\n[ -e "%s/loaded" ]\n' "$tmp" > "$tmp/bin/$tool"
  done
  cli "  worktree queue ready      report a worktree's pushed work ready"
  chmod +x "$tmp/bin/"*
}

setup_file() {
  export GIT_CONFIG_GLOBAL=/dev/null
  tmp=$(fixture_dir)
  fixture_build build
}

setup() {
  here="$BATS_TEST_DIRNAME"
  tmp=$(fixture_dir)
  fixture_copy
  export HOME="$tmp/home" ERR="$tmp/err"
  unset FARMER_DIR
  export PATH="$tmp/bin:$PATH" GIT_CONFIG_GLOBAL=/dev/null
  main="$tmp/a/demo"
  slots="$HOME/.hal/git/worktree/demo"
  field="$slots/tollman-demo"
  state="$field/roles/tollman"
}

teardown() { fixture_drop; }

cli() { # <a line of its help>...: the fake hal2-cli-git
  printf '%s\n' "$@" > "$tmp/help"
  printf '#!/usr/bin/env bash\n[ "$1" = --help ] && cat "%s/help"\n' "$tmp" > "$tmp/bin/hal2-cli-git"
  chmod +x "$tmp/bin/hal2-cli-git"
}

ago() { # <seconds>: that long ago, as the round frame writes its times (local, no zone)
  python3 -c 'import datetime as d, sys
print((d.datetime.now() - d.timedelta(seconds=int(sys.argv[1]))).isoformat(timespec="seconds"))' "$1"
}

tollman() { # [<seconds since its last round>]: a working tollman (default: a round a minute ago)
  git -C "$main" worktree add -q -b tollman-demo "$field"
  mkdir -p "$state"
  echo timer > "$state/mode"
  echo '{"cron": "2-59/5 * * * *", "label": "local.tollman.demo"}' > "$state/timer.json"
  echo "{\"at\": \"$(ago "${1:-60}")\", \"name\": \"trains\"}" > "$state/runs.jsonl"
  touch "$tmp/loaded"
}

ask() { # [<dir>]: the answer in $output, the reason in $ERR
  run bash -c 'bash "$0" "$@" 2>"$ERR"' "$here/tollman.sh" "$@"
}

@test "a farm without the tollman's worktree: no" {
  ask "$slots/07"
  [ "$status" -eq 0 ]
  [ "$output" = no ]
  grep -q "no tollman here: no worktree .*tollman-demo" "$ERR"
}

@test "a working tollman: yes, with nothing on stderr" {
  tollman
  ask "$slots/07"
  [ "$status" -eq 0 ]
  [ "$output" = yes ]
  [ ! -s "$ERR" ]
}

@test "the current directory is the default, a folder inside the worktree counts" {
  tollman
  mkdir -p "$slots/07/code"
  cd "$slots/07/code"
  ask
  [ "$output" = yes ]
}

@test "the main checkout asks for the same farm" {
  tollman
  ask "$main"
  [ "$output" = yes ]
}

@test "the tollman's own worktree lands itself: no" {
  tollman
  ask "$field"
  [ "$output" = no ]
  grep -q "the own worktree of the tollman: it lands itself" "$ERR"
}

@test "a timer that is not loaded: no" {
  tollman
  rm "$tmp/loaded"
  ask "$slots/07"
  [ "$output" = no ]
  grep -q "the timer local.tollman.demo of the tollman is not loaded" "$ERR"
}

@test "the mode claude (no timer runs the rounds): no" {
  tollman
  echo claude > "$state/mode"
  ask "$slots/07"
  [ "$output" = no ]
  grep -q "the mode of the tollman is claude, not timer" "$ERR"
}

@test "a tollman that never ran a round: no" {
  tollman
  rm "$state/runs.jsonl"
  ask "$slots/07"
  [ "$output" = no ]
  grep -q "has not run a round yet" "$ERR"
}

@test "a last round 29 minutes ago: yes; 31 minutes ago: no" {
  tollman 1740
  ask "$slots/07"
  [ "$output" = yes ]
  echo "{\"at\": \"$(ago 1860)\", \"name\": \"trains\"}" > "$state/runs.jsonl"
  ask "$slots/07"
  [ "$output" = no ]
  grep -q "last round of the tollman is 18[0-9][0-9] s old (limit 1800 s)" "$ERR"
}

@test "the newest round counts: a tick's log entry after an old run record" {
  tollman 7200
  echo "{\"at\": \"$(ago 120)\", \"kind\": \"moves\", \"by\": \"tick\"}" > "$state/log.jsonl"
  ask "$slots/07"
  [ "$output" = yes ]
}

@test "a last round in the future is a doubt: no" {
  tollman -600
  ask "$slots/07"
  [ "$output" = no ]
  grep -q "last round of the tollman is -[0-9]* s old" "$ERR"
}

@test "a state the status cannot read: no" {
  tollman
  echo 'not json' > "$state/runs.jsonl"
  ask "$slots/07"
  [ "$status" -eq 0 ]
  [ "$output" = no ]
  grep -q "tollman.py status failed" "$ERR"
}

@test "a hal2-cli-git that does not know the hitch: no" {
  tollman
  cli "  worktree queue order      the user's priority list"
  ask "$slots/07"
  [ "$output" = no ]
  grep -q 'does not know `worktree queue ready`' "$ERR"
}

@test "a hal2-cli-git that fails: no" {
  tollman
  printf '#!/usr/bin/env bash\nexit 1\n' > "$tmp/bin/hal2-cli-git"
  ask "$slots/07"
  [ "$output" = no ]
}

@test "no git checkout: no" {
  mkdir "$tmp/plain"
  ask "$tmp/plain"
  [ "$status" -eq 0 ]
  [ "$output" = no ]
  grep -q "is no git checkout" "$ERR"
}

@test "without the tollman skill beside mtm: no" {
  tollman
  mkdir -p "$tmp/skills/merge-to-main/scripts"
  cp "$here/tollman.sh" "$tmp/skills/merge-to-main/scripts/"
  run bash -c 'bash "$0" "$@" 2>"$ERR"' "$tmp/skills/merge-to-main/scripts/tollman.sh" "$slots/07"
  [ "$output" = no ]
  grep -q "tollman skill is not installed beside mtm" "$ERR"
}

@test "in category folders the sibling tollman skill is found: yes (plan 0360 D20)" {
  tollman
  unit="$tmp/unit"
  mkdir -p "$unit/skills" "$unit/.claude-plugin"
  cp -R "$here/../../../../scripts" "$unit/scripts"
  cp -R "$here/../.." "$unit/skills/actions"  # the actions in one category, the roles in another
  cp -R "$here/../../../roles" "$unit/skills/roles"
  run bash -c 'bash "$0" "$@" 2>"$ERR"' "$unit/skills/actions/merge-to-main/scripts/tollman.sh" "$slots/07"
  [ "$status" -eq 0 ]
  [ "$output" = yes ]
  [ ! -s "$ERR" ]
  rm -rf "$unit/skills/roles/tollman"
  run bash -c 'bash "$0" "$@" 2>"$ERR"' "$unit/skills/actions/merge-to-main/scripts/tollman.sh" "$slots/07"
  [ "$output" = no ]
  grep -q "tollman skill is not installed beside mtm" "$ERR"
}
