#!/usr/bin/env bats
# wagon-master.sh: `yes` only on a farm with a working wagon master (hal2 plan 0294, D13): its worktree, its timer
# loaded in mode `timer`, a round in the last 30 minutes, a hal2-cli-git that knows the hitch. Every doubt is `no`.
# The wagon-master skill's own `wagon_master.py status` is run over a scratch HOME; launchctl, systemctl and
# hal2-cli-git are fakes on PATH: no real timer, queue or session is read.

setup() {
  here="$BATS_TEST_DIRNAME"
  tmp="$(cd "$(mktemp -d)" && pwd -P)"
  export HOME="$tmp/home" ERR="$tmp/err"
  unset FARMER_DIR
  mkdir -p "$HOME" "$tmp/bin" "$tmp/a"
  export PATH="$tmp/bin:$PATH" GIT_CONFIG_GLOBAL=/dev/null
  git init -q --bare -b main "$tmp/demo.git"
  git clone -q "$tmp/demo.git" "$tmp/a/demo" 2>/dev/null
  main="$tmp/a/demo"
  git -C "$main" -c user.name=t -c user.email=t@t commit -q --allow-empty -m init
  git -C "$main" push -q origin HEAD:main
  slots="$HOME/.hal/git/worktree/demo"
  git -C "$main" worktree add -q -b 07 "$slots/07"
  field="$slots/wagon-master-demo"
  state="$field/roles/wagon-master"
  # The timer's probe: loaded while $tmp/loaded exists (macOS: launchctl print, Linux: systemctl is-active).
  for tool in launchctl systemctl; do
    printf '#!/usr/bin/env bash\n[ -e "%s/loaded" ]\n' "$tmp" > "$tmp/bin/$tool"
  done
  cli "  worktree queue ready      report a worktree's pushed work ready"
  chmod +x "$tmp/bin/"*
}

teardown() { rm -rf "$tmp"; }

cli() { # <a line of its help>...: the fake hal2-cli-git
  printf '%s\n' "$@" > "$tmp/help"
  printf '#!/usr/bin/env bash\n[ "$1" = --help ] && cat "%s/help"\n' "$tmp" > "$tmp/bin/hal2-cli-git"
  chmod +x "$tmp/bin/hal2-cli-git"
}

ago() { # <seconds>: that long ago, as the round frame writes its times (local, no zone)
  python3 -c 'import datetime as d, sys
print((d.datetime.now() - d.timedelta(seconds=int(sys.argv[1]))).isoformat(timespec="seconds"))' "$1"
}

wagon_master() { # [<seconds since its last round>]: a working wagon master (default: a round a minute ago)
  git -C "$main" worktree add -q -b wagon-master-demo "$field"
  mkdir -p "$state"
  echo timer > "$state/mode"
  echo '{"cron": "2-59/5 * * * *", "label": "local.wagon-master.demo"}' > "$state/timer.json"
  echo "{\"at\": \"$(ago "${1:-60}")\", \"name\": \"trains\"}" > "$state/runs.jsonl"
  touch "$tmp/loaded"
}

ask() { # [<dir>]: the answer in $output, the reason in $ERR
  run bash -c 'bash "$0" "$@" 2>"$ERR"' "$here/wagon-master.sh" "$@"
}

@test "a farm without the wagon master's worktree: no" {
  ask "$slots/07"
  [ "$status" -eq 0 ]
  [ "$output" = no ]
  grep -q "no wagon master here: no worktree .*wagon-master-demo" "$ERR"
}

@test "a working wagon master: yes, with nothing on stderr" {
  wagon_master
  ask "$slots/07"
  [ "$status" -eq 0 ]
  [ "$output" = yes ]
  [ ! -s "$ERR" ]
}

@test "the current directory is the default, a folder inside the worktree counts" {
  wagon_master
  mkdir -p "$slots/07/code"
  cd "$slots/07/code"
  ask
  [ "$output" = yes ]
}

@test "the main checkout asks for the same farm" {
  wagon_master
  ask "$main"
  [ "$output" = yes ]
}

@test "the wagon master's own worktree lands itself: no" {
  wagon_master
  ask "$field"
  [ "$output" = no ]
  grep -q "the own worktree of the wagon master: it lands itself" "$ERR"
}

@test "a timer that is not loaded: no" {
  wagon_master
  rm "$tmp/loaded"
  ask "$slots/07"
  [ "$output" = no ]
  grep -q "the timer local.wagon-master.demo of the wagon master is not loaded" "$ERR"
}

@test "the mode claude (no timer runs the rounds): no" {
  wagon_master
  echo claude > "$state/mode"
  ask "$slots/07"
  [ "$output" = no ]
  grep -q "the mode of the wagon master is claude, not timer" "$ERR"
}

@test "a wagon master that never ran a round: no" {
  wagon_master
  rm "$state/runs.jsonl"
  ask "$slots/07"
  [ "$output" = no ]
  grep -q "has not run a round yet" "$ERR"
}

@test "a last round 29 minutes ago: yes; 31 minutes ago: no" {
  wagon_master 1740
  ask "$slots/07"
  [ "$output" = yes ]
  echo "{\"at\": \"$(ago 1860)\", \"name\": \"trains\"}" > "$state/runs.jsonl"
  ask "$slots/07"
  [ "$output" = no ]
  grep -q "last round of the wagon master is 18[0-9][0-9] s old (limit 1800 s)" "$ERR"
}

@test "the newest round counts: a tick's log entry after an old run record" {
  wagon_master 7200
  echo "{\"at\": \"$(ago 120)\", \"kind\": \"moves\", \"by\": \"tick\"}" > "$state/log.jsonl"
  ask "$slots/07"
  [ "$output" = yes ]
}

@test "a last round in the future is a doubt: no" {
  wagon_master -600
  ask "$slots/07"
  [ "$output" = no ]
  grep -q "last round of the wagon master is -[0-9]* s old" "$ERR"
}

@test "a state the status cannot read: no" {
  wagon_master
  echo 'not json' > "$state/runs.jsonl"
  ask "$slots/07"
  [ "$status" -eq 0 ]
  [ "$output" = no ]
  grep -q "wagon_master.py status failed" "$ERR"
}

@test "a hal2-cli-git that does not know the hitch: no" {
  wagon_master
  cli "  worktree queue order      the user's priority list"
  ask "$slots/07"
  [ "$output" = no ]
  grep -q 'does not know `worktree queue ready`' "$ERR"
}

@test "a hal2-cli-git that fails: no" {
  wagon_master
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

@test "without the wagon-master skill beside mtm: no" {
  wagon_master
  mkdir -p "$tmp/skills/mtm/scripts"
  cp "$here/wagon-master.sh" "$tmp/skills/mtm/scripts/"
  run bash -c 'bash "$0" "$@" 2>"$ERR"' "$tmp/skills/mtm/scripts/wagon-master.sh" "$slots/07"
  [ "$output" = no ]
  grep -q "wagon-master skill is not installed beside mtm" "$ERR"
}
