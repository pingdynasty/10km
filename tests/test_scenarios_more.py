"""More end-to-end scenarios with the fake agent; see tests/test_scenarios.py."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv  # noqa: E402  (test config, no caller env: tests/testenv.py)
from test_scenarios import ScenarioCase  # noqa: E402


class TestIdleStop(ScenarioCase):
    def test_idle_limit_of_empty_cycles_stops_the_loop(self):
        """R72, R109, R111, R247, R258, R76, R139."""
        settings = dict(FAKE_TASKS="", IDLE_CYCLE_LIMIT="2")
        self.loop.start()
        self.drive(lambda: self.loop_state()["stopped"], **settings)
        loop = self.loop.msm("loop", "get")
        self.assertEqual((loop["reason"], loop["empty_cycles"], loop["current_cycle"]),
                         ("idle", 2, 2))
        self.assertEqual([c["status"] for c in self.cycles()], ["closed", "closed"])
        self.assertEqual(self.loop.msm("task", "list"), [])
        escalations = self.loop.msm("issue", "list", '{"type": "escalation"}')
        self.assertEqual(len(escalations), 1, escalations)
        issue = escalations[0]
        self.assertEqual((issue["assignee_role"], issue["severity"], issue["status"]),
                         ("operator", "blocking", "open"))
        self.assertTrue(issue["title"].startswith("idle"), issue["title"])
        for _ in range(3):  # stopped: nothing is launched
            self.dispatch(**settings)
        self.assertEqual(self.active(), [])
        self.assertEqual(len(self.cycles()), 2)


class TestOffPhaseCurator(ScenarioCase):
    def test_done_auditor_and_operator_work_is_curated_outside_the_curate_phase(self):
        """R145, R140, R91, R212, R167, R250, R256, R111."""
        settings = dict(AUDIT_CYCLES_LIMIT="1", FAKE_CYCLE2_WORKER1="hang",
                        WORKER_TIMEOUT="3600")
        self.loop.start()
        self.drive(lambda: not self.sessions("auditor")
                   and "smoke learning" in (self.show("main", "LEARNINGS.md", "loop") or ""),
                   **settings)
        self.assertEqual(self.loop.msm("loop", "get")["last_audit"], 1)
        self.assertEqual(len(self.loop.msm("audit", "list")), 1)
        loop = self.loop.msm("loop", "get")
        self.assertNotEqual(loop["phase"], "curate")
        self.assertEqual(loop["current_cycle"], 2)
        self.assertEqual([c["status"] for c in self.cycles()], ["closed", "open"])
        self.drive(lambda: len(self.active("worker")) == 1, **settings)
        operator = self.loop.session("operator", "mars")["name"]
        self.loop.commit(operator, "project", "op.txt", "op")
        self.loop.done(operator)
        self.drive(lambda: operator not in [s["name"] for s in self.sessions()]
                   and self.on_main("op.txt"), **settings)
        self.assertEqual(self.show("main", "op.txt"), "op")
        loop = self.loop.msm("loop", "get")
        self.assertEqual((loop["phase"], loop["current_cycle"]), ("execute", 2))
        self.assertEqual([c["status"] for c in self.cycles()], ["closed", "open"])
        self.assertEqual(self.tasks(2)["hello"]["status"], "active")
        self.assertEqual(len(self.active("worker")), 1)
        curators = self.loop.sessions("curator")
        self.assertEqual([c["status"] for c in curators], ["done"], self.state())


class TestTwoProjectRepos(ScenarioCase):
    def setUp(self):
        super().setUp()
        testenv.project_repo(self.loop.repo("project2"))
        self.loop.ok("init")

    def test_worker_commits_in_both_repos_are_merged(self):
        """R11, R16, R23, R117, R118, R125, R217, R250, R255, R256, R20."""
        self.loop.start()
        self.drive(self.cycle_planned(2), FAKE_TASKS="a b", MAX_WORKERS="2")
        tasks = self.tasks(1)
        self.assertEqual({k: t["status"] for k, t in tasks.items()},
                         {"a": "accepted", "b": "accepted"})
        for repo in ("project", "project2"):
            self.assertEqual((self.show("main", "a.txt", repo), self.show("main", "b.txt", repo)),
                             ("a", "b"), repo)
            for t in tasks.values():
                self.assertNotIn(t["session"], self.loop.branches(repo))
            self.assertTrue(os.path.exists(os.path.join(self.loop.repo(repo), "b.txt")), repo)
        for repo in ("loop", "project", "project2"):  # the cycle 2 Planner's worktrees
            planner = self.cycles()[1]["planner_session"]
            self.assertTrue(os.path.isdir(self.loop.worktree(planner, repo)), repo)


if __name__ == "__main__":
    unittest.main()
