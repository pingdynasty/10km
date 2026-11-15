"""Tests for the tenkm library: migration, config, notify, sessions, dispatch.

Run: python3 -m unittest discover tests
"""
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import warnings
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tenkm import config, dispatch, init, notify, sessions, msm  # noqa: E402


class LoopCase(unittest.TestCase):
    """A fresh loop root with a database and repos, and the env pointing at it."""

    env = {}

    def setUp(self):
        # The process launcher deliberately leaves agents running when it returns.
        warnings.filterwarnings("ignore", "subprocess .* is still running", ResourceWarning)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "root")
        base = {"LOOP_ROOT": self.root, "PROJECT_REPOS": "project", "MSM_DB": "",
                "LOOP_AGENT": "sleep 30", "NOTIFY_CMD": ""}
        self.patch = mock.patch.dict(os.environ, dict(base, **self.env))
        self.patch.start()
        os.environ.pop("MSM_DB")
        self.cfg = config.load()
        init.run(self.cfg)

    def tearDown(self):
        try:
            with msm.transaction(self.cfg.db) as m:
                handles = [s["handle"] for s in m.list("session") if s.get("handle")]
        except sqlite3.DatabaseError:
            handles = []
        for h in handles:
            try:
                os.killpg(int(h.split(":")[1]), 9)
            except (ProcessLookupError, PermissionError):
                pass
        self.patch.stop()
        self.tmp.cleanup()

    def reload(self, **overrides):
        with mock.patch.dict(os.environ, overrides):
            return config.load()

    def m(self):
        return msm.transaction(self.cfg.db)

    def start_loop(self):
        op = sessions.create(self.cfg, "operator", "mars")["name"]
        with self.m() as m:
            m.session_status(op, "done")
            m.loop_start()
        return op


class TestMigration(unittest.TestCase):
    def test_upgrades_pid_column_and_adds_empty_cycles(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "old.db")
            db = sqlite3.connect(path)
            db.executescript("""
              CREATE TABLE loop (id INTEGER PRIMARY KEY, current_cycle INTEGER NOT NULL,
                last_audit INTEGER NOT NULL, phase TEXT NOT NULL, stopped INTEGER NOT NULL,
                reason TEXT, updated_at TEXT NOT NULL);
              INSERT INTO loop VALUES (1, 3, 0, 'plan', 0, NULL, '2026-01-01T00:00:00Z');
              CREATE TABLE sessions (name TEXT PRIMARY KEY, role TEXT, cycle INTEGER,
                status TEXT, pid INTEGER, working_directory TEXT, created_at TEXT,
                updated_at TEXT);
              INSERT INTO sessions VALUES ('s', 'operator', NULL, 'active', 42, '/x', 't', 't');
            """)
            db.commit()
            db.close()
            with msm.transaction(path) as m:
                self.assertEqual(m.loop_get()["empty_cycles"], 0)
                self.assertEqual(m.list("session")[0]["handle"], 42)
            with msm.transaction(path) as m:  # idempotent
                self.assertEqual(m.loop_get()["current_cycle"], 3)


class TestConfig(LoopCase):
    def test_environment_overrides_config(self):
        self.assertEqual(self.cfg.int("MAX_WORKERS", 0), 4)
        self.assertEqual(self.reload(MAX_WORKERS="7").int("MAX_WORKERS", 0), 7)
        self.assertEqual(self.cfg.repos(), ["loop", "project"])
        self.assertEqual(self.reload(WORKER_TIMEOUT="5").timeout("worker"), 5)
        self.assertEqual(self.cfg.timeout("planner"), 3600)


class TestNotify(LoopCase):
    def test_commands_get_variables_and_keys_send_once(self):
        out = os.path.join(self.tmp.name, "out")
        cfg = self.reload(NOTIFY_CMD=f'echo "$TENKM_PRIORITY|$TENKM_TITLE|$TENKM_BODY|$TENKM_PROJECT" >> {out}')
        self.assertTrue(notify.send(cfg, "T", "B", "critical", key="k"))
        self.assertTrue(notify.send(cfg, "T", "B", "critical", key="k"))
        with open(out) as f:
            self.assertEqual(f.read(), "critical|T|B|project\n")

    def test_failed_send_is_retried(self):
        out = os.path.join(self.tmp.name, "out")
        failing = self.reload(NOTIFY_CMD="false")
        self.assertFalse(notify.send(failing, "T", key="k"))
        working = self.reload(NOTIFY_CMD=f"echo sent >> {out}")
        self.assertTrue(notify.send(working, "T", key="k"))
        self.assertTrue(os.path.exists(out))

    def test_default_appends_to_notifications_file(self):
        notify.send(self.cfg, "Hello", "body")
        with open(os.path.join(self.cfg.central, "loop", "NOTIFICATIONS.md")) as f:
            self.assertIn("[default] Hello", f.read())


