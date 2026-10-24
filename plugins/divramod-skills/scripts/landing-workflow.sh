# shellcheck shell=bash
# Which landing workflow file a checkout has (hal2 plan 0423, decision D4). bash 3.2. Sourced:
#
#   . "$here/../shared/landing-workflow.sh"
#   file=$(landing_workflow_pick "$root")            # a checkout's files
#   file=$(landing_workflow_pick "$root" origin/main) # the files of a ref
#
# The names, in the order they are tried: the setting's file (`.hal/landing.toml` `workflow = "local"|"cloud"`;
# $HAL2_LAND_WORKFLOW=local|cloud beats it), the other new file, then the old names, which stay found during the
# migration. No setting: local first. A copy of this file lives in the skills unit
# (code/agents/apps/skills/scripts/landing-workflow.sh), which no other unit may depend on; a test keeps them equal.

# shellcheck disable=SC2034
LANDING_WORKFLOWS="merge-to-main-local.yml merge-to-main-cloud.yml dev-merge-to-main.yml merge-to-main.yml"

# landing_workflow_setting <dir> [ref]: `local`, `cloud` or nothing (unset or unknown).
landing_workflow_setting() {
  local text value
  value="${HAL2_LAND_WORKFLOW:-}"
  if [ -z "$value" ]; then
    if [ -n "${2:-}" ]; then
      text=$(git -C "$1" show "$2:.hal/landing.toml" 2>/dev/null) || text=""
    else
      text=$(cat "$1/.hal/landing.toml" 2>/dev/null) || text=""
    fi
    value=$(printf '%s\n' "$text" | sed -n 's/^[[:space:]]*workflow[[:space:]]*=[[:space:]]*"\([a-z]*\)".*/\1/p' | head -n 1)
  fi
  case "$value" in
    local | cloud) printf '%s\n' "$value" ;;
  esac
}

# landing_workflow_order <dir> [ref]: every name, one per line, in the order to try.
landing_workflow_order() {
  case "$(landing_workflow_setting "$@")" in
    cloud) printf '%s\n' merge-to-main-cloud.yml merge-to-main-local.yml ;;
    *) printf '%s\n' merge-to-main-local.yml merge-to-main-cloud.yml ;;
  esac
  printf '%s\n' dev-merge-to-main.yml merge-to-main.yml
}

# landing_workflow_pick <dir> [ref]: the first name of the order that the checkout (or the ref) has; exit 1 when none.
landing_workflow_pick() {
  local name
  while IFS= read -r name; do
    if [ -n "${2:-}" ]; then
      git -C "$1" cat-file -e "$2:.github/workflows/$name" 2>/dev/null || continue
    else
      [ -f "$1/.github/workflows/$name" ] || continue
    fi
    printf '%s\n' "$name"
    return 0
  done < <(landing_workflow_order "$@")
  return 1
}
