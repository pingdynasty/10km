"""10km: the loop's command-line entry point.

  10km init                       create the database; register the central repos
  10km kickoff [-- message]       set up the loop with OPERATOR_AGENT
  10km status                     status report
  10km start                      start run-loop unless one runs; resume a stopped loop
  10km pause [--now] [reason]     stop the loop; run-loop keeps running
  10km resume                     resume a stopped loop
  10km stop [--now]               stop the loop and run-loop
                                  (--now: also stop running agents and their gates)
  10km metrics [--cycle N] [--json]
                                  sessions, times, commits and usage per cycle and role
  10km dispatch                   one Dispatcher pass
  10km session start <username> [--no-agent] [-- message]
                                  start an operator session
  10km session create <role> [username]
                                  create a session (prints JSON)
  10km session done <name>        mark a session done
  10km notify <title> [body] [--priority critical|default|passive] [--key K]
  10km doctor                     check that the loop can run
  10km launch-test [role] [--timeout SECONDS]
                                  launch a trivial agent outside the loop state
  10km gate worker|validation     run a tier's gates in the central worktrees
  10km msm ...                    the state machine
"""
import json
import os
import subprocess
import sys

from . import (config, control, dispatch, doctor, gate, init, launchtest, metrics, msm, notify,
               sessions, status)


def _session(argv, cfg):
    if not argv:
        print(__doc__, file=sys.stderr)
        return 1
    verb, args = argv[0], argv[1:]
    if verb == "create":
        if not 1 <= len(args) <= 2:
            print(json.dumps({"code": msm.EINVAL,
                              "message": "usage: session create <role> [username]"}),
                  file=sys.stderr)
            return msm.EINVAL
        try:
            s = sessions.create(cfg, *args[:2])
        except sessions.SessionError as e:
            print(json.dumps({"code": e.code, "message": e.message}), file=sys.stderr)
            return e.code
        print(json.dumps(s))
        return 0
    if verb == "done":
        return msm.main(["session", "done", *args])
    if verb == "start":
        message = []
        if "--" in args:
            i = args.index("--")
            args, message = args[:i], args[i + 1:]
        no_agent = "--no-agent" in args
        args = [a for a in args if a != "--no-agent"]
        if len(args) != 1:
            print("usage: 10km session start <username> [--no-agent] [-- message]", file=sys.stderr)
            return 1
        try:
            s = sessions.create(cfg, "operator", args[0])
        except sessions.SessionError as e:
            print(f"{e.code}: {e.message}", file=sys.stderr)
            return e.code
        print(f"Session {s['name']} in {s['working_directory']}")
        print(f"When finished: 10km session done {s['name']}")
        if no_agent:
            return 0
        loop = os.path.join(s["working_directory"], "loop")
        intro = (f"You are the operator's agent in the 10km operator session {s['name']}, in "
                 f"its loop worktree {loop}. Read prompts/session.md there and follow it.")
        if message:
            intro += f"\n\nThe operator's instructions: {' '.join(message)}"
        return run_operator_agent(cfg, loop, intro, session=s["name"], one_shot=bool(message))
    print(__doc__, file=sys.stderr)
    return 1


def run_operator_agent(cfg, cwd, message="", session=None, one_shot=False):
    """Run OPERATOR_AGENT in cwd with FIRST_MESSAGE set to message (may be empty).
    ONE_SHOT=1 asks for a non-interactive run."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("LOOP_SESSION", "SESSION", "FIRST_MESSAGE", "ONE_SHOT")}
    loop = cfg.repo_path("loop")
    env.update(LOOP_ROOT=cfg.root, MSM_DB=cfg.db, MSM_LOG=cfg.action_log,
               PATH=os.pathsep.join([os.path.join(loop, "bin"), env.get("PATH", "")]),
               PYTHONPATH=os.pathsep.join(p for p in (loop, env.get("PYTHONPATH")) if p))
    if session:
        env.update(LOOP_SESSION=session, SESSION=session)
    if message:
        env["FIRST_MESSAGE"] = message
    if one_shot:
        env["ONE_SHOT"] = "1"
    return subprocess.call(["bash", "-c", cfg.agent_command("operator")], cwd=cwd, env=env)


def _kickoff(argv, cfg):
    """Kickoff: create the database if needed, register the central repos, then run
    the operator's agent in the central loop worktree, with no session."""
    message = []
    if "--" in argv:
        i = argv.index("--")
        argv, message = argv[:i], argv[i + 1:]
    if argv:
        print("usage: 10km kickoff [-- message]", file=sys.stderr)
        return 1
    try:
        print(json.dumps(init.run(cfg)))
    except msm.MSMError as e:
        print(f"{e.code}: {e.message}", file=sys.stderr)
        return e.code
    loop = cfg.repo_path("loop")
    intro = (f"You are running the kickoff of a 10km loop, as the operator's agent, in the "
             f"central loop worktree {loop}. Read prompts/kickoff.md there and follow it.")
    if message:
        intro += f"\n\nThe operator's instructions: {' '.join(message)}"
    return run_operator_agent(cfg, loop, intro, one_shot=bool(message))


def _notify(argv, cfg):
    priority, key, rest = "default", None, []
    i = 0
    while i < len(argv):
        if argv[i] in ("--priority", "--key") and i + 1 == len(argv):
            print(f"{argv[i]} needs a value", file=sys.stderr)
            return 1
        if argv[i] == "--priority":
            priority, i = argv[i + 1], i + 2
        elif argv[i] == "--key":
            key, i = argv[i + 1], i + 2
        else:
            rest.append(argv[i])
            i += 1
    if not rest:
        print("usage: 10km notify <title> [body] [--priority P] [--key K]", file=sys.stderr)
        return 1
    return 0 if notify.send(cfg, rest[0], " ".join(rest[1:]), priority, key) else 1


def _metrics(argv, cfg):
    as_json, cycle, i = False, None, 0
    while i < len(argv):
        if argv[i] == "--json":
            as_json, i = True, i + 1
        elif argv[i] == "--cycle" and i + 1 < len(argv) and argv[i + 1].isdigit():
            cycle, i = int(argv[i + 1]), i + 2
        else:
            print("usage: 10km metrics [--cycle N] [--json]", file=sys.stderr)
            return 1
    try:
        data = metrics.collect(cfg, cycle)
    except msm.MSMError as e:
        print(f"{e.code}: {e.message}", file=sys.stderr)
        return e.code
    print(json.dumps(data, indent=1) if as_json else metrics.text(data))
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    command, args = argv[0], argv[1:]
    if command == "msm":
        return msm.main(args)
    cfg = config.load()
    if command == "init":
        try:
            print(json.dumps(init.run(cfg)))
        except msm.MSMError as e:
            print(f"{e.code}: {e.message}", file=sys.stderr)
            return e.code
        return 0
    if command == "status":
        print(status.report(cfg))
        return 0
    if command in ("start", "pause", "resume", "stop"):
        return control.main(cfg, command, args)
    if command == "metrics":
        return _metrics(args, cfg)
    if command == "dispatch":
        return dispatch.run_pass(cfg)
    if command == "session":
        return _session(args, cfg)
    if command == "kickoff":
        return _kickoff(args, cfg)
    if command == "notify":
        return _notify(args, cfg)
    if command == "gate":
        return gate.operator_main(cfg, args)
    if command == "doctor":
        return doctor.main(cfg, args)
    if command == "launch-test":
        return launchtest.main(cfg, args)
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
