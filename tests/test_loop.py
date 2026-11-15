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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv  # noqa: E402  (test config, no caller env: tests/testenv.py)
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
        env = dict(testenv.GIT_ID, **testenv.HOST_GIT_OFF, LOOP_ROOT=self.root,
                   LOOP_AGENT="sleep 30", NOTIFY_CMD="")
        self.patch = mock.patch.dict(os.environ, dict(env, **self.env))
        self.patch.start()
        self.cfg = config.load()
        testenv.loop_repo(self.cfg.repo_path("loop"))
        testenv.project_repo(self.cfg.repo_path("project"))
        init.run(self.cfg)

    def tearDown(self):
        try:
            with msm.transaction(self.cfg.db) as m:
                handles = [s["handle"] for s in m.list("session") if s.get("handle")]
        except (sqlite3.DatabaseError, msm.MSMError):
            handles = []
        for h in handles:
            try:
                os.killpg(int(h.split(":")[1]), 9)
            except (ProcessLookupError, PermissionError, ValueError, IndexError):
                pass
        self.patch.stop()
        self.tmp.cleanup()

    def reload(self, **overrides):
        with mock.patch.dict(os.environ, overrides):
            return config.load()

    def m(self):
        return msm.transaction(self.cfg.db)

    def sessions(self, role):
        with self.m() as m:
            return [s for s in m.list("session") if s["role"] == role]

    def start_loop(self):
        """Start the loop with a done operator session: work for a Curator."""
        op = sessions.create(self.cfg, "operator", "mars")["name"]
        with self.m() as m:
            m.session_status(op, "done")
            m.loop_start()
        return op

    def close_cycle(self, curated_at="2026-01-01T01:00:00Z"):
        """Add a closed cycle, curated at curated_at."""
        with self.m() as m:
            m.db.execute("INSERT INTO cycles (id, status, planned_at, curated_at) "
                         "VALUES ((SELECT COALESCE(MAX(id), 0) + 1 FROM cycles), 'closed', ?, ?)",
                         (curated_at, curated_at))


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
                self.assertEqual(m.list("session")[0]["handle"], "process:42:")
            with msm.transaction(path) as m:  # idempotent
                self.assertEqual(m.loop_get()["current_cycle"], 3)

    def test_rebuilds_issues_with_answered_and_assigner(self):
        """Schema 2 to 3: status answered and answered_at; owner_session becomes
        assigner_session, assigner_role comes from its name, resolver_role goes."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "old.db")
            db = sqlite3.connect(path)
            db.executescript("""
              CREATE TABLE loop (id INTEGER PRIMARY KEY, current_cycle INTEGER NOT NULL,
                last_audit INTEGER NOT NULL, empty_cycles INTEGER NOT NULL,
                phase TEXT NOT NULL, stopped INTEGER NOT NULL, reason TEXT,
                updated_at TEXT NOT NULL);
              INSERT INTO loop VALUES (1, 3, 0, 0, 'plan', 0, NULL, '2026-01-01T00:00:00Z');
              CREATE TABLE issues (id TEXT PRIMARY KEY, type TEXT NOT NULL, title TEXT NOT NULL,
                description TEXT, owner_session TEXT, assignee_role TEXT, resolver_role TEXT,
                severity TEXT NOT NULL DEFAULT 'low', urgent_if TEXT,
                status TEXT NOT NULL CHECK (status IN ('open','resolved')), branch TEXT,
                created_at TEXT NOT NULL, resolved_at TEXT, resolution TEXT);
              PRAGMA user_version = 2;
            """)
            owners = {"p": "cycle3-planner-abcdefgh", "w": "cycle3-worker12-abcdefgh",
                      "c": "cycle2-curator-abcdefgh", "a": "auditor4-abcdefgh",
                      "o": "operator-mars-abcdefgh", "n": None, "e": "", "x": "odd"}
            for key, owner in owners.items():
                db.execute("INSERT INTO issues VALUES (?, 'backlog', ?, 'd', ?, 'planner', "
                           "'planner', 'low', NULL, 'open', 'b', 't', NULL, NULL)",
                           (key, key, owner))
            db.commit()
            db.close()
            for _ in range(2):  # idempotent
                with msm.transaction(path) as m:
                    issues = {i["id"]: i for i in m.list("issue")}
            roles = {k: (i["assigner_session"], i["assigner_role"]) for k, i in issues.items()}
            self.assertEqual(roles, {
                "p": (owners["p"], "planner"), "w": (owners["w"], "worker"),
                "c": (owners["c"], "curator"), "a": (owners["a"], "auditor"),
                "o": (owners["o"], "operator"), "n": (None, "operator"),
                "e": (None, "operator"), "x": ("odd", "operator")})
            self.assertNotIn("owner_session", issues["p"])
            self.assertNotIn("resolver_role", issues["p"])
            self.assertEqual((issues["p"]["branch"], issues["p"]["answered_at"]), ("b", None))
            with msm.transaction(path) as m:
                self.assertEqual(m.update("issue", "p", {"status": "answered"})["status"],
                                 "answered")
                self.assertEqual(m.db.execute("PRAGMA user_version").fetchone()[0],
                                 msm.SCHEMA_VERSION)


class TestConfig(LoopCase):
    def test_environment_overrides_config(self):
        self.assertEqual(self.cfg.int("MAX_WORKERS", 0), 4)
        self.assertEqual(self.reload(MAX_WORKERS="7").int("MAX_WORKERS", 0), 7)
        self.assertEqual(self.cfg.repos(), ["loop", "project"])
        self.assertEqual(self.reload(WORKER_TIMEOUT="5").timeout("worker"), 5)
        self.assertEqual(self.cfg.timeout("planner"), 3600)


class TestBrokenConfig(LoopCase):
    def test_syntax_error_and_exit_are_reported(self):
        for text in ("MAX_WORKERS=2\nif then\n", "exit 0\n"):
            path = os.path.join(self.tmp.name, "bad.env")
            with open(path, "w") as f:
                f.write(text)
            cfg = self.reload(LOOP_CONFIG=path)
            self.assertIn("TENKM_CONFIG_ERROR", cfg)
            self.assertEqual(cfg.root, self.root)
            self.assertIn("PATH", cfg)


class TestInit(LoopCase):
    def test_init_registers_central_repos_and_rerun_is_safe(self):
        report = init.run(self.cfg)
        self.assertEqual(report, {"database": "existing", "loop": "main", "project": "main"})
        added = self.cfg.repo_path("extra")
        testenv.project_repo(added, "develop")
        self.assertEqual(init.run(self.cfg)["extra"], "develop")
        self.assertEqual(self.cfg.repos(), ["loop", "extra", "project"])

    def test_init_needs_a_loop_repo(self):
        with self.assertRaises(msm.MSMError):
            init.run(self.reload(LOOP_ROOT=os.path.join(self.tmp.name, "nowhere")))


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
        subprocess.run(["git", "-C", self.cfg.repo_path("project"), "config",
                        "tenkm.mainBranch", "no-such-branch"], check=True)
        with self.assertRaises(sessions.SessionError) as e:
            sessions.create(self.cfg, "operator", "mars")
        self.assertEqual(e.exception.code, sessions.EGIT)
        with self.m() as m:
            self.assertEqual(m.list("session"), [])
        self.assertEqual([d for d in os.listdir(self.root) if d.startswith("operator")], [])

    def test_detached_central_head_still_branches_from_main(self):
        subprocess.run(["git", "-C", self.cfg.repo_path("project"), "checkout", "-q", "--detach"],
                       check=True)
        s = sessions.create(self.cfg, "operator", "mars")  # main was recorded at init
        self.assertTrue(os.path.isdir(os.path.join(s["working_directory"], "project")))

    def test_precondition_failure_has_msm_code(self):
        with self.assertRaises(sessions.SessionError) as e:
            sessions.create(self.cfg, "planner")  # loop is stopped
        self.assertEqual(e.exception.code, msm.EPERM)


class TestDispatch(LoopCase):
    def test_launches_curator_with_handle_and_prompt(self):
        self.start_loop()
        dispatch.run_pass(self.cfg)
        [cur] = self.sessions("curator")
        self.assertTrue(cur["handle"].startswith("process:"))
        self.assertTrue(os.path.exists(os.path.join(cur["working_directory"], "prompt.txt")))

    def test_times_out_and_kills_agent(self):
        self.start_loop()
        dispatch.run_pass(self.cfg)
        [cur] = self.sessions("curator")
        pid = int(cur["handle"].split(":")[1])
        dispatch.run_pass(self.reload(CURATOR_TIMEOUT="-1", KILL_GRACE="2"))
        self.assertEqual(self.sessions("curator")[0]["status"], "expired")
        time.sleep(0.2)
        self.assertNotEqual(subprocess.run(["ps", "-p", str(pid), "-o", "stat="],
                                           capture_output=True, text=True).stdout.strip()[:1],
                            "S")

    def test_dead_agent_is_expired_after_start_grace(self):
        self.start_loop()
        cfg = self.reload(LOOP_AGENT="true")
        dispatch.run_pass(cfg)
        from tenkm.launchers import process
        [cur] = self.sessions("curator")
        self.assertTrue(testenv.wait_for(lambda: process.alive(cfg, cur["handle"]) is False))
        dispatch.run_pass(self.reload(LOOP_AGENT="true", START_GRACE="0"))
        statuses = sorted(s["status"] for s in self.sessions("curator"))
        self.assertIn("expired", statuses)

    def test_session_without_handle_only_times_out(self):
        self.start_loop()
        s = sessions.create(self.cfg, "curator")  # not launched by the Dispatcher
        dispatch.run_pass(self.cfg)
        with self.m() as m:
            self.assertEqual(m.get_row("session", s["name"])["status"], "active")
        dispatch.run_pass(self.reload(CURATOR_TIMEOUT="-1"))
        with self.m() as m:
            self.assertEqual(m.get_row("session", s["name"])["status"], "expired")
            self.assertTrue(any(s["name"] in i["title"] for i in m.list("issue")))

    def test_unstoppable_sessions_are_expired_with_an_escalation(self):
        self.start_loop()
        for handle in ("pending:1", "process:42:", "nosuch:x"):
            with self.m() as m:
                m.db.execute("DELETE FROM sessions WHERE role = 'curator'")
            s = sessions.create(self.cfg, "curator")
            with self.m() as m:
                m.session_update(s["name"], {"handle": handle})
            dispatch.run_pass(self.reload(CURATOR_TIMEOUT="-1", LOOP_AGENT=""))
            with self.m() as m:
                self.assertEqual(m.get_row("session", s["name"])["status"], "expired")
                [issue] = [i for i in m.list("issue") if s["name"] in i["title"]]
                self.assertEqual((issue["severity"], issue["assignee_role"]), ("high", "operator"))

    def test_expiring_a_session_that_just_finished_is_harmless(self):
        self.start_loop()
        s = sessions.create(self.cfg, "curator")
        with self.m() as m:
            m.session_status(s["name"], "done")
        dispatch.Pass(self.cfg).expire(s["name"], "test")  # must not raise
        dispatch.Pass(self.cfg).expire("no-such-session", "test")

    def test_agent_children_are_found_and_stopped(self):
        self.start_loop()
        cfg = self.reload(LOOP_AGENT="sleep 30 & sleep 30 & exit 0")
        dispatch.run_pass(cfg)
        [cur] = self.sessions("curator")
        time.sleep(0.5)
        from tenkm.launchers import process
        self.assertTrue(process.alive(cfg, cur["handle"]))  # leader gone, children alive
        self.assertTrue(process.stop(self.reload(KILL_GRACE="2"), cur["handle"]))
        self.assertFalse(process.alive(cfg, cur["handle"]))

    def test_alive_check_ignores_timezone_and_locale(self):
        self.start_loop()
        dispatch.run_pass(self.cfg)
        [cur] = self.sessions("curator")
        from tenkm.launchers import process
        with mock.patch.dict(os.environ, TZ="Asia/Tokyo", LC_ALL="fr_FR.UTF-8"):
            self.assertTrue(process.alive(self.cfg, cur["handle"]))

    def test_missing_database_is_notified(self):
        os.remove(self.cfg.db)
        dispatch.run_pass(self.cfg)
        with open(os.path.join(self.cfg.central, "loop", "NOTIFICATIONS.md")) as f:
            self.assertIn("database missing", f.read())

    def test_stopped_loop_starts_nothing_and_notifies_nothing(self):
        self.start_loop()
        with self.m() as m:
            m.loop_stop("blocked")
        dispatch.run_pass(self.cfg)
        self.assertEqual(self.sessions("curator"), [])
        self.assertFalse(os.path.exists(os.path.join(self.cfg.central, "loop", "NOTIFICATIONS.md")))

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

    def test_never_before_first_curated_cycle(self):
        now = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
        self.assertFalse(self.due(now, AUDIT_TIME="07:00", AUDIT_TIMEZONE="Europe/Madrid"))

    def test_daily_time_in_timezone(self):
        self.close_cycle("2026-11-13T10:00:00Z")
        with self.m() as m:
            m.db.execute("INSERT INTO audits VALUES (1, '{}', 's', '2026-11-13T06:30:00Z')")
        madrid = {"AUDIT_TIME": "07:00", "AUDIT_TIMEZONE": "Europe/Madrid"}
        # 07:00 Madrid in November is 06:00 UTC.
        self.assertFalse(self.due(datetime(2026, 11, 14, 5, 59, tzinfo=timezone.utc), **madrid))
        self.assertTrue(self.due(datetime(2026, 11, 14, 6, 1, tzinfo=timezone.utc), **madrid))
        with self.m() as m:
            m.db.execute("INSERT INTO audits VALUES (2, '{}', 's', '2026-11-14T06:30:00Z')")
        self.assertFalse(self.due(datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc), **madrid))
        self.assertTrue(self.due(datetime(2026, 11, 15, 6, 1, tzinfo=timezone.utc), **madrid))

    def test_missed_trigger_from_yesterday_is_due_after_midnight(self):
        self.close_cycle("2026-11-12T10:00:00Z")
        with self.m() as m:
            m.db.execute("INSERT INTO audits VALUES (1, '{}', 's', '2026-11-12T06:30:00Z')")
        utc = {"AUDIT_TIME": "07:00", "AUDIT_TIMEZONE": "UTC"}
        self.assertTrue(self.due(datetime(2026, 11, 14, 0, 30, tzinfo=timezone.utc), **utc))

    def test_cycle_limit(self):
        self.close_cycle("2026-11-13T10:00:00Z")
        now = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
        self.assertFalse(self.due(now, AUDIT_TIME="", AUDIT_CYCLES_LIMIT="2"))
        self.close_cycle("2026-11-13T11:00:00Z")
        self.assertTrue(self.due(now, AUDIT_TIME="", AUDIT_CYCLES_LIMIT="2"))

    def test_either_trigger_can_be_disabled(self):  # R146
        for _ in range(3):
            self.close_cycle("2026-11-13T11:00:00Z")
        now = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
        self.assertFalse(self.due(now, AUDIT_TIME="", AUDIT_CYCLES_LIMIT="0"))
        self.assertTrue(self.due(now, AUDIT_TIME="", AUDIT_CYCLES_LIMIT="3"))
        self.assertTrue(self.due(now, AUDIT_TIME="07:00", AUDIT_TIMEZONE="UTC",
                                 AUDIT_CYCLES_LIMIT="0"))


if __name__ == "__main__":
    unittest.main()
