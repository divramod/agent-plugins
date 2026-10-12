#!/usr/bin/env bash
# shellcheck disable=SC2034,SC2154 # the globals fastlane.sh and plain-land.sh share
# Helpers fastlane.sh sources: the repository's paths, the conf, the fingerprint
# and the lock of a repository without hal2. Bash 3.2 (the Mac's stock bash).

die() { # die <exit> <message>
  echo "fastlane.sh: $2" >&2
  exit "$1"
}

need() { # need <tool>: exit 2 when it is missing
  command -v "$1" >/dev/null 2>&1 \
    || die 2 "$1 is missing -> bash $FASTLANE_HERE/install-prerequisites.sh"
}

# The worktree's top, its git common dir, the default branch and the main checkout.
repo_paths() {
  top=$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null) || die 1 "$dir is no git checkout"
  common=$(cd "$top" && cd "$(git rev-parse --git-common-dir)" && pwd)
  default=$(git -C "$top" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || echo origin/main)
  default=${default#origin/}
  main_checkout=$(git -C "$top" worktree list --porcelain | sed -n '1s/^worktree //p')
  branch=$(git -C "$top" symbolic-ref --quiet --short HEAD 2>/dev/null || true)
  worktree_script="$top/.hal/mtm-fastlane-worktree.sh"
  main_script=.hal/mtm-fastlane-main.sh
  conf="$top/.hal/mtm-fastlane.conf"
  state="$common/mtm-fastlane"
}

conf_get() { # conf_get <key> <default>: KEY=value lines, never sourced
  local value=""
  if [ -f "$conf" ]; then
    value=$(sed -n "s/^$1=//p" "$conf" | tail -1 | sed 's/^"\(.*\)"$/\1/')
  fi
  if [ -n "$value" ]; then echo "$value"; else echo "$2"; fi
}

sha256() {
  if command -v shasum >/dev/null 2>&1; then shasum -a 256 | cut -d' ' -f1; else sha256sum | cut -d' ' -f1; fi
}

# The fingerprint of the inputs /mtm-fastlane configure read (FINGERPRINT_INPUTS,
# git pathspecs, globs too): the blob ids and paths of the tracked files among them.
fingerprint() {
  local inputs
  inputs=$(conf_get FINGERPRINT_INPUTS "")
  [ -n "$inputs" ] || { echo none; return; }
  # shellcheck disable=SC2086 # the pathspecs are words
  (cd "$top" && set -f && git ls-files -s -- $inputs) | sha256
}

# Whether this run lands through hal2-cli-git: FASTLANE_PLAIN=1 forces plain git,
# HAL2_CLI_GIT names the binary (default hal2-cli-git on PATH).
hal2_bin() {
  [ "${FASTLANE_PLAIN:-0}" = 1 ] && return 1
  local bin=${HAL2_CLI_GIT:-hal2-cli-git}
  command -v "$bin" >/dev/null 2>&1 || return 1
  "$bin" --help 2>&1 | grep -q -- '--local' || return 1
  echo "$bin"
}

minutes() { # minutes <60m|2h|90>: whole minutes, exit 64 otherwise
  local n=${1%[mh]}
  case "$n" in
    ''|*[!0-9]*) die 64 "--max-wait takes minutes (60m, 2h), not '$1'" ;;
  esac
  case "$1" in
    *h) echo $(( n * 60 )) ;;
    *) echo "$n" ;;
  esac
}

# The lock of a repository without hal2: a directory in the git common dir
# (macOS has no flock), owned by a worktree, so the rerun of the same worktree
# keeps it and another one waits.
lock_dir() { echo "$common/mtm-fastlane.lock"; }

lock_take() { # lock_take <max-wait minutes>
  local lock owner waited=0
  lock=$(lock_dir)
  while ! mkdir "$lock" 2>/dev/null; do
    owner=$(cat "$lock/worktree" 2>/dev/null || true)
    [ "$owner" = "$top" ] && { echo "reserved: $top (kept)"; return 0; }
    [ "$waited" -ge $(( $1 * 60 )) ] && die 7 "the lock is still held by $owner after $1 min: tell the user"
    [ "$waited" = 0 ] && echo "waiting for the lock held by $owner"
    sleep "${FASTLANE_POLL:-5}"
    waited=$(( waited + ${FASTLANE_POLL:-5} ))
  done
  echo "$top" > "$lock/worktree"
  echo "$$" > "$lock/pid"
  echo "reserved: $top"
}

lock_drop() { # lock_drop [--force]
  local lock owner
  lock=$(lock_dir)
  [ -d "$lock" ] || { echo "released: nothing held"; return 0; }
  owner=$(cat "$lock/worktree" 2>/dev/null || true)
  if [ "$owner" != "$top" ] && [ "${1:-}" != --force ]; then
    die 1 "the lock is held by $owner, not this worktree (release --force takes it away)"
  fi
  rm -rf "$lock"
  echo "released: $owner"
}
