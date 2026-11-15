"""tenkm.msm: the loop state machine.

Manages only the database (SQLite). Every call runs in one transaction:

    from tenkm import msm
    with msm.transaction() as m:
        print(m.loop_get())

The rules (preconditions, side effects, phase transitions) live here, so the
CLI and ad-hoc scripts behave the same. `main()` is the `msm` command: JSON on
stdout, errors as JSON {"code", "message"} on stderr. Errors raise MSMError with
code 1 EINVAL, 2 EPERM or 3 ENOENT.
"""
import json
import os
import re
import secrets
import sqlite3
import string
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

EINVAL, EPERM, ENOENT = 1, 2, 3

ROLES = ("planner", "worker", "curator", "auditor", "operator")
SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE loop (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  current_cycle INTEGER NOT NULL,
  last_audit INTEGER NOT NULL,
  empty_cycles INTEGER NOT NULL,
  phase TEXT NOT NULL CHECK (phase IN ('plan','execute','curate')),
  stopped INTEGER NOT NULL,
  reason TEXT,
  updated_at TEXT NOT NULL);
CREATE TABLE sessions (
  name TEXT PRIMARY KEY,
  role TEXT NOT NULL CHECK (role IN ('planner','worker','curator','auditor','operator')),
  cycle INTEGER,
  status TEXT NOT NULL CHECK (status IN ('active','done','expired')),
  handle TEXT,
  working_directory TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL);
CREATE TABLE cycles (
  id INTEGER PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('open','closed')),
  planner_session TEXT,
  planned_at TEXT NOT NULL,
  headline TEXT,
  report TEXT,
  curator_session TEXT,
  curated_at TEXT);
CREATE TABLE tasks (
  id TEXT PRIMARY KEY,
  seq INTEGER NOT NULL,
  cycle INTEGER NOT NULL,
  shortname TEXT NOT NULL,
  instructions TEXT NOT NULL,
  branch TEXT NOT NULL,
  session TEXT,
  report TEXT,
  status TEXT NOT NULL CHECK (status IN ('waiting','active','done','expired','accepted','rejected')),
  created_at TEXT NOT NULL,
  started_at TEXT,
  done_at TEXT,
  curated_at TEXT);
CREATE TABLE issues (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK (type IN ('escalation','backlog')),
  title TEXT NOT NULL,
  description TEXT,
  owner_session TEXT,
  assignee_role TEXT CHECK (assignee_role IN ('planner','curator','auditor','operator')),
  resolver_role TEXT CHECK (resolver_role IN ('planner','curator','auditor','operator')),
  severity TEXT NOT NULL DEFAULT 'low' CHECK (severity IN ('low','high','blocking')),
  urgent_if TEXT,
  status TEXT NOT NULL CHECK (status IN ('open','resolved')),
  branch TEXT,
  created_at TEXT NOT NULL,
  resolved_at TEXT,
  resolution TEXT);
CREATE TABLE audits (
  id INTEGER PRIMARY KEY,
  period TEXT NOT NULL,
  summary TEXT NOT NULL,
  created_at TEXT NOT NULL);
