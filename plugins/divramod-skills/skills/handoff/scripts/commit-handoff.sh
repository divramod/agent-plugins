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
# The message is the subject (and body) only: the script adds the trailers `Worktree:` and `Plan:`. Where the farm's
# commits are neutral (hal2 plan 0409 D15, the plan skill's `planread.py neutral`; HAL_HANDOFF_PLANREAD names another
# planread.py) it adds none, a plan scope in the subject (`docs(0409|3): ...`) is dropped (`docs: ...`), and the plan
# is named for the post-commit hook, which links the commit in the plan store (`planread.py link-next --kind handoff`).
# In the store home (hal2 plan 0409: no plan file in the tree) the plan's files named here are where.py's copy in
# the edit folder outside the tree: `where.py --apply` takes them into the plan store (and runs its sync trigger)
# first, and only the files inside the checkout are committed.
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
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The store home's copy into the store (prints nothing and changes nothing in the files home).
applied="$(python3 "$here/where.py" --apply --root "$root")"
if [[ -n "$applied" ]]; then
  echo "applied the plan's copy to the plan store: $applied"
fi
top="$(cd "$root" && pwd -P)"

docs=()
for file in "$@"; do
  real="$(cd "$(dirname "$file")" 2>/dev/null && pwd -P)/$(basename "$file")"
  if [[ "$real" == "$top/HANDOFF.md" ]]; then
    continue
  fi
  if [[ -n "$applied" && "$real" != "$top/"* && -e "$file" ]]; then
    continue  # the store home's copy, applied above
  fi
  if [[ ! -e "$file" ]]; then
    echo "commit-handoff.sh: $file does not exist" >&2
    exit 1
  fi
  docs+=("$file")
done

# Gitignore the root HANDOFF.md (by the rules, whether or not it is tracked), and only that one. Not in the store home:
# its root handoff lives in the plan store (applied above), and no hal line goes into its .gitignore (plan 0409 step 12).
gitignore="$root/.gitignore"
if [[ -n "$applied" ]]; then
  :
elif [[ -f "$gitignore" ]] && grep -qx 'HANDOFF\.md' "$gitignore"; then
  anchored="$(mktemp)"
  sed 's|^HANDOFF\.md$|/HANDOFF.md|' "$gitignore" >"$anchored"
  cat "$anchored" >"$gitignore"
  rm -f "$anchored"
  echo "anchored the HANDOFF.md line of $gitignore (/HANDOFF.md)"
  docs+=("$gitignore")
fi
if [[ -z "$applied" ]] && ! git check-ignore -q --no-index "$handoff"; then
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
# when the CURRENT_PLAN pointer names a plan. Before the attribution lines, which stay the message's last lines.
attribution="$(printf '%s\n' "$message" | grep -E '^(Co-Authored-By|Claude-Session):' || true)"
message="$(printf '%s\n' "$message" | grep -vE '^(Co-Authored-By|Claude-Session):' || true)"
u="$here"; until [ -d "$u/.claude-plugin" ] || [ "$u" = / ]; do u="$(dirname "$u")"; done
if [ -f "$u/scripts/skillpath.sh" ]; then
  . "$u/scripts/skillpath.sh"  # skill_dir <name> <dir>: a sibling skill, flat or in a category (plan 0360 D20)
else
  skill_dir() { printf '%s/../../%s\n' "$2" "$1"; }  # outside a skills unit (a copied script): the flat layout
fi
planread="${HAL_HANDOFF_PLANREAD:-$(skill_dir plan "$here" 2>/dev/null || true)/scripts/planread.py}"
neutral=off
if [[ -f "$planread" ]]; then
  neutral="$(python3 "$planread" neutral --root "$root" 2>/dev/null || echo off)"
fi
pointers="$(dirname "$planread")/pointers.py"  # CURRENT_PLAN: the git dir's, else the old one in `plans/` (plan 0409 step 12)
if [[ -f "$pointers" ]]; then
  current="$(python3 "$pointers" read "$root" CURRENT_PLAN 2>/dev/null | head -n1 || true)"
else
  current="$(head -n1 "$root/plans/CURRENT_PLAN" 2>/dev/null || true)"
fi
if [[ "$neutral" == on ]]; then
  message="$(printf '%s\n' "$message" | sed -E '1s/^([a-z]+)\([0-9][^)]*\)(!?):/\1\2:/')"
  [[ -z "$attribution" ]] || message="$message"$'\n'  # the attribution is its own paragraph
  if [[ "$current" =~ ^[0-9]{4}-[a-z0-9][a-z0-9-]*$ ]]; then
    python3 "$planread" link-next --root "$root" --plan "$current" --kind handoff 2>/dev/null || true
  fi
else
  trailer_args=(--trailer "Worktree: $(basename "$root")")
  if [[ "$current" =~ ^[0-9]{4}-[a-z0-9][a-z0-9-]*$ ]]; then
    trailer_args+=(--trailer "Plan: $current")
  fi
  message="$(printf '%s\n' "$message" | git interpret-trailers --if-exists doNothing "${trailer_args[@]}")"
fi
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
