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

# Repos that get a worktree per session: the loop repo, then every other git
# repo in central/.
repos() {
  echo loop
  for d in "$CENTRAL"/*/; do
    d=${d%/}; n=${d##*/}
    [ "$n" != loop ] && [ -e "$d/.git" ] && echo "$n"
  done
  return 0
}
