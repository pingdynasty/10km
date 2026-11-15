"""Requirements on sessions, the Dispatcher, session time-out and resume
(REQUIREMENTS.md, Sessions; Dispatcher) not covered elsewhere. Each test names
the IDs it checks.

Run: python3 -m unittest discover tests
"""
import fcntl
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv  # noqa: E402  (test config, no caller env: tests/testenv.py)
from test_curate_scripts import CurateScriptCase  # noqa: E402
from test_loop import LoopCase  # noqa: E402
from test_scripts import BIN, SUFFIX, ScriptCase, wait_for  # noqa: E402
from tenkm import dispatch, sessions  # noqa: E402


class TestSessionScriptRules(ScriptCase):
    def test_creation_waits_for_the_session_lock(self):  # R128
        state = os.path.join(self.loop.root, ".10km")
        os.makedirs(state, exist_ok=True)
        with open(os.path.join(state, "session.lock"), "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            p = subprocess.Popen([os.path.join(BIN, "session"), "operator", "mars"],
                                 env=self.loop.env, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            self.addCleanup(p.kill)
            time.sleep(1)
            self.assertIsNone(p.poll())  # blocked on the lock
            self.assertEqual(self.loop.sessions(), [])
        self.assertEqual(p.wait(timeout=testenv.DEADLINE), 0)
        self.assertEqual([s["role"] for s in self.loop.sessions()], ["operator"])

    def test_done_or_expired_sessions_are_inactive(self):  # R120
        self.loop.start()
        op = self.loop.session("operator", "mars")["name"]
        self.assertError(self.loop.run("session", "curator"), 2)  # active: not curatable
        self.loop.msm("session", "expired", op)
        self.loop.session("curator")  # expired counts as inactive work to curate

    def test_operator_sessions_are_interactive_or_one_shot(self):  # R127
        agent = 'printf "%s|%s" "${ONE_SHOT-}" "${FIRST_MESSAGE-}" > "../$SESSION.out"'
        seen = []
        for message in ([], ["--", "do", "this"]):
            p = self.loop.run("10km", "session", "start", "mars", *message,
                              env={"OPERATOR_AGENT": agent})
            self.assertExit(p, 0)
            name = p.stdout.split()[1]
            with open(os.path.join(self.loop.root, name, f"{name}.out")) as f:
                seen.append(f.read().split("|", 1))
        self.assertEqual([one_shot for one_shot, _ in seen], ["", "1"])
        for _, first_message in seen:
            self.assertIn("prompts/session.md", first_message)
        self.assertNotIn("do this", seen[0][1])
        self.assertIn("do this", seen[1][1])

    def test_sessions_not_launched_by_the_dispatcher_have_no_handle(self):  # R160
        self.loop.start()
        names = [self.loop.session("operator", "mars")["name"],
                 self.loop.session("planner")["name"]]
        self.loop.ok("dispatch", env={"START_GRACE": "0"})
        for name in names:
            s = self.loop.msm("session", "get", name)
            self.assertEqual((s.get("handle"), s["status"]), (None, "active"))


class TestDispatchRules(ScriptCase):
    def dispatch(self, **env):
        p = self.loop.run("dispatch", env=env)
        self.assertExit(p, 0)
        return p.stdout

    def active(self, role):
        return [s for s in self.loop.sessions(role) if s["status"] == "active"]

    def test_run_loop_dispatches_every_interval(self):  # R136
        log = os.path.join(self.tmp, "passes.log")
        fake = os.path.join(self.loop.central, "loop", "bin", "dispatch")
        with open(fake, "w") as f:
            f.write(f"#!/bin/sh\necho pass >> '{log}'\n")
        os.chmod(fake, 0o755)
        p = subprocess.Popen([os.path.join(BIN, "run-loop")], start_new_session=True,
                             env=dict(self.loop.env, DISPATCH_INTERVAL="0.2"),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(1.5)
        finally:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()
        with open(log) as f:
            passes = len(f.read().split())
        self.assertGreaterEqual(passes, 3)
        self.assertLessEqual(passes, 9)

    def test_done_auditor_gets_a_curator_in_the_execute_phase(self):  # R140
        self.loop.start()
        self.loop.plan("a")
        auditor = self.loop.session("auditor")["name"]
        self.loop.done(auditor)
        self.dispatch(MAX_WORKERS="0")
        self.assertEqual(self.loop.msm("loop", "get")["phase"], "execute")
        self.assertEqual(len(self.active("curator")), 1)

    def test_curate_phase_launches_a_curator_without_waiting(self):  # R143 R167 R122
        self.loop.start()
        self.loop.plan()  # an empty cycle goes straight to curate
        self.assertEqual(self.loop.msm("loop", "get")["phase"], "curate")
        self.loop.session("operator", "mars")
        self.loop.session("auditor")
        self.dispatch()
        [curator] = self.active("curator")
        self.assertRegex(curator["name"], rf"^cycle1-curator-{SUFFIX}$")
        self.assertTrue(curator["handle"].startswith("process:"))
        self.assertEqual(self.active("planner") + self.active("worker"), [])

    def test_operator_sessions_never_time_out(self):  # R156
        self.loop.start()
        op = self.loop.session("operator", "mars")["name"]
        for _ in range(2):
            self.dispatch(SESSION_TIMEOUT="-1", OPERATOR_TIMEOUT="-1")
        self.assertEqual(self.loop.msm("session", "get", op)["status"], "active")
        self.assertFalse(any(op in i["title"] for i in self.loop.msm("issue", "list")))
        self.assertTrue(any(s["status"] == "expired" for s in self.loop.sessions("planner")))


class TestLaunching(LoopCase):
    def test_taken_branch_name_is_tried_three_times(self):  # R148 R149
        self.start_loop()
        real = sessions.create
        calls = []

        def taken(times):
            def create(cfg, role, username=None):
                calls.append(role)
                if len(calls) <= times:
                    raise sessions.SessionError(sessions.EAGAIN, "taken")
                return real(cfg, role, username)
            return create

        with mock.patch.object(sessions, "create", taken(3)):
            self.assertFalse(dispatch.Pass(self.cfg).launch("curator"))
        self.assertEqual(calls, ["curator"] * 3)
        calls.clear()
        with mock.patch.object(sessions, "create", taken(2)):
            self.assertTrue(dispatch.Pass(self.cfg).launch("curator"))
        self.assertEqual(len(calls), 3)

    def test_launcher_is_configured_for_the_loop(self):  # R152
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        package = os.path.join(tmp, "tenkm_test_launchers")
        os.makedirs(package)
        open(os.path.join(package, "__init__.py"), "w").close()
        with open(os.path.join(package, "fake.py"), "w") as f:
            f.write("def launch(cfg, session, role, env, log_path):\n"
                    "    return 'fake:' + role\n"
                    "def alive(cfg, handle):\n    return True\n"
                    "def stop(cfg, handle):\n    return True\n")
        sys.path.insert(0, tmp)
        self.addCleanup(sys.path.remove, tmp)
        self.addCleanup(sys.modules.pop, "tenkm_test_launchers.fake", None)
        self.addCleanup(sys.modules.pop, "tenkm_test_launchers", None)
        self.start_loop()
        dispatch.run_pass(self.reload(LAUNCHER="tenkm_test_launchers.fake"))
        with self.m() as m:
            [curator] = [s for s in m.list("session") if s["role"] == "curator"]
        self.assertEqual(curator["handle"], "fake:curator")


class TestAuditorTriggers(LoopCase):
    def due(self, now, **overrides):
        p = dispatch.Pass(self.reload(**overrides), now=now)
        with self.m() as m:
            return p.auditor_due(m)

    def test_either_trigger_can_be_disabled(self):  # R146
        with self.m() as m:
            for i in (1, 2, 3):
                m.db.execute("INSERT INTO cycles (id, status, planned_at, curated_at) "
                             "VALUES (?, 'closed', '2026-11-13T10:00:00Z', "
                             "'2026-11-13T11:00:00Z')", (i,))
        now = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
        self.assertFalse(self.due(now, AUDIT_TIME="", AUDIT_CYCLES_LIMIT="0"))
        self.assertTrue(self.due(now, AUDIT_TIME="", AUDIT_CYCLES_LIMIT="3"))
        self.assertTrue(self.due(now, AUDIT_TIME="07:00", AUDIT_TIMEZONE="UTC",
                                 AUDIT_CYCLES_LIMIT="0"))


class TestCuratorCrash(CurateScriptCase):
    def test_a_pass_cut_short_is_redone_by_the_next_curator(self):  # R164 R165
        """Before Publish: main is unchanged and the next Curator redoes the pass.
        After Publish: the next Curator's pass selects nothing and changes nothing."""
        planner, (w1,) = self.cycle(("a.txt", "a"))
        before = self.main("project")
        first = self.curator()
        self.step_ok(first, "select")
        self.step_ok(first, "merge", planner, w1)
        self.loop.msm("session", "expired", first)
        self.assertEqual(self.main("project"), before)
        second = self.curator()
        self.assertEqual({s["name"] for s in self.step_ok(second, "select")}, {planner, w1})
        self.step_ok(second, "merge", planner, w1)
        self.step_ok(second, "publish", "--report", "r", "--accepted", w1)
        self.assertEqual(self.central("project", "a.txt"), "a")
        self.loop.msm("session", "expired", second)
        published = (self.main("loop"), self.main("project"))
        third = self.curator()
        self.assertEqual(self.step_ok(third, "select"), [])
        self.step_ok(third, "merge")
        self.step_ok(third, "publish")
        self.assertEqual((self.main("loop"), self.main("project")), published)
        self.assertEqual(self.tasks()[w1], "accepted")


if __name__ == "__main__":
    unittest.main()