"""

# Per resource: table, key column, fields accepted on create and update.
RESOURCES = {
    "session": dict(table="sessions", key="name",
                    update=("handle", "working_directory", "status")),
    "task": dict(table="tasks", key="id",
                 update=("shortname", "instructions", "branch", "report", "status")),
    "cycle": dict(table="cycles", key="id", update=("headline", "report")),
    "issue": dict(table="issues", key="id",
                  create=("type", "title", "description", "owner_session", "assignee_role",
                          "resolver_role", "severity", "urgent_if", "branch"),
                  required=("type", "title"),
                  update=("title", "description", "assignee_role", "resolver_role", "severity",
                          "urgent_if", "status", "branch", "resolution")),
    "audit": dict(table="audits", key="id", create=("period", "summary"),
                  required=("period", "summary"), update=("period", "summary")),
}

HIDDEN = {"seq"}
USERNAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class MSMError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def suffix():
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


def to_dict(row):
    if row is None:
        return None
    d = {k: row[k] for k in row.keys() if k not in HIDDEN}
    if "stopped" in d:
        d["stopped"] = bool(d["stopped"])
    if "period" in d and isinstance(d["period"], str):
        d["period"] = json.loads(d["period"])
    if "current_cycle" in d:
        d.pop("id", None)
    return d


def parse_json(text, kind=dict):
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError) as e:
        raise MSMError(EINVAL, f"invalid JSON: {e}")
    if not isinstance(value, kind):
        raise MSMError(EINVAL, f"expected a JSON {kind.__name__}")
    return value


class MSM:
    """The state machine over an open transaction.

    caller is the calling agent's session name (LOOP_SESSION), or None for the
    operator and the Dispatcher. Changes from an expired or removed session are
    refused, and agents can't start, resume or update a stopped loop.
    """

    def __init__(self, db, caller=None):
        self.db = db
        self.caller = caller or None
        self.actions = []  # action log lines, written after the transaction commits

    # --- callers -----------------------------------------------------------
    def caller_session(self):
        if self.caller is None:
            return None
        return self.one("SELECT * FROM sessions WHERE name = ?", self.caller)

    def check_caller(self):
        """Refuse changes from an expired or removed session."""
        if self.caller is None:
            return
        s = self.caller_session()
        if s is None or s["status"] == "expired":
            raise MSMError(EPERM, f"session {self.caller} is no longer active; stop")

    def is_agent(self):
        s = self.caller_session() if self.caller else None
        return s is not None and s["role"] != "operator"

    def check_loop_record(self):
        """While the loop is stopped, only the operator changes the loop record."""
        if self.loop()["stopped"] and (self.is_agent() or
                                       (self.caller and self.caller_session() is None)):
            raise MSMError(EPERM, "only the operator can change a stopped loop")

    def log(self, command, **detail):
        self.actions.append(json.dumps({"at": now(), "session": self.caller,
                                        "command": command, **detail}))

    def check_open(self, cycle_id):
        row = self.one("SELECT status FROM cycles WHERE id = ?", cycle_id)
        if row is not None and row["status"] == "closed":
            raise MSMError(EPERM, f"cycle {cycle_id} is closed and can't be changed")

    # --- helpers -----------------------------------------------------------
    def one(self, sql, *args):
        return self.db.execute(sql, args).fetchone()

    def loop(self):
        row = self.one("SELECT * FROM loop WHERE id = 1")
        if row is None:
            raise MSMError(ENOENT, "loop not initialised; run `msm init`")
        return row

    def set_loop(self, **fields):
        fields["updated_at"] = now()
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE loop SET {cols} WHERE id = 1", tuple(fields.values()))

    def current_cycle(self):
        return self.one("SELECT * FROM cycles WHERE id = ?", self.loop()["current_cycle"])

    def get_row(self, res, key):
        spec = RESOURCES[res]
        row = self.one(f"SELECT * FROM {spec['table']} WHERE {spec['key']} = ?", key)
        if row is None:
            raise MSMError(ENOENT, f"{res} {key} not found")
        return row

    def update_row(self, res, key, fields):
        spec = RESOURCES[res]
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        try:
            self.db.execute(f"UPDATE {spec['table']} SET {cols} WHERE {spec['key']} = ?",
                            (*fields.values(), key))
        except sqlite3.IntegrityError as e:
            raise MSMError(EINVAL, str(e))

    def task_for_session(self, name):
        row = self.one("SELECT * FROM tasks WHERE session = ?", name)
        if row is None:
            raise MSMError(ENOENT, f"no task for session {name}")
        return row

    def check_fields(self, data, allowed):
        bad = set(data) - set(allowed)
        if bad:
            raise MSMError(EINVAL, f"fields not allowed: {', '.join(sorted(bad))}")

    # --- init and loop -----------------------------------------------------
    def init(self):
        if self.one("SELECT name FROM sqlite_master WHERE name = 'loop'"):
            raise MSMError(EPERM, "database already exists")
        for statement in SCHEMA.split(";"):
            if statement.strip():
                self.db.execute(statement)
        self.db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self.db.execute("INSERT INTO loop VALUES (1, 0, 0, 0, 'curate', 1, NULL, ?)", (now(),))
        return to_dict(self.loop())

    def loop_get(self):
        return to_dict(self.loop())

    def loop_start(self):
        self.check_caller()
        self.check_loop_record()
        if not self.loop()["stopped"]:
            raise MSMError(EPERM, "loop is not stopped")
        self.set_loop(stopped=0, reason=None, phase="curate")
        return to_dict(self.loop())

    def loop_resume(self):
        self.check_caller()
        self.check_loop_record()
        loop = self.loop()
        if not loop["stopped"]:
            raise MSMError(EPERM, "loop is not stopped")
        phase = "curate" if loop["phase"] == "plan" else loop["phase"]
        self.set_loop(stopped=0, reason=None, phase=phase)
        return to_dict(self.loop())

    def loop_stop(self, reason=None):
        self.check_caller()
        self.loop()
        self.set_loop(stopped=1, reason=reason)
        return to_dict(self.loop())

    def loop_update(self, data):
        self.check_caller()
        self.check_loop_record()
        self.loop()
        self.check_fields(data, ("reason",))
        self.set_loop(**data)
        return to_dict(self.loop())

    # --- sessions ----------------------------------------------------------
    def active(self, role):
        return self.one("SELECT 1 FROM sessions WHERE role = ? AND status = 'active'", role)

    def pending_contributions(self):
        """Inactive operator or Auditor sessions: work the Curator can take in any phase."""
        return self.one("SELECT 1 FROM sessions WHERE role IN ('operator', 'auditor') "
                        "AND status != 'active'")

    def session_create(self, role, username=None, root=None):
        self.check_caller()
        if role not in ROLES:
            raise MSMError(EINVAL, f"unknown role {role}")
        if (username is not None) != (role == "operator"):
            raise MSMError(EINVAL, "a username is required for, and only for, operator sessions")
        loop = self.loop()
        stopped, phase, current = loop["stopped"], loop["phase"], loop["current_cycle"]
        cycle, task = None, None
        if role == "planner":
            if phase != "plan" or stopped or self.active("planner"):
                raise MSMError(EPERM, "planner needs phase = plan, not stopped, no active planner")
            cur = self.current_cycle()
            cycle = current if cur and cur["status"] == "open" else current + 1
            base = f"cycle{cycle}-planner"
        elif role == "curator":
            if stopped or self.active("curator"):
                raise MSMError(EPERM, "curator needs not stopped and no active curator")
            if phase != "curate" and not self.pending_contributions():
                raise MSMError(EPERM, "curator needs phase = curate, or inactive operator "
                                      "or auditor work")
            cycle = current
            base = f"cycle{cycle}-curator"
        elif role == "worker":
            if phase != "execute" or stopped:
                raise MSMError(EPERM, "worker needs phase = execute, not stopped")
            task = self.one("SELECT * FROM tasks WHERE cycle = ? AND status = 'waiting' "
                            "ORDER BY seq LIMIT 1", current)
            if task is None:
                raise MSMError(EPERM, "no waiting task")
            cycle = current
            n = self.one("SELECT COUNT(*) FROM sessions WHERE role = 'worker' AND cycle = ?",
                         cycle)[0]
            base = f"cycle{cycle}-worker{n + 1}"
        elif role == "auditor":
            if stopped or self.one("SELECT 1 FROM sessions WHERE role = 'auditor'"):
                raise MSMError(EPERM, "auditor needs not stopped, no auditor session")
            base = f"auditor{loop['last_audit'] + 1}"
        else:
            if not USERNAME.match(username):
                raise MSMError(EINVAL, "username must match [a-z0-9]+(-[a-z0-9]+)*")
            base = f"operator-{username}"
        name = f"{base}-{suffix()}"
        while self.one("SELECT 1 FROM sessions WHERE name = ?", name):
            name = f"{base}-{suffix()}"
        t = now()
        root = root or os.environ.get("LOOP_ROOT", "/loop")
        self.db.execute("INSERT INTO sessions VALUES (?, ?, ?, 'active', NULL, ?, ?, ?)",
                        (name, role, cycle, os.path.join(root, name), t, t))
        if task is not None:
            self.db.execute("UPDATE tasks SET session = ?, started_at = ?, status = 'active' "
                            "WHERE id = ?", (name, t, task["id"]))
            self.log("task claim", task=task["id"], worker=name)
        return to_dict(self.get_row("session", name))

    def session_status(self, name, status):
        if status not in ("done", "expired"):
            raise MSMError(EINVAL, "status must be done or expired")
        self.check_caller()
        s = self.get_row("session", name)
        if s["status"] == status:
            return to_dict(s)
        if s["status"] != "active":
            raise MSMError(EPERM, f"session {name} is {s['status']}")
        t = now()
        self.update_row("session", name, {"status": status, "updated_at": t})
        role = s["role"]
        if role == "worker":
            changed = self.db.execute("UPDATE tasks SET status = ?, done_at = ? "
                                      "WHERE session = ? AND status = 'active'",
                                      (status, t, name)).rowcount
            if changed:
                self.log(f"task {status}", worker=name)
        # Phase transitions.
        loop, cur = self.loop(), self.current_cycle()
        is_open = cur is not None and cur["status"] == "open"
        if role == "planner" and status == "done" and loop["phase"] == "plan" and is_open:
            n = self.one("SELECT COUNT(*) FROM tasks WHERE cycle = ?", cur["id"])[0]
            self.set_loop(phase="execute" if n else "curate")
        elif role == "worker" and loop["phase"] == "execute":
            left = self.one("SELECT COUNT(*) FROM tasks WHERE cycle = ? "
                            "AND status IN ('waiting','active')", loop["current_cycle"])[0]
            if not left:
                self.set_loop(phase="curate")
        elif role == "curator" and status == "done" and loop["phase"] == "curate" and not is_open:
            self.set_loop(phase="plan")
        return to_dict(self.get_row("session", name))

    def session_update(self, name, data):
        self.check_caller()
        self.check_fields(data, RESOURCES["session"]["update"])
        self.get_row("session", name)
        status = data.pop("status", None)
        if data:
            data["updated_at"] = now()
            self.update_row("session", name, data)
        if status is not None:
            return self.session_status(name, status)
        return to_dict(self.get_row("session", name))

    def session_remove(self, name):
        self.check_caller()
        self.get_row("session", name)
        if self.db.execute("UPDATE tasks SET status = 'waiting', session = NULL, started_at = NULL "
                           "WHERE session = ? AND status = 'active'", (name,)).rowcount:
            self.log("task returned", worker=name)
        self.db.execute("DELETE FROM sessions WHERE name = ?", (name,))
        return {"removed": name}

    # --- tasks -------------------------------------------------------------
    def task_update(self, task, data):
        self.check_caller()
        self.check_fields(data, RESOURCES["task"]["update"])
        self.check_open(task["cycle"])
        if data.get("status") in ("accepted", "rejected"):
            data["curated_at"] = now()
        self.update_row("task", task["id"], data)
        self.log("task update", task=task["id"], fields=sorted(data))
        return to_dict(self.get_row("task", task["id"]))

    def task_remove(self, task):
        self.check_caller()
        if task["cycle"] == self.loop()["current_cycle"]:
            raise MSMError(EPERM, "tasks of the current cycle cannot be removed")
        self.db.execute("DELETE FROM tasks WHERE id = ?", (task["id"],))
        self.log("task remove", task=task["id"])
        return {"removed": task["id"]}

    # --- cycles ------------------------------------------------------------
    def cycle_create(self, data):
        self.check_caller()
        self.check_fields(data, ("planner_session", "headline", "tasks"))
        tasks = data.get("tasks")
        if not isinstance(data.get("headline"), str) or not isinstance(tasks, list):
            raise MSMError(EINVAL, "cycle create needs headline and tasks")
        for t in tasks:
            if not isinstance(t, dict) or set(t) != {"shortname", "instructions", "branch"} \
                    or not all(isinstance(v, str) for v in t.values()):
                raise MSMError(EINVAL, "each task needs exactly shortname, instructions, branch")
        loop = self.loop()
        if loop["phase"] != "plan" or loop["stopped"]:
            raise MSMError(EPERM, "cycle create needs phase = plan and not stopped")
        t = now()
        cur = self.current_cycle()
        if cur is not None and cur["status"] == "open":
            cycle_id = cur["id"]
            self.db.execute("DELETE FROM tasks WHERE cycle = ?", (cycle_id,))
            self.db.execute("UPDATE cycles SET planner_session = ?, planned_at = ?, headline = ? "
                            "WHERE id = ?", (data.get("planner_session"), t, data["headline"],
                                             cycle_id))
        else:
            cycle_id = loop["current_cycle"] + 1
            self.db.execute("INSERT INTO cycles (id, status, planner_session, planned_at, headline)"
                            " VALUES (?, 'open', ?, ?, ?)",
                            (cycle_id, data.get("planner_session"), t, data["headline"]))
            self.set_loop(current_cycle=cycle_id)
        for seq, task in enumerate(tasks):
            self.db.execute("INSERT INTO tasks (id, seq, cycle, shortname, instructions, branch, "
                            "status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'waiting', ?)",
                            (str(uuid.uuid4()), seq, cycle_id, task["shortname"],
                             task["instructions"], task["branch"], t))
        if tasks:
            self.set_loop(empty_cycles=0)
        else:
            self.set_loop(empty_cycles=loop["empty_cycles"] + 1)
        self.log("cycle create", cycle=cycle_id, tasks=[t["shortname"] for t in tasks])
        return self.cycle_get(cycle_id)

    def cycle_curate(self, data):
        """Close the current cycle and set the verdict of each listed task."""
        self.check_caller()
        self.check_fields(data, ("curator_session", "report", "tasks"))
        cur = self.current_cycle()
        if cur is None or cur["status"] != "open":
            raise MSMError(EPERM, "no open cycle")
        verdicts = data.get("tasks") or []
        if not isinstance(verdicts, list):
            raise MSMError(EINVAL, "tasks must be a list of {id, status}")
        t = now()
        for v in verdicts:
            if not isinstance(v, dict) or set(v) != {"id", "status"} \
                    or v["status"] not in ("accepted", "rejected"):
                raise MSMError(EINVAL, "each task verdict needs id and status accepted|rejected")
            task = self.get_row("task", v["id"])
            if task["cycle"] != cur["id"]:
                raise MSMError(EINVAL, f"task {v['id']} is not in cycle {cur['id']}")
            self.db.execute("UPDATE tasks SET status = ?, curated_at = ? WHERE id = ?",
                            (v["status"], t, v["id"]))
        self.db.execute("UPDATE cycles SET status = 'closed', curator_session = ?, report = ?, "
                        "curated_at = ? WHERE id = ?",
                        (data.get("curator_session"), data.get("report"), t, cur["id"]))
        self.log("cycle curate", cycle=cur["id"],
                 verdicts={v["id"]: v["status"] for v in verdicts})
        return self.cycle_get(cur["id"])

    def cycle_get(self, cycle_id=None):
        if cycle_id is None:
            cycle_id = self.loop()["current_cycle"]
        c = to_dict(self.get_row("cycle", int(cycle_id)))
        rows = self.db.execute("SELECT * FROM tasks WHERE cycle = ? ORDER BY seq", (c["id"],))
        c["tasks"] = [to_dict(r) for r in rows]
        return c

    def cycle_remove(self, cycle_id):
        self.check_caller()
        cycle_id = int(cycle_id)
        self.get_row("cycle", cycle_id)
        if cycle_id == self.loop()["current_cycle"]:
            raise MSMError(EPERM, "the current cycle cannot be removed")
        self.db.execute("DELETE FROM tasks WHERE cycle = ?", (cycle_id,))
        self.db.execute("DELETE FROM cycles WHERE id = ?", (cycle_id,))
        self.log("cycle remove", cycle=cycle_id)
        return {"removed": cycle_id}

    # --- issues and audits -------------------------------------------------
    def create(self, res, data):
        self.check_caller()
        spec = RESOURCES[res]
        self.check_fields(data, spec["create"])
        missing = [f for f in spec["required"] if f not in data]
        if missing:
            raise MSMError(EINVAL, f"missing fields: {', '.join(missing)}")
        t = now()
        if res == "issue":
            row = dict(data, id=str(uuid.uuid4()), status="open", created_at=t)
        else:
            if not isinstance(data["period"], dict) or set(data["period"]) != {"from", "to"}:
                raise MSMError(EINVAL, "period must be {from, to}")
            audit_id = self.loop()["last_audit"] + 1
            row = dict(data, id=audit_id, period=json.dumps(data["period"]), created_at=t)
            self.set_loop(last_audit=audit_id)
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        try:
            self.db.execute(f"INSERT INTO {spec['table']} ({cols}) VALUES ({marks})",
                            tuple(row.values()))
        except sqlite3.IntegrityError as e:
            raise MSMError(EINVAL, str(e))
        self.log(f"{res} create", id=row["id"])
        return to_dict(self.get_row(res, row["id"]))

    def update(self, res, key, data):
        self.check_caller()
        self.check_fields(data, RESOURCES[res]["update"])
        self.get_row(res, key)
        if res == "cycle":
            self.check_open(key)
        if res == "issue" and data.get("status") == "resolved":
            data["resolved_at"] = now()
        if res == "audit" and "period" in data:
            data["period"] = json.dumps(data["period"])
        self.update_row(res, key, data)
        self.log(f"{res} update", id=key, fields=sorted(data))
        return to_dict(self.get_row(res, key))

    def remove(self, res, key):
        self.check_caller()
        row = self.get_row(res, key)
        if res == "issue" and row["status"] == "open":
            raise MSMError(EPERM, "open issues cannot be removed")
        spec = RESOURCES[res]
        self.db.execute(f"DELETE FROM {spec['table']} WHERE {spec['key']} = ?", (key,))
        self.log(f"{res} remove", id=key)
        return {"removed": key}

    def list(self, res, filt=None):
        spec = RESOURCES[res]
        filt = parse_json(filt) if filt else {}
        cols = {r[1] for r in self.db.execute(f"PRAGMA table_info({spec['table']})")} - HIDDEN
        bad = set(filt) - cols
        if bad:
            raise MSMError(EINVAL, f"unknown filter fields: {', '.join(sorted(bad))}")
        where, args = [], []
        for k, v in filt.items():
            if v is None:
                where.append(f"{k} IS NULL")
            else:
                where.append(f"{k} = ?")
                args.append(int(v) if isinstance(v, bool) else v)
        sql = f"SELECT * FROM {spec['table']}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        order = {"tasks": "cycle, seq", "sessions": "created_at"}.get(spec["table"], spec["key"])
        sql += f" ORDER BY {order}"
        return [to_dict(r) for r in self.db.execute(sql, args)]


def db_path():
    """The database path: MSM_DB, or <LOOP_ROOT>/.10km/loop.db."""
    root = os.environ.get("LOOP_ROOT", "/loop")
    return os.environ.get("MSM_DB") or os.path.join(root, ".10km", "loop.db")


def migrate(db):
    """Upgrade an existing database to SCHEMA_VERSION. Safe to repeat."""
    if not db.execute("SELECT name FROM sqlite_master WHERE name = 'loop'").fetchone():
        return
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version >= SCHEMA_VERSION:
        return
    session_cols = {r[1] for r in db.execute("PRAGMA table_info(sessions)")}
    if "pid" in session_cols:
        db.execute("ALTER TABLE sessions RENAME COLUMN pid TO handle")
        # Old values are bare pids; without a start time the launcher can't tell
        # whether they are alive, so only the time-out applies to them.
        db.execute("UPDATE sessions SET handle = 'process:' || handle || ':' "
                   "WHERE handle IS NOT NULL")
    loop_cols = {r[1] for r in db.execute("PRAGMA table_info(loop)")}
    if "empty_cycles" not in loop_cols:
        db.execute("ALTER TABLE loop ADD COLUMN empty_cycles INTEGER NOT NULL DEFAULT 0")
    db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def connect(path=None, create=False):
    path = path or db_path()
    if not create and not os.path.exists(path):
        raise MSMError(ENOENT, f"no database at {path}")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    db = sqlite3.connect(path, isolation_level=None, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode = WAL")
    return db


@contextmanager
def transaction(path=None, create=False, caller=None):
    """Open the database and yield an MSM in one IMMEDIATE transaction.

    caller defaults to LOOP_SESSION. Commits on success, rolls back on any
    exception, and appends the transaction's actions to the action log.
    """
    path = path or db_path()
    db = connect(path, create)
    m = None
    try:
        db.execute("BEGIN IMMEDIATE")
        migrate(db)
        m = MSM(db, caller if caller is not None else os.environ.get("LOOP_SESSION"))
        try:
            yield m
        except BaseException:
            db.execute("ROLLBACK")
            raise
        db.execute("COMMIT")
    finally:
        db.close()
    if m.actions:
        with open(action_log_path(path), "a") as f:
            f.write("".join(line + "\n" for line in m.actions))


def action_log_path(db=None):
    """The action log: MSM_LOG, or actions.log next to the database."""
    return os.environ.get("MSM_LOG") or os.path.join(os.path.dirname(
        os.path.abspath(db or db_path())), "actions.log")


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
        raise MSMError(EINVAL, USAGE)
    res, verb, args = argv[0], (argv[1] if len(argv) > 1 else None), argv[2:]

    def need(n_min, n_max=None):
        n_max = n_min if n_max is None else n_max
        if not n_min <= len(args) <= n_max:
            raise MSMError(EINVAL, USAGE)

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
        if verb in ("get", "remove", "update"):
            if args[:1] == ["--session"]:
                need(2, 3)
                task, rest = m.task_for_session(args[1]), args[2:]
            else:
                need(1, 2)
                task, rest = m.get_row("task", args[0]), args[1:]
            if verb == "update":
                if len(rest) != 1:
                    raise MSMError(EINVAL, USAGE)
                return m.task_update(task, parse_json(rest[0]))
            if rest:
                raise MSMError(EINVAL, USAGE)
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
    raise MSMError(EINVAL, USAGE)


def main(argv):
    if argv[:1] in ([], ["-h"], ["--help"]):
        print(USAGE)
        return 0
    try:
        with transaction(create=argv[:1] == ["init"]) as m:
            result = run(m, argv)
    except MSMError as e:
        print(json.dumps({"code": e.code, "message": e.message}), file=sys.stderr)
        return e.code
    except (ValueError, KeyError, TypeError, AttributeError, sqlite3.IntegrityError) as e:
        print(json.dumps({"code": EINVAL, "message": f"invalid input: {e!r}"}), file=sys.stderr)
        return EINVAL
    except sqlite3.Error as e:
        print(json.dumps({"code": EINVAL, "message": f"database error: {e}"}), file=sys.stderr)
        return EINVAL
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
