#!/usr/bin/env bash
# Commit the named decision docs and keep the root HANDOFF.md out of git: it
# is per-worktree session state, so it is gitignored (added to the root
# .gitignore when missing) and untracked (when a repo still tracks it), and
# those two changes go into the same commit. The ignore line is anchored
# (/HANDOFF.md; an unanchored one is rewritten): a plan's own handoff
# (plans/<plan>/handoff.md, hal2 plan 0206) is a committed record, and on a
# case-insensitive disk an unanchored line would ignore it. Name it among the
# files like any other doc. Nothing else is committed:
# other staged or unstaged changes stay as they are (the commit is built in a
# temporary index). Git hooks run as usual.
# The message is the subject (and body) only: the script adds the trailers `Worktree:` and `Plan:`.
# Usage: commit-handoff.sh <message> [file ...]   (a HANDOFF.md among the files is skipped)
# Exit 0: committed (or nothing to commit). Exit 1: usage or git error. Exit 2: git missing.
set -euo pipefail

if ! command -v git >/dev/null 2>&1; then
  echo "commit-handoff.sh: git is missing; run install-prerequisites.sh" >&2
  exit 2
fi

if [[ $# -lt 1 ]]; then
  echo "usage: commit-handoff.sh <message> [file ...]" >&2
  exit 1
fi
message="$1"
shift
git rev-parse --is-inside-work-tree >/dev/null
root="$(git rev-parse --show-toplevel)"
handoff="$root/HANDOFF.md"

docs=()
for file in "$@"; do
  if [[ "$(cd "$(dirname "$file")" 2>/dev/null && pwd -P)/$(basename "$file")" == "$(cd "$root" && pwd -P)/HANDOFF.md" ]]; then
    continue
  fi
  if [[ ! -e "$file" ]]; then
    echo "commit-handoff.sh: $file does not exist" >&2
    exit 1
  fi
  docs+=("$file")
done

# Gitignore the root HANDOFF.md (by the rules, whether or not it is tracked), and only that one.
gitignore="$root/.gitignore"
if [[ -f "$gitignore" ]] && grep -qx 'HANDOFF\.md' "$gitignore"; then
  anchored="$(mktemp)"
  sed 's|^HANDOFF\.md$|/HANDOFF.md|' "$gitignore" >"$anchored"
  cat "$anchored" >"$gitignore"
  rm -f "$anchored"
  echo "anchored the HANDOFF.md line of $gitignore (/HANDOFF.md)"
  docs+=("$gitignore")
fi
if ! git check-ignore -q --no-index "$handoff"; then
  if [[ -s "$gitignore" && -n "$(tail -c1 "$gitignore")" ]]; then
    printf '\n' >>"$gitignore"
  fi
  printf '%s\n' "# This worktree's session state (/handoff), never committed" "/HANDOFF.md" >>"$gitignore"
  echo "gitignored HANDOFF.md in $gitignore"
  docs+=("$gitignore")
fi

paths=(${docs[@]+"${docs[@]}"})
tracked=false
if git ls-files --error-unmatch -- "$handoff" >/dev/null 2>&1 \
  || { git rev-parse -q --verify HEAD >/dev/null && git cat-file -e "HEAD:HANDOFF.md" 2>/dev/null; }; then
  tracked=true
  paths+=("$handoff")
fi
if [[ ${#paths[@]} -eq 0 ]]; then
  echo "nothing to commit: no docs named, HANDOFF.md already ignored and untracked"
  exit 0
fi

# The commit: HEAD plus exactly these changes, in an index of its own.
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
with_commit_index() { GIT_INDEX_FILE="$tmp/index" git "$@"; }
if git rev-parse -q --verify HEAD >/dev/null; then
  with_commit_index read-tree HEAD
else
  with_commit_index read-tree --empty
fi
if [[ ${#docs[@]} -gt 0 ]]; then
  with_commit_index add -- ${docs[@]+"${docs[@]}"}
fi
if $tracked; then
  with_commit_index rm -q --cached --ignore-unmatch -- "$handoff"
fi
if git rev-parse -q --verify HEAD >/dev/null && with_commit_index diff --cached --quiet HEAD --; then
  echo "nothing to commit: ${docs[*]:-HANDOFF.md} unchanged"
  exit 0
fi
# The subject says what changed; the origin goes into trailers (hal2 plan 0355): Worktree: <NN>, and Plan: <NNNN>-<slug>
# when plans/CURRENT_PLAN names a plan. Before the attribution lines, which stay the message's last lines.
attribution="$(printf '%s\n' "$message" | grep -E '^(Co-Authored-By|Claude-Session):' || true)"
message="$(printf '%s\n' "$message" | grep -vE '^(Co-Authored-By|Claude-Session):' || true)"
trailer_args=(--trailer "Worktree: $(basename "$root")")
current="$(head -n1 "$root/plans/CURRENT_PLAN" 2>/dev/null || true)"
if [[ "$current" =~ ^[0-9]{4}-[a-z0-9][a-z0-9-]*$ ]]; then
  trailer_args+=(--trailer "Plan: $current")
fi
message="$(printf '%s\n' "$message" | git interpret-trailers --if-exists doNothing "${trailer_args[@]}")"
if [[ -n "$attribution" ]]; then
  message="$message"$'\n'"$attribution"
fi
with_commit_index commit --quiet -m "$message"
# The real index follows the new commit for these paths only.
git reset -q -- ${paths[@]+"${paths[@]}"}
if $tracked; then
  echo "untracked HANDOFF.md (it stays on disk)"
fi
git log --oneline -1
