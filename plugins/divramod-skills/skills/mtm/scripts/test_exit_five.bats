#!/usr/bin/env bats
# Exit 5 split (plan 0017): `interrupted` reruns at once, `stopped`/`cancelled` are report-and-stop,
# in mtm's SKILL.md, mtm's references/ci.md and the plan skill's "Land the plan".

setup() {
  root="${MTM_SKILLS_ROOT:-$BATS_TEST_DIRNAME/../..}"
  skill="$root/mtm/SKILL.md"
  ci="$root/mtm/references/ci.md"
  plan="$root/plan/SKILL.md"
}

rows() { grep -E '^\| 5 \|' "$1"; }

check_rows() {
  local f="$1" want="$2" n=0 row
  while IFS= read -r row; do
    if [[ "$row" == *'`interrupted`'* ]]; then
      n=$((n + 1))
      [[ "$row" == *rerun* ]] || { echo "no rerun: $row"; return 1; }
      [[ "$row" != *stopped* && "$row" != *cancelled* ]] || { echo "names stop: $row"; return 1; }
    elif [[ "$row" == *'`stopped`'* || "$row" == *'`cancelled`'* ]]; then
      [[ "$row" == *"never rerun"* ]] || { echo "no never rerun: $row"; return 1; }
      [[ "$row" != *interrupted* ]] || { echo "names interrupted: $row"; return 1; }
    else
      echo "unknown exit-5 row: $row"; return 1
    fi
  done < <(rows "$f")
  [ "$n" -eq "$want" ] || { echo "interrupted rows: $n, want $want"; return 1; }
}

@test "mtm SKILL.md: two interrupted rows rerun, stopped/cancelled rows never rerun" {
  check_rows "$skill" 2
}

@test "mtm SKILL.md: both tables have a stopped/cancelled row" {
  [ "$(rows "$skill" | grep -c -E '`(stopped|cancelled)`')" -eq 2 ]
}

@test "mtm ci.md: one interrupted row reruns, stopped/cancelled row never reruns" {
  check_rows "$ci" 1
}

@test "mtm intro: never again after exit 5 excepts interrupted" {
  p="$(tr '\n' ' ' < "$skill" | grep -o 'never again after it ended with exit 5.\{0,250\}')"
  [[ "$p" == *'`interrupted`'* ]]
  [[ "$p" == *rerun* ]]
}

@test "plan skill: Land the plan counts only stopped and cancelled as the user's exit 5" {
  p="$(tr '\n' ' ' < "$plan" | grep -o 'never again after a landing ended with exit 5[^:]*:')"
  [ -n "$p" ]
  [[ "$p" == *stopped* && "$p" == *cancelled* ]]
  [[ "$p" == *'`interrupted`'* ]]
  [[ "$p" == *rerun* ]]
  # interrupted is not named inside the "ended ... by the user" part
  user="${p%%by the user*}"
  [[ "$user" != *interrupted* ]]
}
