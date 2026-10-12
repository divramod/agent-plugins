#!/usr/bin/env bash
# The farmer skill: every landing carries the farmer branch's role file commits (roles/farmer/ROLE.md,
# roles/farmer/.gitignore) to main.
# Runs in the worktree being landed, after main was merged in and the gates passed. The farmer
# branch may only change those two files; anything else is not merged (it would skip the gates).
set -euo pipefail
# The farmer works in the slot and branch farmer-<project> (hal2 .adr/roles-folder.md): <project> is origin's
# repository name, else the main checkout's folder, lowercase, other characters than [a-z0-9-] as "-".
project() {
  local url name
  url="$(git -C "${HAL_HOOK_MAIN_ROOT:-.}" remote get-url origin 2>/dev/null || true)"
  name="${url##*[/:]}"; name="${name%.git}"
  [ -n "$name" ] || name="$(basename "$(cd "${HAL_HOOK_MAIN_ROOT:-.}" && pwd)")"
  printf '%s' "$name" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9-' '-' | sed 's/^-*//; s/-*$//'
}
farmer="${HAL_FARMER_BRANCH:-farmer-$(project)}"
[ "${HAL_HOOK_BRANCH:-}" = "$farmer" ] && exit 0
git rev-parse --verify --quiet "refs/heads/$farmer" >/dev/null || exit 0
[ -n "$(git rev-list HEAD.."$farmer")" ] || exit 0
changed="$(git diff --name-only HEAD..."$farmer")"
if [ -n "$(printf '%s\n' "$changed" | grep -vx -e 'roles/farmer/ROLE.md' -e 'roles/farmer/.gitignore' | grep -v '^$' || true)" ]; then
  echo "farmer: branch $farmer changes more than roles/farmer/ROLE.md; not merged into this landing:" >&2
  printf '  %s\n' $changed >&2
  exit 0
fi
git merge --no-edit -m "Merge branch '$farmer' (roles/farmer/ROLE.md) into $HAL_HOOK_BRANCH" "$farmer"
echo "farmer: merged $farmer's roles/farmer/ROLE.md into this landing"
