#!/usr/bin/env bash
# End-to-end smoke test with a fake agent. Runs in the container:
#   docker build -t 10km . && docker run --rm 10km /opt/10km/tests/smoke.sh
set -euo pipefail
export LOOP_ROOT=$(mktemp -d) MSM_DB=$(mktemp -d)/loop.db
export LOOP_AGENT=fake-agent DISPATCH_INTERVAL=1 PATH="/opt/10km/tests:$PATH"
here="$(cd "$(dirname "$0")/.." && pwd)"

"$here/bin/init"
export LOOP_CONFIG="$LOOP_ROOT/central/loop/config.env"
. "$here/bin/lib.sh"

# Kickoff as an operator session.
op=$(session operator smoke | jq -r .name)
echo "Goal: say hello" >"$LOOP_ROOT/$op/loop/GOALS.md"
git -C "$LOOP_ROOT/$op/loop" add GOALS.md
git -C "$LOOP_ROOT/$op/loop" commit -q -m "Set goals"
msm session done "$op" >/dev/null
msm loop start >/dev/null

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
[ -f "$CENTRAL/loop/GOALS.md" ] || fail "kickoff not on main"
grep -q "smoke learning" "$CENTRAL/loop/LEARNINGS.md" || fail "auditor work not on main"
git -C "$CENTRAL/project" log --format=%B | grep -q '^Loop-Session: cycle1-worker1-' ||
  fail "no Loop-Session trailer"
[ "$(msm audit list | jq length)" = 1 ] || fail "no audit"
echo "PASS"
