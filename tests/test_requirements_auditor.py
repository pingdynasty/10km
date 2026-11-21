"""Requirement tests for the Auditor, Kickoff and Notification sections."""
import os
import signal
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv  # noqa: E402  (test config, no caller env: tests/testenv.py)
from test_loop import LoopCase  # noqa: E402
from test_scripts import ScriptCase  # noqa: E402
from tenkm import config, control, dispatch, notify, sessions  # noqa: E402


class TestAuditorLaunch(LoopCase):
    def due(self, **overrides):
        return self.reload(AUDIT_TIME="", AUDIT_CYCLES_LIMIT="1", **overrides)

    def test_auditor_is_launched_with_its_session_name_and_prompt(self):  # R6 R145 R260 R262
        self.start_loop()
        self.close_cycle()
        out = os.path.join(self.tmp.name, "env.txt")
        dispatch.run_pass(self.due(AUDITOR_AGENT=f'env > {out}.tmp; mv {out}.tmp {out}; sleep 30'))
        [auditor] = self.sessions("auditor")
        self.assertTrue(auditor["handle"].startswith("process:"))
        self.assertTrue(testenv.wait_for(lambda: os.path.exists(out)))
        env = testenv.read_env(out)
        self.assertEqual(env["SESSION"], auditor["name"])
        self.assertEqual(env["LOOP_SESSION"], auditor["name"])
        with open(env["PROMPT_FILE"]) as f:
            prompt = f.read()
        self.assertIn(f"Session: {auditor['name']}", prompt)
        with open(os.path.join(testenv.CODE, "prompts", "auditor.md")) as f:
            self.assertIn(f.read(), prompt)

    def test_no_auditor_until_the_previous_audit_is_curated(self):  # R282
        self.start_loop()
        self.close_cycle()
        first = sessions.create(self.cfg, "auditor")["name"]
        with self.m() as m:
            m.session_status(first, "done")
        dispatch.run_pass(self.due())
        with self.m() as m:
            auditors = [s["name"] for s in m.list("session") if s["role"] == "auditor"]
            curators = [s for s in m.list("session") if s["role"] == "curator"]
        self.assertEqual(auditors, [first])  # the done, uncurated audit blocks a new one
        self.assertEqual(len(curators), 1)   # and a Curator is launched to take it in
        sessions.remove(self.cfg, first)     # what curation does with it
        with self.m() as m:
            for c in curators:
                m.session_remove(c["name"])
        dispatch.run_pass(self.due())
        with self.m() as m:
            auditors = [s["name"] for s in m.list("session") if s["role"] == "auditor"]
        self.assertEqual(len(auditors), 1)
        self.assertNotEqual(auditors, [first])


class TestKickoff(ScriptCase):
    def kickoff(self, *message):
        """Run `10km kickoff` with an operator agent that records where and how it ran."""
        out = os.path.join(self.tmp, "kickoff")
        agent = (f'pwd > {out}.cwd; env > {out}.env; '
                 f'printf %s "${{FIRST_MESSAGE-}}" > {out}.msg')
        args = ["kickoff"] + (["--", *message] if message else [])
        p = self.loop.run("10km", *args, env={"OPERATOR_AGENT": agent})
        self.assertExit(p, 0)
        with open(out + ".cwd") as f:
            cwd = f.read().strip()
        return cwd, testenv.read_env(out + ".env"), testenv.read(out + ".msg")

    def test_kickoff_creates_the_database_and_runs_in_central_without_a_session(self):
        """R287 R289 R290."""
        os.remove(self.loop.db)
        cwd, env, message = self.kickoff()
        self.assertTrue(os.path.exists(self.loop.db))
        self.assertEqual(os.path.realpath(cwd), os.path.realpath(self.loop.repo("loop")))
        self.assertNotIn("LOOP_SESSION", env)
        self.assertNotIn("SESSION", env)
        self.assertEqual(self.loop.sessions(), [])
        self.assertTrue(self.loop.msm("loop", "get")["stopped"])
        self.assertIn("prompts/kickoff.md", message)

    def test_kickoff_leaves_the_loop_stopped_and_says_how_to_start(self):  # R296
        out = os.path.join(self.tmp, "kickoff")
        p = self.loop.run("10km", "kickoff", env={"OPERATOR_AGENT": f"true > {out}"})
        self.assertExit(p, 0)  # no terminal: it doesn't ask
        self.assertIn("`10km start`", p.stdout)
        self.assertTrue(self.loop.msm("loop", "get")["stopped"])

    def test_interactive_kickoff_offers_to_start(self):  # R296
        for answer, starts in (("", True), ("y", True), ("n", False), (EOFError, False)):
            def ask(prompt):
                self.assertIn("[Y/n]", prompt)
                if answer is EOFError:
                    raise EOFError
                return answer
            with mock.patch.object(control, "start", return_value=0) as start, \
                    mock.patch.dict(os.environ, self.loop.env):
                self.assertEqual(control.offer_start(config.load(), True, ask), 0)
            self.assertEqual(start.called, starts, answer)

    def test_kickoff_is_interactive_or_one_shot(self):  # R288
        _, env, _ = self.kickoff()
        self.assertNotIn("ONE_SHOT", env)
        _, env, message = self.kickoff("use", "defaults")
        self.assertEqual(env["ONE_SHOT"], "1")
        self.assertIn("use defaults", message)


class TestNotification(LoopCase):
    def test_notifications_file_is_gitignored(self):  # R299
        loop = self.cfg.repo_path("loop")
        notify.send(self.cfg, "Hello", "body")
        self.assertTrue(os.path.exists(os.path.join(loop, "NOTIFICATIONS.md")))
        p = subprocess.run(["git", "-C", loop, "check-ignore", "-q", "NOTIFICATIONS.md"])
        self.assertEqual(p.returncode, 0)
        status = subprocess.run(["git", "-C", loop, "status", "--porcelain"],
                                capture_output=True, text=True, check=True).stdout
        self.assertEqual(status, "")

    def test_routine_passes_notify_nothing(self):  # R300
        """Launches, time-outs and escalations are not notified (fatal errors are:
        test_loop.TestDispatch)."""
        self.start_loop()
        dispatch.run_pass(self.cfg)
        with self.m() as m:
            [s] = [s for s in m.list("session") if s["role"] == "curator"]
            m.session_update(s["name"], {"handle": "nosuch:x"})
        os.killpg(int(s["handle"].split(":")[1]), signal.SIGKILL)  # no launcher can now
        dispatch.run_pass(self.reload(CURATOR_TIMEOUT="-1", LOOP_AGENT=""))
        with self.m() as m:
            self.assertTrue(any(i["severity"] == "high" for i in m.list("issue")))
        self.assertFalse(os.path.exists(os.path.join(self.cfg.central, "loop",
                                                     "NOTIFICATIONS.md")))


if __name__ == "__main__":
    unittest.main()
