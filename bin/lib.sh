# Shared settings for the remaining Bash scripts and tests. Source this file.
set -euo pipefail

BIN="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOOP_ROOT="${LOOP_ROOT:-/loop}"
CENTRAL="$LOOP_ROOT/central"
CONFIG="${LOOP_CONFIG:-$CENTRAL/loop/config.env}"
# shellcheck source=/dev/null
[ -f "$CONFIG" ] && . "$CONFIG"
export LOOP_ROOT MSM_DB="${MSM_DB:-$LOOP_ROOT/.10km/loop.db}"
MSM="$BIN/msm"

# Repos that get a worktree per session: the loop repo, then the project repos.
repos() {
  echo loop
  for spec in ${PROJECT_REPOS:-}; do echo "${spec%%=*}"; done
}
