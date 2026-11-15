"""Requirements on scripts, repos and configuration (REQUIREMENTS.md, Scripts and
Actions; Git Repositories and File System) not covered elsewhere. Each test names
the IDs it checks.

Run: python3 -m unittest discover tests
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv  # noqa: E402,F401  (test config, no caller env: tests/testenv.py)
from test_curate import CurateCase  # noqa: E402
from test_loop import LoopCase  # noqa: E402
from tenkm import config, curate, dispatch, sessions, status  # noqa: E402

BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")


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
        self.assertEqual(config.load()["TENKM_TEST_SETTING"], "from central")  # via the test config
        os.environ.pop("LOOP_CONFIG")  # without it, as the loop runs (LoopCase restores it)
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
            env.pop("LOOP_SESSION", None)
            env.pop("MSM_LOG", None)

            def msm(*args, **extra):
                subprocess.run([os.path.join(BIN, "msm"), *args], env=dict(env, **extra),
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
    # Keep host git config (e.g. a system core.hooksPath) out of the test loop.
    env = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}

    def test_commits_carry_a_loop_session_trailer(self):  # R24 R25
        name = sessions.create(self.cfg, "operator", "mars")["name"]
        wt = os.path.join(self.root, name, "project")
        trailers = []
        for extra in ({}, {"LOOP_SESSION": "cycle9-worker1-abcdefgh"}):
            env = {k: v for k, v in os.environ.items() if k != "LOOP_SESSION"}
            env.update(extra)
            subprocess.run(["git", "-C", wt, "commit", "-q", "--allow-empty", "-m", "change"],
                           check=True, env=env)
            trailers.append(subprocess.run(
                ["git", "-C", wt, "log", "-1", "--format=%(trailers:key=Loop-Session,valueonly)"],
                check=True, capture_output=True, text=True).stdout.strip())
        self.assertEqual(trailers, [name, "cycle9-worker1-abcdefgh"])


class TestCuratorCleanup(CurateCase):
    def test_curated_sessions_leave_no_branch_or_worktree(self):  # R20 R22
        op = sessions.create(self.cfg, "operator", "mars")["name"]
        self.commit(op, "project", "goal.txt", "hello")
        with self.m() as m:
            m.session_status(op, "done")
            m.loop_start()
        cur = self.curator()
        with self.as_session(cur):
            curate.prepare(self.cfg)
            curate.select(self.cfg)
            curate.merge(self.cfg, [op])
            curate.publish(self.cfg)
            curate.cleanup(self.cfg)
        self.assertEqual(self.central("project", "goal.txt"), "hello")
        self.assertFalse(os.path.exists(os.path.join(self.root, op)))
        for repo in self.cfg.repos():
            branches = subprocess.run(
                ["git", "-C", self.cfg.repo_path(repo), "branch", "--format=%(refname:short)"],
                check=True, capture_output=True, text=True).stdout.split()
            self.assertNotIn(op, branches)
            worktrees = subprocess.run(["git", "-C", self.cfg.repo_path(repo), "worktree", "list"],
                                       check=True, capture_output=True, text=True).stdout
            self.assertNotIn(op, worktrees)


class TestDispatchRoles(LoopCase):
    def test_dispatcher_launches_an_auditor_when_due(self):  # R6
        self.start_loop()
        with self.m() as m:
            m.db.execute("INSERT INTO cycles (id, status, planned_at, curated_at) "
                         "VALUES (1, 'closed', '2026-01-01T00:00:00Z', '2026-01-01T01:00:00Z')")
        dispatch.run_pass(self.reload(AUDIT_TIME="", AUDIT_CYCLES_LIMIT="1"))
        with self.m() as m:
            roles = {s["role"]: s for s in m.list("session") if s["status"] == "active"}
        self.assertIn("auditor", roles)
        self.assertTrue(roles["auditor"]["handle"].startswith("process:"))
        self.assertTrue(os.path.exists(os.path.join(roles["auditor"]["working_directory"],
                                                    "prompt.txt")))


if __name__ == "__main__":
    unittest.main()
