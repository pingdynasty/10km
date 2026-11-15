"""tenkm.launchtest: launch a trivial agent outside the loop state.

    10km launch-test [role] [--timeout SECONDS]

Launches the role's agent command (default role: worker) through the configured
launcher, as the Dispatcher would, but with a one-line prompt, in a new
temporary directory, and with no session or cycle in msm. It follows the agent
to the end (killing it after the time-out, default 600 seconds) and reports its
exit code, how long it ran and its log. The temporary directory is kept, with
the log, the prompt and the exit code.

The agent gets the Dispatcher's environment (SESSION, PROMPT_FILE,
FIRST_MESSAGE, PATH, PYTHONPATH) plus LAUNCH_TEST=1, without LOOP_SESSION, and
with LOOP_ROOT, MSM_DB and MSM_LOG pointing into the temporary directory, so it
can't change the live loop's state.
"""
import os
import sys
import tempfile
import time

from . import dispatch, launchers
from .config import Config

ROLES = ("planner", "worker", "curator", "auditor")
PROMPT = "This is a 10km launch test. Reply with the single word OK and do nothing else."
USAGE = "usage: 10km launch-test [planner|worker|curator|auditor] [--timeout SECONDS]"


def _wrapped(command, rc_path):
    """The agent command, run in a subshell, then its exit status recorded."""
    return (f'(\n{command}\n)\nrc=$?\n'
            f'echo "$rc" > "{rc_path}.tmp" && mv "{rc_path}.tmp" "{rc_path}"\nexit "$rc"\n')


def run(cfg, role="worker", timeout=600, poll=0.5):
    """Launch, follow and report. Returns a dict: role, directory, log, handle,
    exit (int, or None if unknown), seconds, timed_out."""
    command = cfg.agent_command(role)
    if not command:
        raise RuntimeError(f"no agent command for {role}: set LOOP_AGENT or {role.upper()}_AGENT")
    directory = tempfile.mkdtemp(prefix=f"10km-launch-test-{role}-")
    name = f"launch-test-{role}"
    log_path = os.path.join(directory, "agent.log")
    rc_path = os.path.join(directory, "exit-code")
    prompt_file = os.path.join(directory, "prompt.txt")
    with open(prompt_file, "w") as f:
        f.write(PROMPT + "\n")
    test_cfg = Config(cfg)
    test_cfg[f"{role.upper()}_AGENT"] = _wrapped(command, rc_path)
    env = dispatch.Pass(cfg).agent_env(name, prompt_file, PROMPT)
    env.pop("LOOP_SESSION", None)
    env.update(LAUNCH_TEST="1", LOOP_ROOT=directory,
               MSM_DB=os.path.join(directory, "no-loop.db"),
               MSM_LOG=os.path.join(directory, "actions.log"))
    launcher = launchers.get(cfg)
    session = {"name": name, "working_directory": directory, "role": role}
    start = time.time()
    handle = launcher.launch(test_cfg, session, role, env, log_path)
    timed_out = False
    while not os.path.exists(rc_path):
        alive = launcher.alive(test_cfg, handle)
        if alive is False:
            break
        if time.time() - start >= timeout:
            timed_out = True
            launcher.stop(test_cfg, handle)
            break
        time.sleep(poll)
    seconds = time.time() - start
    # The status file is written as the wrapper exits; give a racing exit a moment.
    for _ in range(10):
        if os.path.exists(rc_path) or timed_out:
            break
        time.sleep(0.1)
    try:
        with open(rc_path) as f:
            code = int(f.read().strip())
    except (OSError, ValueError):
        code = None
    return {"role": role, "directory": directory, "log": log_path, "handle": handle,
            "exit": code, "seconds": round(seconds, 1), "timed_out": timed_out}


def _tail(path, n=10):
    try:
        with open(path, errors="replace") as f:
            return "".join(f.readlines()[-n:])
    except OSError:
        return ""


def main(cfg, argv):
    role, timeout, i = "worker", 600, 0
    rest = []
    while i < len(argv):
        if argv[i] == "--timeout" and i + 1 < len(argv) and argv[i + 1].isdigit():
            timeout, i = int(argv[i + 1]), i + 2
        else:
            rest.append(argv[i])
            i += 1
    if len(rest) > 1 or rest and rest[0] not in ROLES:
        print(USAGE, file=sys.stderr)
        return 1
    if rest:
        role = rest[0]
    try:
        r = run(cfg, role, timeout)
    except Exception as e:  # a launch failure is the result
        print(f"launch-test {role}: launch failed: {e}", file=sys.stderr)
        return 1
    if r["timed_out"]:
        result = f"timed out after {timeout}s and stopped"
    elif r["exit"] is None:
        result = "exit code unknown"
    else:
        result = f"exit {r['exit']}"
    print(f"launch-test {role}: {result} in {r['seconds']}s\nlog: {r['log']}")
    tail = _tail(r["log"])
    if tail:
        print(f"--- last lines of the log ---\n{tail}", end="" if tail.endswith("\n") else "\n")
    return 0 if r["exit"] == 0 and not r["timed_out"] else 1
