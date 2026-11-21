"""Requirements on sessions, the Dispatcher, session time-out and resume not
covered elsewhere."""
import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv  # noqa: E402  (test config, no caller env: tests/testenv.py)
from testenv import BIN, SUFFIX, wait_for  # noqa: E402
from test_curate_scripts import CurateScriptCase  # noqa: E402
from test_loop import LoopCase  # noqa: E402
from test_scripts import ScriptCase  # noqa: E402
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
    def test_run_loop_dispatches_every_interval(self):  # R136
        """Each pass logs when it starts: passes keep coming, at least the interval
        apart. Waits on the passes, so a loaded host only makes it slower."""
        log = os.path.join(self.tmp, "passes.log")
        fake = os.path.join(self.loop.central, "loop", "bin", "dispatch")
        with open(fake, "w") as f:
            f.write(f"#!{sys.executable}\nimport time\n"
                    f"with open({log!r}, 'a') as f:\n    f.write(f'{{time.time()}}\\n')\n")
        os.chmod(fake, 0o755)
        p = subprocess.Popen([os.path.join(BIN, "run-loop")], start_new_session=True,
                             env=dict(self.loop.env, DISPATCH_INTERVAL="0.2"),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        def passes():
            try:
                with open(log) as f:
                    return [float(t) for t in f.read().split()]
            except (OSError, ValueError):  # not written yet, or mid-write
                return []
        try:
            self.assertTrue(testenv.wait_for(lambda: len(passes()) >= 3, interval=0.05))
        finally:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()
        starts = passes()
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        self.assertGreaterEqual(min(gaps), 0.2, gaps)  # sleeps the interval between passes

    def test_done_auditor_gets_a_curator_in_the_execute_phase(self):  # R140
        self.loop.start()
        self.loop.plan("a")
        auditor = self.loop.session("auditor")["name"]
        self.loop.done(auditor)
        self.dispatch(MAX_CONCURRENT_AGENTS="1")  # the Curator only
        self.assertEqual(self.loop.msm("loop", "get")["phase"], "execute")
        self.assertEqual(len(self.loop.active("curator")), 1)

    def test_curate_phase_launches_a_curator_without_waiting(self):  # R143 R167 R122
        self.loop.start()
        self.loop.plan()  # an empty cycle goes straight to curate
        self.assertEqual(self.loop.msm("loop", "get")["phase"], "curate")
        self.loop.session("operator", "mars")
        self.loop.session("auditor")
        self.dispatch()
        [curator] = self.loop.active("curator")
        self.assertRegex(curator["name"], rf"^cycle1-curator-{SUFFIX}$")
        self.assertTrue(curator["handle"].startswith("process:"))
        self.assertEqual(self.loop.active("planner") + self.loop.active("worker"), [])

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
            def create(cfg, role, username=None, setup=None):
                calls.append(role)
                if len(calls) <= times:
                    raise sessions.SessionError(sessions.EAGAIN, "taken")
                return real(cfg, role, username, setup)
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


class TestCuratorCrash(CurateScriptCase):
    def test_a_pass_cut_short_is_redone_by_the_next_curator(self):  # R164 R165
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


class TestLoopControl(ScriptCase):
    """`10km start|pause|resume|stop` and the Dispatcher heartbeat."""

    settings = {"DISPATCH_INTERVAL": "1"}

    def runner(self):
        """The running run-loop's pid, or None."""
        from tenkm import config, runloop
        return runloop.running(config.load(self.loop.root))

    def setUp(self):
        super().setUp()
        self.addCleanup(self.kill_runner)

    def kill_runner(self):
        pid = self.runner()
        if pid:
            os.kill(pid, signal.SIGKILL)

    def heartbeat(self):
        return testenv.read(os.path.join(self.loop.root, ".10km", "dispatch.json"))

    def test_start_runs_one_run_loop_and_stop_ends_it(self):  # R331 R332 R335
        self.loop.start()
        self.loop.msm("loop", "stop", "operator")
        p = self.loop.run("10km", "start")
        self.assertExit(p, 0)
        self.assertIn("run-loop started", p.stdout)
        self.assertFalse(self.loop.msm("loop", "get")["stopped"])  # resumed
        pid = self.runner()
        self.assertTrue(pid)
        self.assertTrue(wait_for(lambda: "run-loop started" in (testenv.read(
            os.path.join(self.loop.root, ".10km", "run-loop.log")) or "")))
        p = self.loop.run("10km", "start")
        self.assertIn(f"already running (pid {pid})", p.stdout)
        self.assertExit(self.loop.run("run-loop"), 1)  # R332: one per loop
        self.assertEqual(self.runner(), pid)
        p = self.loop.run("10km", "stop")
        self.assertExit(p, 0)
        self.assertIsNone(self.runner())
        loop = self.loop.msm("loop", "get")
        self.assertEqual((loop["stopped"], loop["reason"]), (1, "stopped by the operator"))

    def test_start_starts_a_loop_that_never_started(self):  # R331
        self.assertExit(self.loop.run("10km", "resume"), 1)  # nothing to resume yet
        p = self.loop.run("10km", "start")
        self.assertExit(p, 0)
        self.assertIn("the first Planner runs", p.stdout)
        loop = self.loop.msm("loop", "get")
        self.assertEqual((loop["stopped"], loop["phase"]), (0, "plan"))
        self.assertTrue(self.runner())

    def test_start_initialises_a_loop_that_never_ran(self):  # R342
        os.remove(self.loop.db)
        p = self.loop.run("10km", "start")
        self.assertExit(p, 0)
        self.assertIn("Initialised the loop", p.stdout)
        self.assertEqual(self.loop.msm("loop", "get")["phase"], "plan")

    def test_start_refuses_a_missing_database_of_a_loop_that_ran(self):  # R342
        self.dispatch()  # a heartbeat
        os.remove(self.loop.db)
        p = self.loop.run("10km", "start")
        self.assertExit(p, 1)
        self.assertIn("has run before", p.stderr)
        self.assertFalse(os.path.exists(self.loop.db))
        self.assertIsNone(self.runner())

    def test_pause_keeps_run_loop_and_resume_continues(self):  # R333 R334
        self.loop.start()
        self.loop.ok("10km", "start")
        pid = self.runner()
        p = self.loop.run("10km", "pause", "for", "lunch")
        self.assertExit(p, 0)
        loop = self.loop.msm("loop", "get")
        self.assertEqual((loop["stopped"], loop["reason"]), (1, "for lunch"))
        self.assertEqual(self.runner(), pid)
        self.loop.ok("10km", "pause")  # an earlier reason is kept
        self.assertEqual(self.loop.msm("loop", "get")["reason"], "for lunch")
        self.assertExit(self.loop.run("10km", "resume"), 0)
        self.assertFalse(self.loop.msm("loop", "get")["stopped"])

    def test_resume_is_refused_while_a_blocking_escalation_is_open(self):  # R334 R313
        self.loop.start()
        self.loop.msm("issue", "create", '{"type": "escalation", "title": "ESC1: help", '
                      '"assignee_role": "operator", "severity": "blocking"}')
        self.loop.msm("loop", "stop", "blocked")
        self.assertExit(self.loop.run("10km", "resume"), 2)  # EPERM
        self.assertTrue(self.loop.msm("loop", "get")["stopped"])

    def test_without_now_agents_run_on(self):  # R336
        self.loop.start()
        self.dispatch()
        self.assertEqual([s["role"] for s in self.loop.active()], ["planner"])
        self.loop.ok("10km", "pause")
        self.assertEqual([s["role"] for s in self.loop.active()], ["planner"])

    def test_now_stops_agents_and_gate_runs(self):  # R336
        self.loop.start()
        op = self.loop.session("operator", "mars")["name"]
        self.dispatch()
        planner = self.loop.active("planner")[0]
        gate_run = subprocess.Popen(["sleep", "600"], start_new_session=True)
        self.addCleanup(gate_run.kill)
        from tenkm.launchers import process
        evidence = os.path.join(self.loop.root, ".10km", "evidence")
        os.makedirs(evidence, exist_ok=True)
        with open(os.path.join(evidence, "running-x.json"), "w") as f:
            json.dump({"pgid": gate_run.pid, "started": process._ps(gate_run.pid, "lstart"),
                       "rc": os.path.join(evidence, "x.rc"), "log": "x.log"}, f)
        p = self.loop.run("10km", "pause", "--now")
        self.assertExit(p, 0)
        self.assertIn("Stopped 1 agent", p.stdout)
        self.assertIn("1 gate run", p.stdout)
        status = {s["name"]: s["status"] for s in self.loop.sessions()}
        self.assertEqual((status[planner["name"]], status[op]), ("expired", "active"))
        self.assertFalse(process.alive(None, planner["handle"]))
        self.assertIsNotNone(gate_run.wait(timeout=testenv.DEADLINE))

    def test_status_reports_the_last_pass_and_overdue_passes(self):  # R337
        self.loop.start()
        self.assertIn("Dispatcher: no pass recorded; OVERDUE", self.loop.ok("10km", "status"))
        self.dispatch()
        beat = json.loads(self.heartbeat())
        self.assertEqual(beat["result"], "ok")
        text = self.loop.ok("10km", "status")
        self.assertIn("Dispatcher: last pass", text)
        self.assertNotIn("OVERDUE", text)
        beat["finished_at"] = "2026-01-01T00:00:00Z"
        with open(os.path.join(self.loop.root, ".10km", "dispatch.json"), "w") as f:
            json.dump(beat, f)
        self.assertIn("OVERDUE", self.loop.ok("10km", "status"))
        self.loop.msm("loop", "stop", "operator")
        self.assertNotIn("OVERDUE", self.loop.ok("10km", "status"))  # stopped: not due


if __name__ == "__main__":
    unittest.main()
