"""tenkm.control: the operator's start, pause, resume and stop (R331-R336).

    10km start               start run-loop unless one runs; resume a stopped loop
    10km pause [--now] [reason]
                             stop the loop; run-loop keeps running
    10km resume              resume a stopped loop
    10km stop [--now]        stop the loop and run-loop

Without --now, running agents finish their work; with it, they and their gate
runs are stopped and their sessions expired.
"""
import os
import signal
import subprocess
import sys
import time

from . import dispatch, gate, msm, runloop, timefmt
from .config import BIN

START_WAIT = 10  # seconds `start` waits for run-loop to take its lock
STOP_WAIT = 60  # seconds `stop` waits for run-loop's pass to end


def _loop(cfg):
    with msm.transaction(cfg.db) as m:
        return m.loop_get()


def kicked_off(loop):
    """False before kickoff's `loop start`: msm init leaves phase curate, cycle 0."""
    return not (loop["phase"] == "curate" and loop["current_cycle"] == 0)


def _wait(predicate, seconds):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.1)
    return True


def spawn(cfg):
    """Start this code's run-loop detached (it runs the central loop repo's own
    dispatch), logging to <state dir>/run-loop.log. Returns (pid or None, log path)."""
    script = os.path.join(BIN, "run-loop")
    os.makedirs(cfg.state_dir, exist_ok=True)
    log = os.path.join(cfg.state_dir, "run-loop.log")
    with open(log, "ab") as f:
        p = subprocess.Popen([script], stdin=subprocess.DEVNULL, stdout=f, stderr=f,
                             start_new_session=True, env=dict(os.environ, LOOP_ROOT=cfg.root))
    _wait(lambda: runloop.running(cfg) is not None or p.poll() is not None, START_WAIT)
    return runloop.running(cfg), log


def start(cfg):
    pid = runloop.running(cfg)
    if pid is None:
        pid, log = spawn(cfg)
        if pid is None:
            print(f"run-loop did not start: see {log}", file=sys.stderr)
            return 1
        print(f"run-loop started (pid {pid}), log {log}")
    else:
        print(f"run-loop is already running (pid {pid or '?'})")
    loop = _loop(cfg)
    if not loop["stopped"]:
        print("Loop: running")
        return 0
    return resume(cfg)


def resume(cfg):
    loop = _loop(cfg)
    if not loop["stopped"]:
        print("Loop: running")
    elif not kicked_off(loop):
        print("The loop hasn't been kicked off: `10km kickoff` starts it.", file=sys.stderr)
        return 1
    else:
        try:
            with msm.transaction(cfg.db) as m:
                m.loop_resume()
        except msm.MSMError as e:
            print(f"{e.code}: {e.message}", file=sys.stderr)
            return e.code
        print(f"Loop: resumed, phase {loop['phase']}")
    if runloop.running(cfg) is None and overdue(cfg):
        print("Nothing seems to run the Dispatcher: `10km start` runs run-loop, or run "
              "`10km dispatch` from your scheduler.", file=sys.stderr)
    return 0


def _stop_loop(cfg, reason):
    """Stop the loop unless it is stopped: an earlier reason is kept."""
    with msm.transaction(cfg.db) as m:
        loop = m.loop_get()
        if loop["stopped"]:
            print(f"Loop: already stopped ({loop['reason']})")
            return
        m.loop_stop(reason)
    print(f"Loop: stopped ({reason})")


def _stop_agents(cfg):
    names = dispatch.Pass(cfg).stop_agents()
    runs = gate.stop_runs(cfg)
    print(f"Stopped {len(names)} agent{'s' if len(names) != 1 else ''}"
          + (f" ({', '.join(names)})" if names else "")
          + f" and {runs} gate run{'s' if runs != 1 else ''}")


def pause(cfg, now=False, reason=None):
    _stop_loop(cfg, reason or "paused by the operator")
    if now:
        _stop_agents(cfg)
    else:
        print("Running agents finish their work; run-loop keeps running.")
    return 0


def stop(cfg, now=False):
    _stop_loop(cfg, "stopped by the operator")
    status = 0
    pid = runloop.running(cfg)
    if pid is None:
        print("run-loop: not running")
    elif not pid:
        print("run-loop is starting: run `10km stop` again", file=sys.stderr)
        status = 1
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        if _wait(lambda: runloop.running(cfg) is None, STOP_WAIT):
            print(f"run-loop stopped (pid {pid})")
        else:
            print(f"run-loop (pid {pid}) is still finishing its pass", file=sys.stderr)
            status = 1
    if now:
        _stop_agents(cfg)
    else:
        print("Running agents finish their work.")
    return status


def overdue(cfg, now=None):
    """True if no pass was recorded, or the last one ended over three intervals
    ago (at least two minutes)."""
    beat = dispatch.last_heartbeat(cfg)
    at = timefmt.parse(beat.get("finished_at")) if beat else None
    if at is None:
        return True
    limit = max(3 * cfg.int("DISPATCH_INTERVAL", 60), 120)
    return ((timefmt.parse(now) or timefmt.now()) - at).total_seconds() > limit


def main(cfg, command, argv):
    now = "--now" in argv
    args = [a for a in argv if a != "--now"]
    if command == "start" and not argv:
        return start(cfg)
    if command == "resume" and not argv:
        return resume(cfg)
    if command == "pause":
        return pause(cfg, now, " ".join(args) or None)
    if command == "stop" and not args:
        return stop(cfg, now)
    print(__doc__, file=sys.stderr)
    return 1
