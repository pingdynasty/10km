"""tenkm.runloop: run a Dispatcher pass every DISPATCH_INTERVAL seconds (R136).

One runs per loop (R332): it holds <state dir>/run-loop.lock, with its pid in it,
while it runs. Each pass runs the central loop repo's own bin/dispatch, so agents
can adapt it. SIGTERM ends it once the current pass is over.

`run-loop` is optional: anything that runs `10km dispatch` regularly (cron, a
systemd timer, launchd) does the same job.
"""
import fcntl
import os
import signal
import subprocess
import sys
import time

from . import config
from .config import BIN
from .dispatch import log

LOCK = "run-loop.lock"


def lock_path(cfg):
    return os.path.join(cfg.state_dir, LOCK)


def running(cfg):
    """The pid of this loop's run-loop, 0 if one runs but its pid isn't written
    yet, or None if none runs."""
    try:
        f = open(lock_path(cfg))
    except FileNotFoundError:
        return None
    with f:
        try:
            fcntl.flock(f, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            text = f.read().strip()
            return int(text) if text.isdigit() else 0
        return None


def dispatch_command(cfg):
    path = os.path.join(cfg.central, "loop", "bin", "dispatch")
    return path if os.access(path, os.X_OK) else os.path.join(BIN, "dispatch")


def interval():
    """DISPATCH_INTERVAL, read again before each sleep so a change applies."""
    try:
        return max(float(config.load().get("DISPATCH_INTERVAL") or 60), 0.0)
    except ValueError:
        return 60.0


class _Stop(Exception):
    pass


def main(argv=None):
    cfg = config.load()
    os.environ["LOOP_ROOT"] = cfg.root
    os.makedirs(cfg.state_dir, exist_ok=True)
    lock = open(lock_path(cfg), "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"run-loop is already running for {cfg.root} (pid {running(cfg) or '?'})",
              file=sys.stderr)
        return 1
    lock.truncate(0)
    lock.write(f"{os.getpid()}\n")
    lock.flush()

    state = {"stop": False, "sleeping": False}

    def on_term(signum, frame):
        state["stop"] = True
        if state["sleeping"]:
            raise _Stop

    signal.signal(signal.SIGTERM, on_term)
    log(f"run-loop started (pid {os.getpid()}) for {cfg.root}")
    try:
        while not state["stop"]:
            rc = subprocess.call([dispatch_command(cfg)])
            if rc:
                log(f"dispatch failed: {rc}")
            state["sleeping"] = True
            try:
                if not state["stop"]:
                    time.sleep(interval())
            except _Stop:
                break
            finally:
                state["sleeping"] = False
    finally:
        log("run-loop stopped")
    return 0
