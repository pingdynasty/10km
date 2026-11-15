#!/usr/bin/env bash
# End-to-end smoke test with a fake agent. Runs in the container:
#   docker build -t 10km . && docker run --rm 10km /opt/10km/tests/smoke.sh
set -euo pipefail
export LOOP_ROOT=$(mktemp -d) MSM_DB=$(mktemp -d)/loop.db
export LOOP_AGENT=fake-agent DISPATCH_INTERVAL=1 PATH="/opt/10km/tests:$PATH"
here="$(cd "$(dirname "$0")/.." && pwd)"

export GIT_AUTHOR_NAME=smoke GIT_AUTHOR_EMAIL=smoke@localhost
export GIT_COMMITTER_NAME=smoke GIT_COMMITTER_EMAIL=smoke@localhost

# Kickoff, as the operator, directly in central: the loop repo, a project repo,
# the database, the goals; then start the loop.
python3 -c 'import sys; sys.path.insert(0, sys.argv[1])
from tenkm.init import create_loop_repo; create_loop_repo(sys.argv[2], source=sys.argv[1])' \
  "$here" "$LOOP_ROOT/central/loop"
git init -q -b main "$LOOP_ROOT/central/project"
git -C "$LOOP_ROOT/central/project" commit -q --allow-empty -m "Initial commit"
"$here/bin/10km" init >/dev/null
export LOOP_CONFIG="$LOOP_ROOT/central/loop/config.env"
. "$here/bin/lib.sh"
echo "Goal: say hello" >"$CENTRAL/loop/GOALS.md"
git -C "$CENTRAL/loop" add GOALS.md
git -C "$CENTRAL/loop" commit -q -m "Set goals"
[ "$(msm loop start | jq -r .phase)" = plan ] || { echo "FAIL: loop start not in plan"; exit 1; }

# Run until cycle 1 is curated and the Auditor's work has been merged too.
for _ in $(seq 90); do
  dispatch
  cycle=$(msm cycle get 1 2>/dev/null || echo null)
  if [ "$(jq -r .status <<<"$cycle")" = closed ] &&
     [ -f "$LOOP_ROOT/central/loop/LEARNINGS.md" ]; then
    break
  fi
  sleep 1
done

msm loop stop >/dev/null
fail() { echo "FAIL: $1"; exit 1; }
[ "$(msm cycle get 1 | jq -r .status)" = closed ] || fail "cycle 1 not closed"
[ "$(msm cycle get 1 | jq -r '.tasks[0].status')" = accepted ] || fail "task not accepted"
[ -f "$CENTRAL/project/hello.txt" ] || fail "worker output not on main"
[ -f "$CENTRAL/loop/GOALS.md" ] || fail "kickoff goals missing"
grep -q "smoke learning" "$CENTRAL/loop/LEARNINGS.md" || fail "auditor work not on main"
git -C "$CENTRAL/project" log --format=%B | grep -q '^Loop-Session: cycle1-worker1-' ||
  fail "no Loop-Session trailer"
[ "$(msm audit list | jq length)" = 1 ] || fail "no audit"
echo "PASS"
