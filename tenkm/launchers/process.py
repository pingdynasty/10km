"""The process launcher: runs the role's agent command as a detached process group.

Handle: "process:<pid>:<start time>". The pid is also the process group id. The
start time (from `ps`, in UTC and the C locale) guards against pid reuse: a
recycled pid has a different start time, so it is never treated as ours.

The agent counts as alive while any process in its group is alive, so children
that outlive the agent's own process are found and stopped too.
"""
import os
import signal
import subprocess
import time

PS_ENV = dict(os.environ, TZ="UTC", LC_ALL="C")


def _ps(pid, field):
    p = subprocess.run(["ps", "-o", f"{field}=", "-p", str(pid)],
                       capture_output=True, text=True, env=PS_ENV)
    return p.stdout.strip() if p.returncode == 0 else ""


def _parse(handle):
    _, pid, started = handle.split(":", 2)
    return int(pid), started


def _group_exists(pgid):
    """True if any process in the group is running (zombies don't count)."""
    p = subprocess.run(["ps", "-A", "-o", "pgid,stat"], capture_output=True, text=True,
                       env=PS_ENV)
    for line in p.stdout.splitlines()[1:]:  # the first row is the header
        fields = line.split()
        if len(fields) == 2 and fields[0] == str(pgid) and not fields[1].startswith("Z"):
            return True
    return False


def _state(handle):
    """'ours' if the group leader is our process, 'gone' if it has exited, or
    'reused' if another process now has its pid."""
    pid, started = _parse(handle)
    current = _ps(pid, "lstart")
    if not current:
        return "gone"
    return "ours" if current == started else "reused"


def launch(cfg, session, role, env, log_path):
    command = cfg.agent_command(role)
    if not command:
        raise RuntimeError(f"no agent command for {role}: set LOOP_AGENT or {role.upper()}_AGENT")
    with open(log_path, "ab") as log:
        p = subprocess.Popen(["bash", "-c", command], cwd=session["working_directory"],
                             env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             start_new_session=True)
    return f"process:{p.pid}:{_ps(p.pid, 'lstart')}"


def alive(cfg, handle):
    """True while any process of the agent's group runs; None if it can't tell."""
    pid, started = _parse(handle)
    if not started:
        return None  # a pid without a start time (migrated from an old database)
    if _state(handle) == "reused":
        return False
    return _group_exists(pid)


def stop(cfg, handle):
    """SIGTERM to the process group, a grace period, then SIGKILL. True when gone."""
    pid, started = _parse(handle)
    if not started:
        return False  # can't be sure the pid is still ours
    if _state(handle) == "reused" or not _group_exists(pid):
        return True
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        for _ in range(cfg.int("KILL_GRACE", 10) if sig == signal.SIGTERM else 2):
            if not _group_exists(pid):
                return True
            time.sleep(1)
    return not _group_exists(pid)
