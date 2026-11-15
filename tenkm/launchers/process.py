"""The process launcher: runs the role's agent command as a detached process group.

Handle: "process:<pid>:<start time>". The start time (from `ps`) guards against pid
reuse: a recycled pid has a different start time, so it doesn't count as alive.
"""
import os
import signal
import subprocess
import time


def _ps(pid, field):
    p = subprocess.run(["ps", "-o", f"{field}=", "-p", str(pid)],
                       capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else ""


def _parse(handle):
    _, pid, started = handle.split(":", 2)
    return int(pid), started


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
    pid, started = _parse(handle)
    if not started or _ps(pid, "lstart") != started:
        return False
    return not _ps(pid, "stat").startswith("Z")


def stop(cfg, handle):
    """SIGTERM to the process group, a grace period, then SIGKILL."""
    pid, _ = _parse(handle)
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    for _ in range(cfg.int("KILL_GRACE", 10)):
        if not alive(cfg, handle):
            return True
        time.sleep(1)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return True
