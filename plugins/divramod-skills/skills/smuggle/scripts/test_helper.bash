# shellcheck shell=bash disable=SC2154 # $tmp is the caller's (fixture_dir)
# The bats files' shared fixture: a scratch tree built once per file (setup_file) and copied for each test (setup),
# so no test pays for git init, commits, pushes and worktrees of its own. Both live in the file's own
# $BATS_FILE_TMPDIR: parallel bats runs never share a path.
#
# The copy lands at the path the template was built at ($tmp, the same for every test of the file), so the
# absolute paths git wrote (a worktree's gitdir, origin's url) hold in every copy. Tests of one file therefore run
# one after another, also under `bats --jobs`.
#
#   setup_file() { tmp=$(fixture_dir); fixture_build build_fn; }   # build_fn fills $tmp
#   setup()      { tmp=$(fixture_dir); fixture_copy; ... }         # a fresh $tmp, as build_fn left it
#   teardown()   { fixture_drop; }

fixture_dir() { # the scratch path, physical (git prints resolved paths; macOS's temp folder is a link)
  echo "$(cd "$BATS_FILE_TMPDIR" && pwd -P)/fixture"
}

fixture_build() { # <function>: builds the template in $tmp
  export BATS_NO_PARALLELIZE_WITHIN_FILE=true
  rm -rf "$tmp" "$BATS_FILE_TMPDIR/template"
  mkdir -p "$tmp"
  "$1"
  cd "$BATS_FILE_TMPDIR" || return 1
  mv "$tmp" "$BATS_FILE_TMPDIR/template"
}

fixture_copy() { # a fresh copy of the template at $tmp
  rm -rf "$tmp"
  cp -Rp "$BATS_FILE_TMPDIR/template" "$tmp"
}

fixture_drop() {
  cd "$BATS_FILE_TMPDIR" || return 1
  rm -rf "$tmp"
}

# link_tools_except <dir> <tool>: a PATH directory with every tool of /usr/bin and /bin but <tool> (a Linux runner
# has gh in /usr/bin itself), linked by two ln calls instead of one per tool.
link_tools_except() {
  local dir=$1 skip=$2 f links=()
  mkdir -p "$dir"
  for f in /usr/bin/*; do
    [ "${f##*/}" = "$skip" ] || links+=("$f")
  done
  [ ${#links[@]} -eq 0 ] || ln -s "${links[@]}" "$dir/"
  links=()
  for f in /bin/*; do
    [ "${f##*/}" = "$skip" ] || [ -e "$dir/${f##*/}" ] || [ -L "$dir/${f##*/}" ] || links+=("$f")
  done
  [ ${#links[@]} -eq 0 ] || ln -s "${links[@]}" "$dir/"
}
