"""tenkm.state: the loop state machine (msm).

Manages only the database (SQLite). Every call runs in one transaction:

    from tenkm import state
    with state.transaction() as m:
        print(m.loop_get())

The rules (preconditions, side effects, phase transitions) live here, so the
CLI and ad-hoc scripts behave the same. `msm` is the command-line front end.
Errors raise MsmError with code 1 EINVAL, 2 EPERM or 3 ENOENT.
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


class MsmError(Exception):
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
        raise MsmError(EINVAL, f"invalid JSON: {e}")
    if not isinstance(value, kind):
        raise MsmError(EINVAL, f"expected a JSON {kind.__name__}")
    return value


class Msm:
    def __init__(self, db):
        self.db = db

    # --- helpers -----------------------------------------------------------
    def one(self, sql, *args):
        return self.db.execute(sql, args).fetchone()

    def loop(self):
        row = self.one("SELECT * FROM loop WHERE id = 1")
        if row is None:
            raise MsmError(ENOENT, "loop not initialised; run `msm init`")
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
            raise MsmError(ENOENT, f"{res} {key} not found")
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
            raise MsmError(EINVAL, str(e))

    def task_for_session(self, name):
        row = self.one("SELECT * FROM tasks WHERE session = ?", name)
        if row is None:
            raise MsmError(ENOENT, f"no task for session {name}")
        return row

    def check_fields(self, data, allowed):
        bad = set(data) - set(allowed)
        if bad:
            raise MsmError(EINVAL, f"fields not allowed: {', '.join(sorted(bad))}")

    # --- init and loop -----------------------------------------------------
    def init(self):
        if self.one("SELECT name FROM sqlite_master WHERE name = 'loop'"):
            raise MsmError(EPERM, "database already exists")
        for statement in SCHEMA.split(";"):
            if statement.strip():
                self.db.execute(statement)
        self.db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self.db.execute("INSERT INTO loop VALUES (1, 0, 0, 0, 'curate', 1, NULL, ?)", (now(),))
        return to_dict(self.loop())

    def loop_get(self):
        return to_dict(self.loop())

    def loop_start(self):
        if not self.loop()["stopped"]:
            raise MsmError(EPERM, "loop is not stopped")
        self.set_loop(stopped=0, reason=None, phase="curate")
        return to_dict(self.loop())

    def loop_resume(self):
        loop = self.loop()
        if not loop["stopped"]:
            raise MsmError(EPERM, "loop is not stopped")
        phase = "curate" if loop["phase"] == "plan" else loop["phase"]
        self.set_loop(stopped=0, reason=None, phase=phase)
        return to_dict(self.loop())

    def loop_stop(self, reason=None):
        self.loop()
        self.set_loop(stopped=1, reason=reason)
        return to_dict(self.loop())

    def loop_update(self, data):
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
        if role not in ROLES:
            raise MsmError(EINVAL, f"unknown role {role}")
        if (username is not None) != (role == "operator"):
            raise MsmError(EINVAL, "a username is required for, and only for, operator sessions")
        loop = self.loop()
        stopped, phase, current = loop["stopped"], loop["phase"], loop["current_cycle"]
        cycle, task = None, None
        if role == "planner":
            if phase != "plan" or stopped or self.active("planner"):
                raise MsmError(EPERM, "planner needs phase = plan, not stopped, no active planner")
            cur = self.current_cycle()
            cycle = current if cur and cur["status"] == "open" else current + 1
            base = f"cycle{cycle}-planner"
        elif role == "curator":
            if stopped or self.active("curator"):
                raise MsmError(EPERM, "curator needs not stopped and no active curator")
            if phase != "curate" and not self.pending_contributions():
                raise MsmError(EPERM, "curator needs phase = curate, or inactive operator "
                                      "or auditor work")
            cycle = current
            base = f"cycle{cycle}-curator"
        elif role == "worker":
            if phase != "execute" or stopped:
                raise MsmError(EPERM, "worker needs phase = execute, not stopped")
            task = self.one("SELECT * FROM tasks WHERE cycle = ? AND status = 'waiting' "
                            "ORDER BY seq LIMIT 1", current)
            if task is None:
                raise MsmError(EPERM, "no waiting task")
            cycle = current
            n = self.one("SELECT COUNT(*) FROM sessions WHERE role = 'worker' AND cycle = ?",
                         cycle)[0]
            base = f"cycle{cycle}-worker{n + 1}"
        elif role == "auditor":
            if stopped or self.one("SELECT 1 FROM sessions WHERE role = 'auditor'"):
                raise MsmError(EPERM, "auditor needs not stopped, no auditor session")
            base = f"auditor{loop['last_audit'] + 1}"
        else:
            if not USERNAME.match(username):
                raise MsmError(EINVAL, "username must match [a-z0-9]+(-[a-z0-9]+)*")
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
        return to_dict(self.get_row("session", name))

    def session_status(self, name, status):
        if status not in ("done", "expired"):
            raise MsmError(EINVAL, "status must be done or expired")
        s = self.get_row("session", name)
        if s["status"] == status:
            return to_dict(s)
        if s["status"] != "active":
            raise MsmError(EPERM, f"session {name} is {s['status']}")
        t = now()
        self.update_row("session", name, {"status": status, "updated_at": t})
        role = s["role"]
        if role == "worker":
            self.db.execute("UPDATE tasks SET status = ?, done_at = ? "
                            "WHERE session = ? AND status = 'active'", (status, t, name))
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
        self.get_row("session", name)
        self.db.execute("UPDATE tasks SET status = 'waiting', session = NULL, started_at = NULL "
                        "WHERE session = ? AND status = 'active'", (name,))
        self.db.execute("DELETE FROM sessions WHERE name = ?", (name,))
        return {"removed": name}

    # --- tasks -------------------------------------------------------------
    def task_update(self, task, data):
        self.check_fields(data, RESOURCES["task"]["update"])
        if data.get("status") in ("accepted", "rejected"):
            data["curated_at"] = now()
        self.update_row("task", task["id"], data)
        return to_dict(self.get_row("task", task["id"]))

    def task_remove(self, task):
        if task["cycle"] == self.loop()["current_cycle"]:
            raise MsmError(EPERM, "tasks of the current cycle cannot be removed")
        self.db.execute("DELETE FROM tasks WHERE id = ?", (task["id"],))
        return {"removed": task["id"]}

    def task_batch_update(self, verdicts, curate=None):
        """Atomic: update tasks to accepted|rejected, optionally curate the cycle."""
        t = now()
        for row in verdicts:
            tid = row.get("id") or self.task_for_session(row["session"])["id"]
            status = row["status"]
            if status not in ("accepted", "rejected"):
                raise MsmError(EINVAL, f"bad verdict {status}")
            self.db.execute("UPDATE tasks SET status = ?, curated_at = ? WHERE id = ?",
                            (status, t, tid))
        if curate is not None:
            self.cycle_curate(curate)
        return {"updated": len(verdicts), "curated": curate is not None}

    # --- cycles ------------------------------------------------------------
    def cycle_create(self, data):
        self.check_fields(data, ("planner_session", "headline", "tasks"))
        tasks = data.get("tasks")
        if not isinstance(data.get("headline"), str) or not isinstance(tasks, list):
            raise MsmError(EINVAL, "cycle create needs headline and tasks")
        for t in tasks:
            if not isinstance(t, dict) or set(t) != {"shortname", "instructions", "branch"} \
                    or not all(isinstance(v, str) for v in t.values()):
                raise MsmError(EINVAL, "each task needs exactly shortname, instructions, branch")
        loop = self.loop()
        if loop["phase"] != "plan" or loop["stopped"]:
            raise MsmError(EPERM, "cycle create needs phase = plan and not stopped")
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
        return self.cycle_get(cycle_id)

    def cycle_curate(self, data):
        self.check_fields(data, ("curator_session", "report"))
        cur = self.current_cycle()
        if cur is None or cur["status"] != "open":
            raise MsmError(EPERM, "no open cycle")
        self.db.execute("UPDATE cycles SET status = 'closed', curator_session = ?, report = ?, "
                        "curated_at = ? WHERE id = ?",
                        (data.get("curator_session"), data.get("report"), now(), cur["id"]))
        return self.cycle_get(cur["id"])

    def cycle_get(self, cycle_id=None):
        if cycle_id is None:
            cycle_id = self.loop()["current_cycle"]
        c = to_dict(self.get_row("cycle", int(cycle_id)))
        rows = self.db.execute("SELECT * FROM tasks WHERE cycle = ? ORDER BY seq", (c["id"],))
        c["tasks"] = [to_dict(r) for r in rows]
        return c

    def cycle_remove(self, cycle_id):
        cycle_id = int(cycle_id)
        self.get_row("cycle", cycle_id)
        if cycle_id == self.loop()["current_cycle"]:
            raise MsmError(EPERM, "the current cycle cannot be removed")
        self.db.execute("DELETE FROM tasks WHERE cycle = ?", (cycle_id,))
        self.db.execute("DELETE FROM cycles WHERE id = ?", (cycle_id,))
        return {"removed": cycle_id}

    # --- issues and audits -------------------------------------------------
    def create(self, res, data):
        spec = RESOURCES[res]
        self.check_fields(data, spec["create"])
        missing = [f for f in spec["required"] if f not in data]
        if missing:
            raise MsmError(EINVAL, f"missing fields: {', '.join(missing)}")
        t = now()
        if res == "issue":
            row = dict(data, id=str(uuid.uuid4()), status="open", created_at=t)
        else:
            if not isinstance(data["period"], dict) or set(data["period"]) != {"from", "to"}:
                raise MsmError(EINVAL, "period must be {from, to}")
            audit_id = self.loop()["last_audit"] + 1
            row = dict(data, id=audit_id, period=json.dumps(data["period"]), created_at=t)
            self.set_loop(last_audit=audit_id)
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        try:
            self.db.execute(f"INSERT INTO {spec['table']} ({cols}) VALUES ({marks})",
                            tuple(row.values()))
        except sqlite3.IntegrityError as e:
            raise MsmError(EINVAL, str(e))
        return to_dict(self.get_row(res, row["id"]))

    def update(self, res, key, data):
        self.check_fields(data, RESOURCES[res]["update"])
        self.get_row(res, key)
        if res == "issue" and data.get("status") == "resolved":
            data["resolved_at"] = now()
        if res == "audit" and "period" in data:
            data["period"] = json.dumps(data["period"])
        self.update_row(res, key, data)
        return to_dict(self.get_row(res, key))

    def remove(self, res, key):
        row = self.get_row(res, key)
        if res == "issue" and row["status"] == "open":
            raise MsmError(EPERM, "open issues cannot be removed")
        spec = RESOURCES[res]
        self.db.execute(f"DELETE FROM {spec['table']} WHERE {spec['key']} = ?", (key,))
        return {"removed": key}

    def list(self, res, filt=None):
        spec = RESOURCES[res]
        filt = parse_json(filt) if filt else {}
        cols = {r[1] for r in self.db.execute(f"PRAGMA table_info({spec['table']})")} - HIDDEN
        bad = set(filt) - cols
        if bad:
            raise MsmError(EINVAL, f"unknown filter fields: {', '.join(sorted(bad))}")
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
    loop_cols = {r[1] for r in db.execute("PRAGMA table_info(loop)")}
    if "empty_cycles" not in loop_cols:
        db.execute("ALTER TABLE loop ADD COLUMN empty_cycles INTEGER NOT NULL DEFAULT 0")
    db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def connect(path=None, create=False):
    path = path or db_path()
    if not create and not os.path.exists(path):
        raise MsmError(ENOENT, f"no database at {path}")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    db = sqlite3.connect(path, isolation_level=None, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode = WAL")
    return db


@contextmanager
def transaction(path=None, create=False):
    """Open the database and yield an Msm in one IMMEDIATE transaction.

    Commits on success, rolls back on any exception.
    """
    db = connect(path, create)
    try:
        db.execute("BEGIN IMMEDIATE")
        migrate(db)
        try:
            yield Msm(db)
        except BaseException:
            db.execute("ROLLBACK")
            raise
        db.execute("COMMIT")
    finally:
        db.close()
