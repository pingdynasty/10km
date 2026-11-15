"""10km: the loop's command-line entry point.

  10km init                       create the database and repos
  10km status                     status report
  10km dispatch                   one Dispatcher pass
  10km session start <username> [--no-agent] [-- message]
                                  start an operator session
  10km session create <role> [username]
                                  create a session (prints JSON)
  10km session done <name>        mark a session done
  10km notify <title> [body] [--priority critical|default|passive] [--key K]
  10km msm ...                    the state machine
"""
import json
import os
import subprocess
import sys

from . import config, dispatch, init, msm_cli, notify, sessions, state, status


def _session(argv, cfg):
    if not argv:
        print(__doc__, file=sys.stderr)
        return 1
    verb, args = argv[0], argv[1:]
    if verb == "create":
        try:
            s = sessions.create(cfg, *args[:2])
        except sessions.SessionError as e:
            print(json.dumps({"code": e.code, "message": e.message}), file=sys.stderr)
            return e.code
        print(json.dumps(s))
        return 0
    if verb == "done":
        return msm_cli.main(["session", "done", *args])
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
        loop_dir = os.path.join(s["working_directory"], "loop")
        print(f"Session {s['name']} in {s['working_directory']}")
        print(f"When finished: 10km session done {s['name']}")
        if no_agent:
            return 0
        command = cfg.get("SESSION_COMMAND") or "kiro-cli chat"
        env = dict(os.environ, LOOP_SESSION=s["name"], SESSION=s["name"], **cfg.git_env())
        if message:
            command += " " + " ".join(f"'{m}'" for m in message)
        return subprocess.call(["bash", "-c", command], cwd=loop_dir, env=env)
    print(__doc__, file=sys.stderr)
    return 1


def _notify(argv, cfg):
    priority, key, rest = "default", None, []
    i = 0
    while i < len(argv):
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


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    command, args = argv[0], argv[1:]
    if command == "msm":
        return msm_cli.main(args)
    cfg = config.load()
    if command == "init":
        try:
            print(json.dumps(init.run(cfg)))
        except state.MsmError as e:
            print(f"{e.code}: {e.message}", file=sys.stderr)
            return e.code
        return 0
    if command == "status":
        print(status.report(cfg))
        return 0
    if command == "dispatch":
        return dispatch.run_pass(cfg)
    if command == "session":
        return _session(args, cfg)
    if command == "notify":
        return _notify(args, cfg)
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
