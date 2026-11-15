# Shared helpers for the 10km scripts. Source this file; don't run it.
set -euo pipefail

BIN="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOOP_ROOT="${LOOP_ROOT:-/loop}"
CENTRAL="$LOOP_ROOT/central"
CONFIG="${LOOP_CONFIG:-$CENTRAL/loop/config.env}"
# shellcheck source=/dev/null
[ -f "$CONFIG" ] && . "$CONFIG"
export LOOP_ROOT MSM_DB="${MSM_DB:-$LOOP_ROOT/.10km/loop.db}"
MSM="$BIN/msm"
EAGAIN=4
EGIT=5

die() { echo "$(basename "$0"): $1" >&2; exit "${2:-1}"; }

# Repos that get a worktree per session: the loop repo, then the project repos.
repos() {
  echo loop
  for spec in ${PROJECT_REPOS:-}; do echo "${spec%%=*}"; done
}

# Branches referenced by open issues. Scripts never remove these.
protected_branches() {
  "$MSM" issue list '{"status":"open"}' | jq -r '.[].branch // empty'
}

# Remove a session's worktrees, branches (unless protected), directory and record.
remove_session() {
  local name=$1 protected=$2 repo
  for repo in $(repos); do
    git -C "$CENTRAL/$repo" worktree remove --force "$LOOP_ROOT/$name/$repo" 2>/dev/null || true
    if ! grep -qxF "$name" <<<"$protected"; then
      git -C "$CENTRAL/$repo" branch -D "$name" >/dev/null 2>&1 || true
    fi
    git -C "$CENTRAL/$repo" worktree prune
  done
  rm -rf "${LOOP_ROOT:?}/$name"
  "$MSM" session remove "$name" >/dev/null 2>&1 || true
}

# A repo's default branch: MAIN_BRANCH, else the central worktree's branch.
main_branch() {
  if [ -n "${MAIN_BRANCH:-}" ]; then echo "$MAIN_BRANCH"
  else git -C "$CENTRAL/$1" symbolic-ref --short HEAD; fi
}

# The current cycle as JSON, or null before the first cycle.
current_cycle() { "$MSM" cycle get 2>/dev/null || echo null; }