class TestSessions(LoopCase):
    def test_creates_branch_and_worktree_in_every_repo(self):
        s = sessions.create(self.cfg, "operator", "mars")
        for repo in self.cfg.repos():
            self.assertTrue(os.path.isdir(os.path.join(s["working_directory"], repo, ".git"))
                            or os.path.isfile(os.path.join(s["working_directory"], repo, ".git")))
        sessions.remove(self.cfg, s["name"])
        self.assertFalse(os.path.exists(s["working_directory"]))
        with self.m() as m:
            self.assertEqual(m.list("session"), [])

    def test_git_failure_rolls_back(self):
        cfg = self.reload(MAIN_BRANCH="no-such-branch")
        with self.assertRaises(sessions.SessionError) as e:
            sessions.create(cfg, "operator", "mars")
        self.assertEqual(e.exception.code, sessions.EGIT)
        with self.m() as m:
            self.assertEqual(m.list("session"), [])
        self.assertEqual([d for d in os.listdir(self.root) if d.startswith("operator")], [])

    def test_precondition_failure_has_msm_code(self):
        with self.assertRaises(sessions.SessionError) as e:
            sessions.create(self.cfg, "planner")  # loop is stopped
        self.assertEqual(e.exception.code, msm.EPERM)


class TestDispatch(LoopCase):
    def session(self, role):
        with self.m() as m:
            return [s for s in m.list("session") if s["role"] == role]

    def test_launches_curator_with_handle_and_prompt(self):
        self.start_loop()
        dispatch.run_pass(self.cfg)
        [cur] = self.session("curator")
        self.assertTrue(cur["handle"].startswith("process:"))
        self.assertTrue(os.path.exists(os.path.join(cur["working_directory"], "prompt.txt")))

    def test_times_out_and_kills_agent(self):
        self.start_loop()
        dispatch.run_pass(self.cfg)
        [cur] = self.session("curator")
        pid = int(cur["handle"].split(":")[1])
        dispatch.run_pass(self.reload(CURATOR_TIMEOUT="-1", KILL_GRACE="2"))
        self.assertEqual(self.session("curator")[0]["status"], "expired")
        time.sleep(0.2)
        self.assertNotEqual(subprocess.run(["ps", "-p", str(pid), "-o", "stat="],
                                           capture_output=True, text=True).stdout.strip()[:1],
                            "S")

    def test_dead_agent_is_expired_after_start_grace(self):
        self.start_loop()
        cfg = self.reload(LOOP_AGENT="true")
        dispatch.run_pass(cfg)
        time.sleep(0.5)
        dispatch.run_pass(self.reload(LOOP_AGENT="true", START_GRACE="0"))
        statuses = sorted(s["status"] for s in self.session("curator"))
        self.assertIn("expired", statuses)

    def test_orphan_session_without_handle_is_expired(self):
        self.start_loop()
        s = sessions.create(self.cfg, "curator")
        dispatch.run_pass(self.reload(ORPHAN_GRACE="-1"))
        with self.m() as m:
            self.assertEqual(m.get_row("session", s["name"])["status"], "expired")

    def test_stop_notifies_once(self):
        self.start_loop()
        with self.m() as m:
            m.loop_stop("blocked")
        dispatch.run_pass(self.cfg)
        dispatch.run_pass(self.cfg)
        with open(os.path.join(self.cfg.central, "loop", "NOTIFICATIONS.md")) as f:
            self.assertEqual(f.read().count("Loop stopped: blocked"), 1)
        self.assertEqual(self.session("curator"), [])

    def test_unreadable_database_notifies_and_starts_nothing(self):
        with open(self.cfg.db, "wb") as f:
            f.write(b"not a database" * 100)
        for suffix in ("-wal", "-shm"):
            if os.path.exists(self.cfg.db + suffix):
                os.remove(self.cfg.db + suffix)
        dispatch.run_pass(self.cfg)
        with open(os.path.join(self.cfg.central, "loop", "NOTIFICATIONS.md")) as f:
            self.assertIn("database unreadable", f.read())


class TestAuditorDue(LoopCase):
    def due(self, now, **overrides):
        p = dispatch.Pass(self.reload(**overrides), now=now)
        with self.m() as m:
            return p.auditor_due(m)

    def close_cycle(self, curated_at):
        with self.m() as m:
            m.db.execute("INSERT INTO cycles (id, status, planned_at, curated_at) "
                         "VALUES ((SELECT COALESCE(MAX(id), 0) + 1 FROM cycles), 'closed', ?, ?)",
                         (curated_at, curated_at))

    def test_never_before_first_curated_cycle(self):
        now = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
        self.assertFalse(self.due(now, AUDIT_TIME="07:00", AUDIT_TIMEZONE="Europe/Madrid"))

    def test_daily_time_in_timezone(self):
        self.close_cycle("2026-11-13T10:00:00Z")
        madrid = {"AUDIT_TIME": "07:00", "AUDIT_TIMEZONE": "Europe/Madrid"}
        # 07:00 Madrid in November is 06:00 UTC.
        self.assertFalse(self.due(datetime(2026, 11, 14, 5, 59, tzinfo=timezone.utc), **madrid))
        self.assertTrue(self.due(datetime(2026, 11, 14, 6, 1, tzinfo=timezone.utc), **madrid))
        with self.m() as m:
            m.db.execute("INSERT INTO audits VALUES (1, '{}', 's', '2026-11-14T06:30:00Z')")
        self.assertFalse(self.due(datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc), **madrid))
        self.assertTrue(self.due(datetime(2026, 11, 15, 6, 1, tzinfo=timezone.utc), **madrid))

    def test_cycle_limit(self):
        self.close_cycle("2026-11-13T10:00:00Z")
        now = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
        self.assertFalse(self.due(now, AUDIT_TIME="", AUDIT_CYCLES_LIMIT="2"))
        self.close_cycle("2026-11-13T11:00:00Z")
        self.assertTrue(self.due(now, AUDIT_TIME="", AUDIT_CYCLES_LIMIT="2"))


if __name__ == "__main__":
    unittest.main()
