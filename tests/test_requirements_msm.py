"""State machine requirements (REQUIREMENTS.md, State Machine) not covered by
tests/test_msm.py, through bin/msm. Each test names the IDs it checks.

Run: python3 -m unittest discover tests
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv  # noqa: E402,F401  (test config, no caller env: tests/testenv.py)

MSM = os.path.join(os.path.dirname(__file__), "..", "bin", "msm")


class MsmCase(unittest.TestCase):
    """A fresh database in a state directory, and an empty loop root beside it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = os.path.join(self.tmp.name, "state")
        self.root = os.path.join(self.tmp.name, "root")
        os.makedirs(self.root)
        self.db = os.path.join(self.state, "loop.db")
        self.env = dict(os.environ, MSM_DB=self.db, LOOP_ROOT=self.root)
        for name in ("LOOP_SESSION", "MSM_LOG"):
            self.env.pop(name, None)  # gates run the tests inside a session
        self.ok("init")

    def run_msm(self, *args):
        p = subprocess.run([MSM, *args], env=self.env, capture_output=True, text=True)
        return p.returncode, (json.loads(p.stdout) if p.stdout else None), p.stderr

    def ok(self, *args):
        rc, out, err = self.run_msm(*args)
        self.assertEqual(rc, 0, f"msm {' '.join(args)} failed with {rc}: {err}")
        return out

    def fails(self, code, *args):
        rc, _, err = self.run_msm(*args)
        self.assertEqual(rc, code, f"msm {' '.join(args)}: {err}")
        return err

    def loop(self):
        return self.ok("loop", "get")

    def plan(self, *shortnames, done=True):
        planner = self.ok("session", "create", "planner")["name"]
        self.ok("cycle", "create", json.dumps({
            "planner_session": planner, "headline": "h",
            "tasks": [{"shortname": s, "instructions": "do " + s, "branch": planner}
                      for s in shortnames]}))
        if done:
            self.ok("session", "done", planner)
        return planner

    def curate(self, verdicts=()):
        cur = self.ok("session", "create", "curator")["name"]
        c = self.ok("cycle", "curate", json.dumps({
            "curator_session": cur, "report": "r",
            "tasks": [{"id": i, "status": s} for i, s in verdicts]}))
        self.ok("session", "done", cur)
        return c

    def backdate(self, table, where=""):
        db = sqlite3.connect(self.db)
        db.execute(f"UPDATE {table} SET updated_at = '2000-01-01T00:00:00Z' {where}")
        db.commit()
        db.close()


class TestInit(MsmCase):
    def test_init_sets_counters_phase_curate_and_stopped(self):  # R39 R85
        loop = self.loop()
        self.assertEqual({k: loop[k] for k in ("current_cycle", "last_audit", "empty_cycles",
                                               "phase", "stopped")},
                         {"current_cycle": 0, "last_audit": 0, "empty_cycles": 0,
                          "phase": "curate", "stopped": True})
        self.fails(2, "init")


class TestTransactions(MsmCase):
    def test_a_failing_call_changes_nothing(self):  # R36 R103
        self.ok("loop", "start")
        self.plan("a")
        w = self.ok("session", "create", "worker")["name"]
        self.ok("session", "done", w)
        task = self.ok("task", "get", "--session", w)
        cur = self.ok("session", "create", "curator")["name"]
        self.fails(3, "cycle", "curate", json.dumps({
            "curator_session": cur, "report": "r",
            "tasks": [{"id": task["id"], "status": "accepted"},
                      {"id": "no-such-task", "status": "accepted"}]}))
        c = self.ok("cycle", "get")
        self.assertEqual((c["status"], c["report"], c["tasks"][0]["status"]),
                         ("open", None, "done"))

    def test_msm_touches_only_the_database(self):  # R37 R38
        self.ok("loop", "start")
        self.plan("a")
        w = self.ok("session", "create", "worker")["name"]
        self.ok("issue", "create", '{"type": "backlog", "title": "t"}')
        self.ok("session", "done", w)
        # The session's working directory is recorded, not created.
        self.assertEqual(self.ok("session", "get", w)["working_directory"],
                         os.path.join(self.root, w))
        self.assertEqual(os.listdir(self.root), [])
        files = {f for f in os.listdir(self.state) if not f.startswith("loop.db")}
        self.assertEqual(files, {"actions.log"})


