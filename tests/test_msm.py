"""Tests for bin/msm. Run: python3 -m unittest discover tests"""
import json
import os
import subprocess
import tempfile
import unittest

MSM = os.path.join(os.path.dirname(__file__), "..", "bin", "msm")


class MsmTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ, MSM_DB=os.path.join(self.tmp.name, "loop.db"),
                        LOOP_ROOT=self.tmp.name)
        self.ok("init")

    def tearDown(self):
        self.tmp.cleanup()

    def run_msm(self, *args):
        p = subprocess.run([MSM, *args], env=self.env, capture_output=True, text=True)
        return p.returncode, (json.loads(p.stdout) if p.stdout else None)

    def ok(self, *args):
        rc, out = self.run_msm(*args)
        self.assertEqual(rc, 0, f"msm {' '.join(args)} failed with {rc}")
        return out

    def fails(self, code, *args):
        rc, _ = self.run_msm(*args)
        self.assertEqual(rc, code, f"msm {' '.join(args)}")

    def phase(self):
        return self.ok("loop", "get")["phase"]

    def start_and_curate_kickoff(self):
        op = self.ok("session", "create", "operator", "mars")["name"]
        self.ok("session", "done", op)
        self.ok("loop", "start")
        cur = self.ok("session", "create", "curator")["name"]
        self.ok("session", "remove", op)  # curate-cleanup removes the selected sessions
        self.ok("session", "done", cur)
        self.assertEqual(self.phase(), "plan")

    def plan(self, tasks):
        planner = self.ok("session", "create", "planner")["name"]
        self.ok("cycle", "create", json.dumps({
            "planner_session": planner, "headline": "h",
            "tasks": [{"shortname": t, "instructions": "do " + t, "branch": planner}
                      for t in tasks]}))
        return planner

    def test_full_cycle(self):
        self.start_and_curate_kickoff()
        planner = self.plan(["a", "b"])
        self.assertEqual(self.phase(), "plan")  # phase moves on planner done, not cycle create
        self.fails(2, "session", "create", "worker")
        self.ok("session", "done", planner)
        self.assertEqual(self.phase(), "execute")
        w1 = self.ok("session", "create", "worker")["name"]
        w2 = self.ok("session", "create", "worker")["name"]
        self.assertTrue(w1.startswith("cycle1-worker1-"))
        self.assertTrue(w2.startswith("cycle1-worker2-"))
        self.fails(2, "session", "create", "worker")  # no waiting task
        self.assertEqual(self.ok("task", "get", "--session", w1)["shortname"], "a")
        self.ok("task", "update", "--session", w1, '{"report": "did a"}')
        self.ok("session", "done", w1)
        self.assertEqual(self.phase(), "execute")
        self.ok("session", "expired", w2)
        self.assertEqual(self.phase(), "curate")
        self.assertEqual(self.ok("task", "get", "--session", w2)["status"], "expired")
        cur = self.ok("session", "create", "curator")["name"]
        self.ok("task", "update", "--session", w1, '{"status": "accepted"}')
        self.ok("cycle", "curate", json.dumps({"curator_session": cur, "report": "r"}))
        self.assertEqual(self.phase(), "curate")  # phase moves on curator done
        self.ok("session", "done", cur)
        self.assertEqual(self.phase(), "plan")
        c = self.ok("cycle", "get", "1")
        self.assertEqual((c["status"], c["report"]), ("closed", "r"))
        self.assertIsNotNone(c["tasks"][0]["curated_at"])

    def test_empty_cycle_goes_to_curate(self):
        self.start_and_curate_kickoff()
        planner = self.plan([])
        self.ok("session", "done", planner)
        self.assertEqual(self.phase(), "curate")

    def test_expired_planner_cycle_is_replaced(self):
        self.start_and_curate_kickoff()
        p1 = self.plan(["a"])
        self.ok("session", "expired", p1)
        self.assertEqual(self.phase(), "plan")
        p2 = self.plan(["b", "c"])
        self.assertTrue(p2.startswith("cycle1-planner-"))
        c = self.ok("cycle", "get")
        self.assertEqual((c["id"], [t["shortname"] for t in c["tasks"]]), (1, ["b", "c"]))

    def test_remove_worker_returns_task(self):
        self.start_and_curate_kickoff()
        self.ok("session", "done", self.plan(["a"]))
        w = self.ok("session", "create", "worker")["name"]
        self.ok("session", "remove", w)
        t = self.ok("task", "list")[0]
        self.assertEqual((t["status"], t["session"]), ("waiting", None))

    def test_preconditions(self):
        self.fails(2, "session", "create", "curator")  # stopped after init
        self.fails(1, "session", "create", "operator")  # username required
        self.fails(1, "session", "create", "planner", "x")
        self.fails(2, "cycle", "create", '{"headline": "h", "tasks": []}')  # not plan phase
        self.ok("loop", "start")
        self.fails(2, "loop", "start")
        self.fails(2, "session", "create", "planner")
        self.ok("session", "create", "curator")
        self.fails(2, "session", "create", "curator")
        self.fails(1, "loop", "update", '{"phase": "plan"}')
        self.fails(3, "session", "get", "nope")

    def test_curator_runs_in_any_phase_for_contributions(self):
        self.start_and_curate_kickoff()
        self.ok("session", "done", self.plan(["a"]))
        self.assertEqual(self.phase(), "execute")
        self.fails(2, "session", "create", "curator")  # execute, nothing to contribute
        op = self.ok("session", "create", "operator", "mars")["name"]
        self.fails(2, "session", "create", "curator")  # still active
        self.ok("session", "done", op)
        cur = self.ok("session", "create", "curator")["name"]  # now allowed in execute
        self.ok("session", "remove", op)
        self.ok("session", "done", cur)
        self.assertEqual(self.phase(), "execute")  # cycle still open: phase unchanged
        self.assertEqual(self.ok("task", "list")[0]["status"], "waiting")

    def test_stop_and_resume(self):
        self.start_and_curate_kickoff()
        self.ok("loop", "stop", "blocked")
        self.assertEqual(self.ok("loop", "get")["reason"], "blocked")
        self.fails(2, "session", "create", "planner")
        loop = self.ok("loop", "resume")
        self.assertEqual((loop["stopped"], loop["phase"], loop["reason"]), (False, "curate", None))

    def test_audits_and_auditor_naming(self):
        self.ok("loop", "start")
        a = self.ok("session", "create", "auditor")["name"]
        self.assertTrue(a.startswith("auditor1-"))
        self.fails(2, "session", "create", "auditor")
        audit = self.ok("audit", "create", json.dumps(
            {"period": {"from": "a", "to": "b"}, "summary": "s"}))
        self.assertEqual(audit["id"], 1)
        self.assertEqual(self.ok("loop", "get")["last_audit"], 1)
        self.ok("session", "remove", a)
        self.assertTrue(self.ok("session", "create", "auditor")["name"].startswith("auditor2-"))

    def test_issues(self):
        i = self.ok("issue", "create", json.dumps(
            {"type": "escalation", "title": "t", "severity": "blocking",
             "assignee_role": "operator", "branch": "b"}))
        self.assertEqual(i["status"], "open")
        self.fails(2, "issue", "remove", i["id"])
        self.fails(1, "issue", "create", '{"type": "bug", "title": "t"}')
        self.assertEqual(len(self.ok("issue", "list", '{"status": "open"}')), 1)
        r = self.ok("issue", "update", i["id"], '{"status": "resolved", "resolution": "ok"}')
        self.assertIsNotNone(r["resolved_at"])
        self.ok("issue", "remove", i["id"])


if __name__ == "__main__":
    unittest.main()
