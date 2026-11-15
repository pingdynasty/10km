"""Requirement tests for the Auditor, Kickoff, Notification and Test Scripts
sections of REQUIREMENTS.md. Each test names the requirement IDs it checks.

Run: python3 -m unittest tests.test_requirements_auditor
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv  # noqa: E402  (test config, no caller env: tests/testenv.py)
from test_loop import LoopCase  # noqa: E402
from test_scripts import BIN, CODE, ScriptCase, wait_for  # noqa: E402
from tenkm import dispatch, notify, sessions  # noqa: E402

FAKE_AGENT = os.path.join(CODE, "tests", "fake-agent")


def close_cycle(m):
    m.db.execute("INSERT INTO cycles (id, status, planned_at, curated_at) "
                 "VALUES (1, 'closed', '2026-01-01T00:00:00Z', '2026-01-01T01:00:00Z')")


class TestAuditorLaunch(LoopCase):
    def due(self, **overrides):
        return self.reload(AUDIT_TIME="", AUDIT_CYCLES_LIMIT="1", **overrides)

    def test_auditor_is_launched_with_its_session_name_and_prompt(self):  # R260 R262
        self.start_loop()
        with self.m() as m:
            close_cycle(m)
        out = os.path.join(self.tmp.name, "env.txt")
        dispatch.run_pass(self.due(AUDITOR_AGENT=f'env > {out}; sleep 30'))
        with self.m() as m:
            [auditor] = [s for s in m.list("session") if s["role"] == "auditor"]
        self.assertTrue(wait_for(lambda: os.path.exists(out) and os.path.getsize(out) > 0))
        with open(out) as f:
            env = dict(line.split("=", 1) for line in f.read().splitlines() if "=" in line)
        self.assertEqual(env["SESSION"], auditor["name"])
        self.assertEqual(env["LOOP_SESSION"], auditor["name"])
        with open(env["PROMPT_FILE"]) as f:
            prompt = f.read()
        self.assertIn(f"Session: {auditor['name']}", prompt)
        with open(os.path.join(CODE, "prompts", "auditor.md")) as f:
            self.assertIn(f.read(), prompt)

    def test_no_auditor_until_the_previous_audit_is_curated(self):  # R282
        self.start_loop()
        with self.m() as m:
            close_cycle(m)
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
        with open(out + ".env") as f:
            env = dict(line.split("=", 1) for line in f.read().splitlines() if "=" in line)
        with open(out + ".msg") as f:
            return cwd, env, f.read()

    def test_kickoff_creates_the_database_and_runs_in_central_without_a_session(self):
        """R287 R289 R290: `10km kickoff` creates the database if there is none, then
        runs the operator's agent in the central loop worktree with no session, and
        does not start the loop."""
        os.remove(self.loop.db)
        cwd, env, message = self.kickoff()
        self.assertTrue(os.path.exists(self.loop.db))
        self.assertEqual(os.path.realpath(cwd), os.path.realpath(self.loop.repo("loop")))
        self.assertNotIn("LOOP_SESSION", env)
        self.assertNotIn("SESSION", env)
        self.assertEqual(self.loop.sessions(), [])
        self.assertTrue(self.loop.msm("loop", "get")["stopped"])
        self.assertIn("prompts/kickoff.md", message)

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
        """Launching agents, timing out sessions and escalating an agent that may still
        run are not notified; only fatal errors (see test_loop) are."""
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


@unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "needs bash and jq")
class TestFakeAgent(ScriptCase):
    def agent(self, name):
        """Run the fake agent as LOOP_AGENT would, for one session."""
        env = dict(SESSION=name, LOOP_SESSION=name,
                   PATH=os.pathsep.join([BIN, self.loop.env["PATH"]]))
        p = subprocess.run([FAKE_AGENT], env=dict(self.loop.env, **env), capture_output=True,
                           text=True, timeout=testenv.DEADLINE)
        self.assertExit(p, 0)

    def test_fake_agent_plays_each_role(self):
        """The fake agent (tests/fake-agent), run with its session, creates the cycle
        and finishes as Planner; reports and finishes as Worker; curates the cycle with
        a report and finishes as Curator."""
        self.loop.start()
        planner = self.loop.session("planner")["name"]
        self.agent(planner)
        self.assertEqual(self.loop.msm("session", "get", planner)["status"], "done")
        self.assertEqual([t["shortname"] for t in self.loop.msm("cycle", "get", "1")["tasks"]],
                         ["hello"])
        worker = self.loop.session("worker")["name"]
        self.agent(worker)
        task = self.loop.msm("task", "get", "--session", worker)
        self.assertEqual((task["status"], task["report"]), ("done", "added hello"))
        self.assertEqual(self.loop.msm("session", "get", worker)["status"], "done")
        curator = self.loop.session("curator")["name"]
        self.agent(curator)
        cycle = self.loop.msm("cycle", "get", "1")
        self.assertEqual((cycle["status"], cycle["report"]), ("closed", "smoke"))
        self.assertEqual(json.loads(json.dumps(cycle["tasks"]))[0]["status"], "accepted")


if __name__ == "__main__":
    unittest.main()
