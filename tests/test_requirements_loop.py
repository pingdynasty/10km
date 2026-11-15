"""Requirements on scripts, repos and configuration not covered elsewhere."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv  # noqa: E402  (test config, no caller env: tests/testenv.py)
from test_loop import LoopCase  # noqa: E402
from tenkm import config, sessions, status  # noqa: E402


class TestStatus(LoopCase):
    def test_report_shows_loop_cycle_sessions_and_issues(self):  # R10
        op = self.start_loop()
        with self.m() as m:
            m.create("issue", {"type": "escalation", "title": "help", "severity": "blocking",
                               "assignee_role": "operator"})
            answered = m.create("issue", {"type": "escalation", "title": "which way",
                                          "assignee_role": "operator"})
            m.update("issue", answered["id"], {"status": "answered", "resolution": "left"})
        text = status.report(self.cfg)
        for expected in ("Loop: running, phase plan, cycle 0", f"{op} (done)",
                         "Open escalations: 1", "[blocking] help",
                         "Answered issues, awaiting follow-up: 1",
                         "[escalation] which way  -> operator", "project:"):
            self.assertIn(expected, text)


class TestCentralConfig(LoopCase):
    def test_scripts_read_config_env_from_the_central_loop_worktree(self):  # R14 R15
        path = os.path.join(self.cfg.central, "loop", "config.env")
        with open(path, "a") as f:
            f.write('TENKM_TEST_SETTING="from central"\n')
        self.assertEqual(config.load()["TENKM_TEST_SETTING"], "from central")
        os.environ.pop("LOOP_CONFIG")  # as the loop runs; LoopCase restores it
        self.assertEqual(config.load()["LOOP_CONFIG_PATH"], path)
        self.assertEqual(config.load()["TENKM_TEST_SETTING"], "from central")

    def test_agent_command_per_role_falls_back_to_loop_agent(self):  # R28
        cfg = self.reload(LOOP_AGENT="loop-agent", WORKER_AGENT="worker-agent",
                          OPERATOR_AGENT="operator-agent")
        self.assertEqual([cfg.agent_command(r) for r in ("worker", "planner", "operator")],
                         ["worker-agent", "loop-agent", "operator-agent"])


class TestStatePaths(unittest.TestCase):
    def test_database_and_action_log_are_at_the_configured_paths(self):  # R13 R27
        with tempfile.TemporaryDirectory() as tmp:
            root, state = os.path.join(tmp, "root"), os.path.join(tmp, "state")
            os.makedirs(root)
            env = dict(os.environ, LOOP_ROOT=root, MSM_DB=os.path.join(state, "x.db"))

            def msm(*args, **extra):
                subprocess.run([os.path.join(testenv.BIN, "msm"), *args], env=dict(env, **extra),
                               check=True, capture_output=True)

            msm("init")
            msm("issue", "create", '{"type": "backlog", "title": "t"}')
            self.assertEqual(os.listdir(root), [])
            self.assertIn("x.db", os.listdir(state))
            with open(os.path.join(state, "actions.log")) as f:
                line = json.loads(f.read().splitlines()[-1])
            self.assertEqual((line["command"], line["session"]), ("issue create", None))
            self.assertRegex(line["at"], r"^\d{4}-\d\d-\d\dT")
            log = os.path.join(tmp, "elsewhere.log")
            msm("issue", "create", '{"type": "backlog", "title": "u"}', MSM_LOG=log)
            self.assertTrue(os.path.exists(log))


class TestCommitTrailer(LoopCase):
    def test_commits_carry_a_loop_session_trailer(self):  # R24 R25
        name = sessions.create(self.cfg, "operator", "mars")["name"]
        wt = os.path.join(self.root, name, "project")
        trailers = []
        for extra in ({}, {"LOOP_SESSION": "cycle9-worker1-abcdefgh"}):
            subprocess.run(["git", "-C", wt, "commit", "-q", "--allow-empty", "-m", "change"],
                           check=True, env=dict(os.environ, **extra))
            trailers.append(subprocess.run(
                ["git", "-C", wt, "log", "-1", "--format=%(trailers:key=Loop-Session,valueonly)"],
                check=True, capture_output=True, text=True).stdout.strip())
        self.assertEqual(trailers, [name, "cycle9-worker1-abcdefgh"])


if __name__ == "__main__":
    unittest.main()
