"""msm: command-line front end to tenkm.state.

Output is JSON on stdout. Errors are JSON {"code", "message"} on stderr.
Exit status: 0 ok, 1 EINVAL, 2 EPERM, 3 ENOENT.
"""
import json
import sqlite3
import sys

from .state import EINVAL, MsmError, parse_json, to_dict, transaction

USAGE = """usage: msm <command>
  init
  loop start|resume|get
  loop stop [reason]
  loop update <json>
  session create <role> [username]
  session update <name> <json>
  session get <name>
  session list [filter]
  session done|expired <name>
  session remove <name>
  task get|remove <id> | --session <name>
  task update <id> | --session <name> <json>
  task list [filter]
  task batch <verdicts-json> [<cycle-curate-json>]
  cycle create|curate <json>
  cycle get [id]
  cycle list [filter]
  cycle update <id> <json>
  cycle remove <id>
  issue|audit create <json>
  issue|audit get|remove <id>
  issue|audit list [filter]
  issue|audit update <id> <json>"""


def run(m, argv):
    if not argv:
        raise MsmError(EINVAL, USAGE)
    res, verb, args = argv[0], (argv[1] if len(argv) > 1 else None), argv[2:]

    def need(n_min, n_max=None):
        n_max = n_min if n_max is None else n_max
        if not n_min <= len(args) <= n_max:
            raise MsmError(EINVAL, USAGE)

    if res == "init" and verb is None:
        return m.init()
    if res == "loop":
        if verb in ("start", "resume", "get"):
            need(0)
            return {"start": m.loop_start, "resume": m.loop_resume, "get": m.loop_get}[verb]()
        if verb == "stop":
            need(0, 1)
            return m.loop_stop(*args)
        if verb == "update":
            need(1)
            return m.loop_update(parse_json(args[0]))
    if res == "session":
        if verb == "create":
            need(1, 2)
            return m.session_create(*args)
        if verb == "update":
            need(2)
            return m.session_update(args[0], parse_json(args[1]))
        if verb == "get":
            need(1)
            return to_dict(m.get_row("session", args[0]))
        if verb == "list":
            need(0, 1)
            return m.list("session", *args)
        if verb in ("done", "expired"):
            need(1)
            return m.session_status(args[0], verb)
        if verb == "remove":
            need(1)
            return m.session_remove(args[0])
    if res == "task":
        if verb == "list":
            need(0, 1)
            return m.list("task", *args)
        if verb == "batch":
            need(1, 2)
            data = parse_json(args[0], list)
            curate = parse_json(args[1]) if len(args) == 2 else None
            return m.task_batch_update(data, curate)
        if verb in ("get", "remove", "update"):
            if args[:1] == ["--session"]:
                need(2, 3)
                task, rest = m.task_for_session(args[1]), args[2:]
            else:
                need(1, 2)
                task, rest = m.get_row("task", args[0]), args[1:]
            if verb == "update":
                if len(rest) != 1:
                    raise MsmError(EINVAL, USAGE)
                return m.task_update(task, parse_json(rest[0]))
            if rest:
                raise MsmError(EINVAL, USAGE)
            return to_dict(task) if verb == "get" else m.task_remove(task)
    if res == "cycle":
        if verb in ("create", "curate"):
            need(1)
            data = parse_json(args[0])
            return m.cycle_create(data) if verb == "create" else m.cycle_curate(data)
        if verb == "get":
            need(0, 1)
            return m.cycle_get(*args)
        if verb == "list":
            need(0, 1)
            return m.list("cycle", *args)
        if verb == "update":
            need(2)
            return m.update("cycle", int(args[0]), parse_json(args[1]))
        if verb == "remove":
            need(1)
            return m.cycle_remove(args[0])
    if res in ("issue", "audit"):
        key = (lambda k: int(k)) if res == "audit" else (lambda k: k)
        if verb == "create":
            need(1)
            return m.create(res, parse_json(args[0]))
        if verb == "get":
            need(1)
            return to_dict(m.get_row(res, key(args[0])))
        if verb == "list":
            need(0, 1)
            return m.list(res, *args)
        if verb == "update":
            need(2)
            return m.update(res, key(args[0]), parse_json(args[1]))
        if verb == "remove":
            need(1)
            return m.remove(res, key(args[0]))
    raise MsmError(EINVAL, USAGE)


def main(argv):
    if argv[:1] in ([], ["-h"], ["--help"]):
        print(USAGE)
        return 0
    try:
        with transaction(create=argv[:1] == ["init"]) as m:
            result = run(m, argv)
    except MsmError as e:
        print(json.dumps({"code": e.code, "message": e.message}), file=sys.stderr)
        return e.code
    except (ValueError, sqlite3.IntegrityError) as e:
        print(json.dumps({"code": EINVAL, "message": str(e)}), file=sys.stderr)
        return EINVAL
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
