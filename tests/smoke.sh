#!/usr/bin/env bash
# End-to-end smoke test with a fake agent, in the container or on a Linux or
# macOS host (needs bash, git, jq and python3 3.9+):
#   make smoke        # docker build -t 10km . && docker run --rm 10km /opt/10km/tests/smoke.sh
#   make smoke-host   # tests/smoke.sh
# It runs in a temporary directory, removed on exit, with this checkout's bin/
# and tests/ first on PATH, and ignores the settings of any loop it runs inside.
# It uses the test config (tests/config.env): agents other than the fake fail.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
tmp=$(mktemp -d "${TMPDIR:-/tmp}/10km-smoke.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
unset SESSION PROMPT_FILE FIRST_MESSAGE ONE_SHOT PYTHONPATH "${!LOOP_@}" "${!MSM_@}" "${!TENKM_@}"
unset PLANNER_AGENT WORKER_AGENT CURATOR_AGENT AUDITOR_AGENT OPERATOR_AGENT
mkdir "$tmp/loop" "$tmp/data"
export LOOP_ROOT="$tmp/loop" MSM_DB="$tmp/data/loop.db"
export LOOP_CONFIG="$here/tests/config.env"
export LOOP_AGENT=fake-agent DISPATCH_INTERVAL=1 PATH="$here/bin:$here/tests:$PATH"

# Ignore the host's system and global git config, so the test does not depend
# on host settings such as an inherited core.hooksPath and its hooks.
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
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

msm loop stop smoke-done >/dev/null
# Let sessions already launched finish before the temporary directory goes.
for _ in $(seq 30); do
  [ "$(msm session list '{"status": "active"}' | jq length)" = 0 ] && break
  sleep 1
done
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
