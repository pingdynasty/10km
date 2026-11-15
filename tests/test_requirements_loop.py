"""Requirements on scripts, repos and configuration not covered elsewhere."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta, timezone

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
        # Inactive sessions now read "<name>  done <time>  <ago>" and the answered
        # count "Answered issues" (operator request, backlog 3e2f9550).
        for expected in ("Loop: running, phase plan, cycle 0", f"{op}  done ",
                         "Open escalations: 1", "[blocking] help",
                         "Answered issues: 1",
                         "[escalation] which way  -> operator", "\nproject "):
            self.assertIn(expected, text)
        self.assertNotIn("empty cycles in a row", text)

    def test_report_times_are_local_and_elapsed(self):  # R10
        """Fixed clock and zone: the target output of backlog 3e2f9550."""
        op = self.start_loop()
        with self.m() as m:
            planner = "cycle1-planner-48y3tkot"
            m.db.execute("INSERT INTO sessions (name, role, cycle, status, handle, created_at, "
                         "updated_at) VALUES (?, 'planner', 1, 'active', ?, ?, ?)",
                         (planner, "process:20940:Sun Nov 15 19:47:11 2026",
                          "2026-11-15T18:47:00Z", "2026-11-15T18:47:00Z"))
            m.cycle_create({"headline": "PH1: DEL2 and DEL3",
                            "tasks": [{"shortname": "msm-fixes", "instructions": "x",
                                       "branch": planner}]})
            audit = m.create("audit", {"period": {"from": 1, "to": 1}, "summary": "s"})
            m.db.execute("UPDATE cycles SET planned_at = '2026-11-15T18:35:00Z'")
            m.db.execute("UPDATE sessions SET updated_at = '2026-11-14T22:05:00Z' "
                         "WHERE name = ?", (op,))
            m.db.execute("UPDATE audits SET created_at = '2025-11-14T22:05:00Z' WHERE id = ?",
                         (audit["id"],))
            m.db.execute("UPDATE loop SET empty_cycles = 1")
        project = self.cfg.repo_path("project")
        env = dict(os.environ, GIT_COMMITTER_DATE="2026-11-15T17:53:10Z",
                   GIT_AUTHOR_DATE="2026-11-15T17:53:10Z")
        subprocess.run(["git", "-C", project, "commit", "-q", "--allow-empty", "-m",
                        "Metrics: skip control characters"], env=env, check=True)
        text = status.report(self.cfg, now="2026-11-15T18:47:10Z",
                             tz=timezone(timedelta(hours=1), "CET"))
        lines = text.splitlines()
        self.assertEqual(lines[0], "project loop, Nov 15 19:47 CET")
        self.assertEqual(lines[1], "Loop: running, phase plan, cycle 1, "
                                   "1 empty cycle in a row")
        self.assertIn("Cycle 1 (open, planned 19:35, 12m ago):\n  PH1: DEL2 and DEL3\n"
                      "  waiting  msm-fixes", text)
        self.assertRegex(text, rf"\n  {planner}\s+since 19:47\s+10s\s+pid 20940\n")
        self.assertRegex(text, rf"\n  {op}\s+done Nov 14 23:05\s+20h42m ago\n")
        self.assertIn("Audits: 1, last Nov 14 2025 23:05, 365d20h ago", text)
        self.assertRegex(text, r"\nRepository\s+Branch\s+Commit\s+When\s+Message\n")
        self.assertRegex(text, r"\nproject\s+main\s+[0-9a-f]{7,}\s+54m ago\s+"
                               r"Metrics: skip control characters")
        self.assertNotIn("Main:", text)

    def test_report_replaces_terminal_escapes(self):  # R10
        self.start_loop()
        with self.m() as m:
            m.create("issue", {"type": "escalation", "title": "red \x1b[31m\x07",
                               "assignee_role": "operator"})
        subprocess.run(["git", "-C", self.cfg.repo_path("project"), "commit", "-q",
                        "--allow-empty", "-m", "clear \x1b[2J"], check=True)
        text = status.report(self.cfg)
        self.assertIn("red ?[31m?", text)
        self.assertIn("clear ?[2J", text)
        self.assertNotIn("\x1b", text)

    def test_empty_cycles_plural(self):  # R10
        self.start_loop()
        with self.m() as m:
            m.db.execute("UPDATE loop SET empty_cycles = 3")
        self.assertIn("cycle 0, 3 empty cycles in a row", status.report(self.cfg))


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