class TestLoopRecord(MsmCase):
    def test_start_clears_reason_and_goes_to_plan(self):  # R40 R74 R112
        self.ok("loop", "update", '{"reason": "setting up"}')
        loop = self.ok("loop", "start")
        self.assertEqual((loop["stopped"], loop["reason"], loop["phase"]), (False, None, "plan"))

    def test_resume_outside_plan_keeps_the_phase(self):  # R75 R113
        self.ok("loop", "start")
        self.plan("a")
        self.assertEqual(self.loop()["phase"], "execute")
        self.ok("loop", "stop", "blocked")
        loop = self.ok("loop", "resume")
        self.assertEqual((loop["stopped"], loop["reason"], loop["phase"]),
                         (False, None, "execute"))

    def blocking_escalation(self):
        return self.ok("issue", "create", json.dumps(
            {"type": "escalation", "title": "decide", "severity": "blocking",
             "assignee_role": "operator"}))["id"]

    def test_resume_is_refused_while_a_blocking_operator_escalation_is_open(self):  # R171 R313
        self.ok("loop", "start")
        self.ok("loop", "stop", "blocked")
        issue = self.blocking_escalation()
        # Escalations that are not blocking, or not for the operator, don't hold it.
        for other in ({"severity": "high", "assignee_role": "operator"},
                      {"severity": "blocking", "assignee_role": "planner"}):
            self.ok("issue", "create", json.dumps(dict(other, type="escalation", title="t")))
        err = self.fails(2, "loop", "resume")
        self.assertIn(issue, err)
        operator = self.ok("session", "create", "operator", "mars")["name"]
        self.env["LOOP_SESSION"] = operator
        self.fails(2, "loop", "resume")
        self.assertTrue(self.loop()["stopped"])

    def test_resume_is_allowed_once_the_blocking_escalation_is_resolved(self):  # R171 R313
        self.ok("loop", "start")
        self.ok("loop", "stop", "blocked")
        issue = self.blocking_escalation()
        self.fails(2, "loop", "resume")
        self.ok("issue", "update", issue, '{"status": "resolved", "resolution": "ruled"}')
        loop = self.ok("loop", "resume")
        self.assertEqual((loop["stopped"], loop["reason"]), (False, None))

    def test_stop_sets_stopped_and_reason(self):  # R41 R76
        self.ok("loop", "start")
        loop = self.ok("loop", "stop", "idle")
        self.assertEqual((loop["stopped"], loop["reason"]), (True, "idle"))

    def test_stop_without_a_reason_is_refused(self):  # R41 R76
        self.ok("loop", "start")
        for args in ((), ("",), ("  ",)):
            with self.subTest(args=args):
                self.fails(1, "loop", "stop", *args)
        self.assertFalse(self.loop()["stopped"])

    def test_update_changes_fields_but_not_the_protected_ones(self):  # R43 R61
        self.ok("loop", "start")
        self.assertEqual(self.ok("loop", "update", '{"reason": "note"}')["reason"], "note")
        before = self.loop()
        for field, value in (("phase", "curate"), ("stopped", True), ("current_cycle", 5),
                             ("last_audit", 5)):
            with self.subTest(field=field):
                self.fails(1, "loop", "update", json.dumps({field: value}))
        after = self.loop()
        self.assertEqual({k: after[k] for k in ("phase", "stopped", "current_cycle", "last_audit")},
                         {k: before[k] for k in ("phase", "stopped", "current_cycle",
                                                 "last_audit")})

    def test_status_changes_update_updated_at(self):  # R77
        name = self.ok("session", "create", "operator", "mars")["name"]
        self.backdate("loop")
        self.backdate("sessions")
        self.assertNotEqual(self.ok("loop", "start")["updated_at"], "2000-01-01T00:00:00Z")
        self.assertNotEqual(self.ok("session", "done", name)["updated_at"],
                            "2000-01-01T00:00:00Z")


