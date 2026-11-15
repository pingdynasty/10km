"""tenkm.launchtest: `10km launch-test` launches a role's agent with a one-line
prompt, as the Dispatcher would but with no loop state (see README, "Checking a
loop"). The temporary directory it runs in is kept, with the log and exit code.
"""
import os
import sys
import tempfile
import time

from . import dispatch, gate, launchers
from .config import Config

ROLES = ("planner", "worker", "curator", "auditor")
PROMPT = "This is a 10km launch test. Reply with the single word OK and do nothing else."
USAGE = "usage: 10km launch-test [planner|worker|curator|auditor] [--timeout SECONDS]"


def run(cfg, role="worker", timeout=600, poll=0.5):
    """Launch and follow the agent. Returns (exit status or None if unknown, seconds,
    timed out, log path)."""
    command = cfg.agent_command(role)
    if not command:
        raise RuntimeError(f"no agent command for {role}: set LOOP_AGENT or {role.upper()}_AGENT")
    directory = tempfile.mkdtemp(prefix=f"10km-launch-test-{role}-")
    name = f"launch-test-{role}"
    log = os.path.join(directory, "agent.log")
    rc_path = os.path.join(directory, "exit-code")
    prompt_file = os.path.join(directory, "prompt.txt")
    with open(prompt_file, "w") as f:
        f.write(PROMPT + "\n")
    test_cfg = Config(cfg)
    test_cfg[f"{role.upper()}_AGENT"] = gate.recording(command, rc_path)
    env = dispatch.Pass(cfg).agent_env(name, prompt_file, PROMPT)
    del env["LOOP_SESSION"]
    env.update(LAUNCH_TEST="1", LOOP_ROOT=directory,
               MSM_DB=os.path.join(directory, "no-loop.db"),
               MSM_LOG=os.path.join(directory, "actions.log"))
    launcher = launchers.get(cfg)
    session = {"name": name, "working_directory": directory, "role": role}
    start = time.monotonic()
    handle = launcher.launch(test_cfg, session, role, env, log)
    timed_out = False
    while not os.path.exists(rc_path) and launcher.alive(test_cfg, handle) is not False:
        if time.monotonic() - start >= timeout:
            timed_out = True
            launcher.stop(test_cfg, handle)
            break
        time.sleep(poll)
    seconds = round(time.monotonic() - start, 1)
    try:
        with open(rc_path) as f:
            code = int(f.read().strip())
    except (OSError, ValueError):
        code = None
    return code, seconds, timed_out, log


def main(cfg, argv):
    args, timeout = list(argv), 600
    if "--timeout" in args:
        i = args.index("--timeout")
        value = args[i + 1:i + 2]
        if not value or not value[0].isdigit():
            print(USAGE, file=sys.stderr)
            return 2
        timeout = int(value[0])
        del args[i:i + 2]
    if len(args) > 1 or args and args[0] not in ROLES:
        print(USAGE, file=sys.stderr)
        return 2
    role = args[0] if args else "worker"
    try:
        code, seconds, timed_out, log = run(cfg, role, timeout)
    except Exception as e:  # a launch failure is the result
        print(f"launch-test {role}: launch failed: {e}", file=sys.stderr)
        return 1
    if timed_out:
        result = f"timed out after {timeout}s and stopped"
    else:
        result = "exit code unknown" if code is None else f"exit {code}"
    print(f"launch-test {role}: {result} in {seconds}s\nlog: {log}")
    tail = gate.tail(log, 10)
    if tail:
        print(f"--- last lines of the log ---\n{tail}", end="" if tail.endswith("\n") else "\n")
    return 0 if code == 0 and not timed_out else 1