class TestSessions(MsmCase):
    def test_update_get_and_list_with_a_filter(self):  # R45 R46 R47 R57 R58 R60
        name = self.ok("session", "create", "operator", "mars")["name"]
        self.ok("session", "create", "operator", "venus")
        s = self.ok("session", "update", name, '{"handle": "process:1:x"}')
        self.assertEqual((s["name"], s["handle"]), (name, "process:1:x"))
        self.assertIsNone(self.ok("session", "update", name, '{"handle": null}')["handle"])
        self.assertEqual(self.ok("session", "get", name)["name"], name)
        self.assertEqual(len(self.ok("session", "list")), 2)
        listed = self.ok("session", "list", json.dumps({"name": name}))
        self.assertEqual([s["name"] for s in listed], [name])
        self.assertEqual(self.ok("session", "list", '{"role": "planner"}'), [])

    def test_expired_session_cannot_be_set_to_done(self):  # R78
        name = self.ok("session", "create", "operator", "mars")["name"]
        self.ok("session", "expired", name)
        self.fails(2, "session", "done", name)
        self.assertEqual(self.ok("session", "get", name)["status"], "expired")

    def test_operator_sessions_need_no_precondition(self):  # R94
        names = [self.ok("session", "create", "operator", "mars")["name"]]  # stopped
        self.ok("loop", "start")
        names.append(self.ok("session", "create", "operator", "mars")["name"])  # plan
        self.plan("a")
        names.append(self.ok("session", "create", "operator", "venus")["name"])  # execute
        self.assertEqual(len(set(names)), 3)


class TestWorkerSideEffects(MsmCase):
    def setUp(self):
        super().setUp()
        self.ok("loop", "start")
        self.plan("a", "b")

    def test_creating_a_worker_claims_the_first_waiting_task(self):  # R66
        w = self.ok("session", "create", "worker")["name"]
        t = self.ok("task", "get", "--session", w)
        self.assertEqual((t["shortname"], t["session"], t["status"]), ("a", w, "active"))
        self.assertIsNotNone(t["started_at"])
        other = [t for t in self.ok("task", "list") if t["shortname"] == "b"][0]
        self.assertEqual((other["status"], other["session"]), ("waiting", None))

    def test_done_or_expired_worker_sets_its_task_and_done_at(self):  # R67
        w1 = self.ok("session", "create", "worker")["name"]
        w2 = self.ok("session", "create", "worker")["name"]
        self.ok("session", "done", w1)
        self.ok("session", "expired", w2)
        for w, status in ((w1, "done"), (w2, "expired")):
            t = self.ok("task", "get", "--session", w)
            self.assertEqual(t["status"], status)
            self.assertIsNotNone(t["done_at"])

    def test_removing_an_active_worker_returns_its_task(self):  # R68
        w = self.ok("session", "create", "worker")["name"]
        self.ok("session", "remove", w)
        t = [t for t in self.ok("task", "list") if t["shortname"] == "a"][0]
        self.assertEqual((t["status"], t["session"], t["started_at"]), ("waiting", None, None))
        self.fails(3, "session", "get", w)


class TestCycles(MsmCase):
    def test_create_needs_plan_phase_and_a_running_loop(self):  # R69
        self.ok("loop", "start")
        planner = self.ok("session", "create", "planner")["name"]
        self.ok("loop", "stop", "x")
        self.fails(2, "cycle", "create", json.dumps(
            {"planner_session": planner, "headline": "h", "tasks": []}))

    def test_create_sets_id_status_planned_at_and_task_fields(self):  # R70 R80 R82
        self.ok("loop", "start")
        planner = self.ok("session", "create", "planner")["name"]
        c = self.ok("cycle", "create", json.dumps({
            "planner_session": planner, "headline": "h",
            "tasks": [{"shortname": "a", "instructions": "i", "branch": planner}]}))
        self.assertEqual((c["id"], c["status"], c["headline"]), (1, "open", "h"))
        self.assertIsNotNone(c["planned_at"])
        self.assertEqual(self.loop()["current_cycle"], 1)
        [t] = c["tasks"]
        self.assertEqual((t["cycle"], t["status"], t["shortname"], t["branch"]),
                         (1, "waiting", "a", planner))
        self.assertIsNotNone(t["created_at"])

    def test_empty_cycles_counts_consecutive_empty_cycles(self):  # R72 R105
        self.ok("loop", "start")
        self.plan()
        self.assertEqual(self.loop()["empty_cycles"], 1)
        self.curate()
        self.plan()
        self.assertEqual(self.loop()["empty_cycles"], 2)
        self.curate()
        self.plan("a")
        self.assertEqual(self.loop()["empty_cycles"], 0)
        self.assertEqual([c["id"] for c in self.ok("cycle", "list")], [1, 2, 3])

    def test_curate_sets_curated_at_report_and_closes(self):  # R73 R81
        self.ok("loop", "start")
        self.plan()
        c = self.curate()
        self.assertEqual((c["status"], c["report"]), ("closed", "r"))
        self.assertIsNotNone(c["curated_at"])
        self.assertTrue(c["curator_session"].startswith("cycle1-curator-"))

    def test_list_update_and_remove(self):  # R50 R54 R106 R108
        self.ok("loop", "start")
        self.plan("old")
        w = self.ok("session", "create", "worker")["name"]
        self.ok("session", "done", w)
        old_task = self.ok("task", "get", "--session", w)
        self.curate([(old_task["id"], "accepted")])
        self.plan("new")
        active = self.ok("session", "create", "worker")["name"]
        issue = self.ok("issue", "create", '{"type": "backlog", "title": "t"}')
        self.assertEqual(self.ok("cycle", "update", "2", '{"headline": "h2"}')["headline"], "h2")
        self.assertEqual([c["id"] for c in self.ok("cycle", "list", '{"status": "open"}')], [2])
        # Removing history must not touch the current cycle, open issues, or active sessions.
        self.fails(2, "cycle", "remove", "2")
        self.fails(2, "task", "remove", "--session", active)
        self.fails(2, "issue", "remove", issue["id"])
        self.ok("task", "remove", old_task["id"])
        self.fails(3, "task", "get", old_task["id"])
        self.ok("cycle", "remove", "1")
        self.fails(3, "cycle", "get", "1")
        self.assertEqual(self.ok("cycle", "get")["id"], 2)
        self.assertEqual(self.ok("session", "get", active)["status"], "active")
        self.assertEqual(self.ok("task", "get", "--session", active)["status"], "active")
        self.assertEqual(self.ok("issue", "get", issue["id"])["status"], "open")

    def test_create_and_curate_inputs_are_checked(self):  # R101 R102
        self.ok("loop", "start")
        planner = self.ok("session", "create", "planner")["name"]
        for task in ({"shortname": "a", "instructions": "i"},
                     {"shortname": "a", "instructions": "i", "branch": "b", "extra": "x"}):
            with self.subTest(task=task):
                self.fails(1, "cycle", "create", json.dumps(
                    {"planner_session": planner, "headline": "h", "tasks": [task]}))
        self.fails(1, "cycle", "create", json.dumps({"headline": "h", "tasks": [], "x": 1}))
        self.ok("cycle", "create", json.dumps({"planner_session": planner, "headline": "h",
                                               "tasks": []}))
        self.ok("session", "done", planner)
        cur = self.ok("session", "create", "curator")["name"]
        self.fails(1, "cycle", "curate", json.dumps({"curator_session": cur, "x": 1}))
        self.ok("cycle", "curate", json.dumps({"curator_session": cur, "report": "r",
                                               "tasks": []}))


class TestIssuesAndAudits(MsmCase):
    def test_issue_get_and_update(self):  # R55 R57 R59
        i = self.ok("issue", "create", json.dumps({
            "type": "backlog", "title": "t", "urgent_if": "never", "branch": "b"}))
        self.assertEqual(self.ok("issue", "get", i["id"])["urgent_if"], "never")
        u = self.ok("issue", "update", i["id"], '{"branch": null, "severity": "high"}')
        self.assertEqual((u["branch"], u["severity"]), (None, "high"))
        self.fails(3, "issue", "get", "no-such-issue")

    def test_audit_create_get_list_update_remove(self):  # R55 R59 R84
        self.ok("loop", "start")
        a = self.ok("audit", "create", json.dumps({"period": {"from": "a", "to": "b"},
                                                   "summary": "s"}))
        self.assertEqual((a["id"], a["period"]), (1, {"from": "a", "to": "b"}))
        self.assertIsNotNone(a["created_at"])
        self.assertEqual(self.ok("loop", "get")["last_audit"], 1)
        self.assertEqual(self.ok("audit", "create", json.dumps(
            {"period": {"from": "b", "to": "c"}, "summary": "s2"}))["id"], 2)
        self.assertEqual(self.ok("audit", "get", "1")["summary"], "s")
        self.assertEqual(self.ok("audit", "update", "1", '{"summary": "s1"}')["summary"], "s1")
        self.assertEqual([x["id"] for x in self.ok("audit", "list")], [1, 2])
        self.ok("audit", "remove", "1")
        self.fails(3, "audit", "get", "1")


class TestResults(MsmCase):
    def test_create_returns_the_resource_and_errors_are_json(self):  # R56
        s = self.ok("session", "create", "operator", "mars")  # a string argument
        self.assertEqual((s["role"], s["status"]), ("operator", "active"))
        i = self.ok("issue", "create", '{"type": "backlog", "title": "t"}')  # JSON
        self.assertEqual((i["type"], i["title"], i["status"]), ("backlog", "t", "open"))
        err = json.loads(self.fails(1, "issue", "create", '{"type": "bug", "title": "t"}'))
        self.assertEqual(err["code"], 1)
        self.assertTrue(err["message"])
        err = json.loads(self.fails(3, "session", "get", "nope"))
        self.assertEqual(err["code"], 3)

    def test_records_have_the_fields_of_the_state_block(self):  # R95 R96 R97 R98 R99 R100
        self.ok("loop", "start")
        planner = self.plan("a")
        issue = self.ok("issue", "create", '{"type": "backlog", "title": "t"}')
        audit = self.ok("audit", "create", '{"period": {"from": "a", "to": "b"}, "summary": "s"}')
        cycle = self.ok("cycle", "get")
        expected = {
            "loop": (self.loop(), "current_cycle last_audit empty_cycles phase stopped reason "
                                  "updated_at"),
            "session": (self.ok("session", "get", planner),
                        "name role status handle working_directory created_at updated_at"),
            "cycle": (cycle, "id status planner_session planned_at headline report "
                             "curator_session curated_at"),
            "task": (cycle["tasks"][0], "id cycle shortname instructions branch session report "
                                        "status created_at started_at done_at curated_at"),
            "issue": (issue, "id type title description owner_session assignee_role "
                             "resolver_role severity urgent_if status branch created_at "
                             "resolved_at resolution"),
            "audit": (audit, "id period summary created_at"),
        }
        for kind, (record, fields) in expected.items():
            with self.subTest(kind=kind):
                self.assertLessEqual(set(fields.split()), set(record))


if __name__ == "__main__":
    unittest.main()
