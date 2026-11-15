"""Tests for the Curator steps (tenkm.curate), gates (tenkm.gate) and recovery
from crashes at named fault points.

Run: python3 -m unittest discover tests
"""
import json
import os
import subprocess
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from test_loop import LoopCase  # noqa: E402
from tenkm import config, curate, gate, msm, sessions  # noqa: E402

BIN = os.path.join(os.path.dirname(__file__), "..", "bin")
GIT_ID = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
          "GIT_COMMITTER_EMAIL": "t@t"}


class CurateCase(LoopCase):
    env = dict(GIT_ID)

    def commit(self, session, repo, path, text, message="change"):
        wt = os.path.join(self.root, session, repo)
        with open(os.path.join(wt, path), "w") as f:
            f.write(text)
        subprocess.run(["git", "-C", wt, "add", path], check=True)
        subprocess.run(["git", "-C", wt, "commit", "-q", "-m", message], check=True)

    def central(self, repo, path):
        try:
            with open(os.path.join(self.cfg.central, repo, path)) as f:
                return f.read()
        except FileNotFoundError:
            return None

    def as_session(self, name):
        return mock.patch.dict(os.environ, LOOP_SESSION=name)

    def curator(self):
        name = sessions.create(self.cfg, "curator")["name"]
        return name

    def run_step(self, name, step, *args, **env):
        p = subprocess.run([os.path.join(BIN, f"curate-{step}"), *args], capture_output=True,
                           text=True, env=dict(os.environ, LOOP_SESSION=name, **env))
        return p.returncode, p.stdout, p.stderr

    def cycle_with_workers(self, *edits):
        """Kickoff, plan one task per edit, run the Workers, and stop at curate."""
        op = self.start_loop()
        cur = self.curator()
        with self.as_session(cur):
            curate.prepare(self.cfg)
            curate.select(self.cfg)
            curate.merge(self.cfg, [op])
            curate.publish(self.cfg)
            curate.cleanup(self.cfg)
        with self.m() as m:
            m.session_status(cur, "done")
        planner = sessions.create(self.cfg, "planner")["name"]
        with self.m() as m:
            m.cycle_create({"planner_session": planner, "headline": "h", "tasks": [
                {"shortname": f"t{i}", "instructions": "edit", "branch": planner}
                for i in range(len(edits))]})
            m.session_status(planner, "done")
        workers = []
        for path, text in edits:
            w = sessions.create(self.cfg, "worker")["name"]
            self.commit(w, "project", path, text)
            with self.m() as m:
                m.session_status(w, "done")
            workers.append(w)
        return planner, workers


class TestContributionPass(CurateCase):
    def test_operator_work_reaches_main_and_session_is_removed(self):
        op = sessions.create(self.cfg, "operator", "mars")["name"]
        self.commit(op, "project", "goal.txt", "hello")
        with self.m() as m:
            m.session_status(op, "done")
            m.loop_start()
        cur = self.curator()
        with self.as_session(cur):
            curate.prepare(self.cfg)
            self.assertEqual([s["name"] for s in curate.select(self.cfg)], [op])
            self.assertEqual(curate.merge(self.cfg, [op])["merged"], [op])
            self.assertIsNone(curate.publish(self.cfg)["cycle"])
            curate.cleanup(self.cfg)
        self.assertEqual(self.central("project", "goal.txt"), "hello")
        with self.m() as m:
            self.assertEqual([s["name"] for s in m.list("session")], [cur])


class TestCyclePass(CurateCase):
    def test_conflict_rerun_rebuild_and_close(self):
        planner, (w1, w2) = self.cycle_with_workers(("f.txt", "one"), ("f.txt", "two"))
        cur = self.curator()
        with self.as_session(cur):
            curate.prepare(self.cfg)
            chosen = {s["name"] for s in curate.select(self.cfg)}
            self.assertEqual(chosen, {planner, w1, w2})
            result = curate.merge(self.cfg, [planner, w1, w2])
            self.assertEqual(result["conflicts"][0]["session"], w2)
            self.assertEqual(result["conflicts"][0]["files"], ["f.txt"])
            wt = os.path.join(self.root, cur, "project")
            subprocess.run(["git", "-C", wt, "checkout", "--ours", "f.txt"], check=True)
            subprocess.run(["git", "-C", wt, "add", "f.txt"], check=True)
            subprocess.run(["git", "-C", wt, "commit", "-q", "--no-edit"], check=True)
            again = curate.merge(self.cfg, [planner, w1, w2])
            self.assertEqual(set(again["skipped"]), {planner, w1, w2})
            rebuilt = curate.rebuild(self.cfg, [w2])
            self.assertEqual(rebuilt["excluded"], [w2])
            with self.assertRaises(curate.CurateError):  # w1's done task needs a verdict
                curate.publish(self.cfg, "r", accepted=[], rejected=[w2])
            out = curate.publish(self.cfg, "r", accepted=[w1], rejected=[w2])
            self.assertEqual(out["cycle"], 1)
            curate.cleanup(self.cfg)
        self.assertEqual(self.central("project", "f.txt"), "one")
        with self.m() as m:
            c = m.cycle_get(1)
            self.assertEqual(c["status"], "closed")
            self.assertEqual(sorted(t["status"] for t in c["tasks"]), ["accepted", "rejected"])
            m.session_status(cur, "done")
            self.assertEqual(m.loop_get()["phase"], "plan")

    def test_clean_only_skips_conflicting_session(self):
        planner, (w1, w2) = self.cycle_with_workers(("f.txt", "one"), ("f.txt", "two"))
        cur = self.curator()
        with self.as_session(cur):
            curate.select(self.cfg)
            curate.merge(self.cfg, [planner, w1])
            result = curate.merge(self.cfg, [w2], clean_only=True)
        self.assertEqual(result["not_clean"], [w2])
        wt = os.path.join(self.root, cur, "project")
        self.assertEqual(subprocess.run(["git", "-C", wt, "status", "--porcelain"],
                                        capture_output=True, text=True).stdout, "")


class TestRefusals(CurateCase):
    def test_steps_refuse_an_inactive_curator(self):
        self.start_loop()
        cur = self.curator()
        with self.m() as m:
            m.session_status(cur, "expired")
        rc, _, err = self.run_step(cur, "select")
        self.assertEqual(rc, curate.EXIT_REFUSED)
        self.assertIn("stop", err)
        rc, _, _ = self.run_step("", "prepare")
        self.assertEqual(rc, curate.EXIT_REFUSED)

    def test_prepare_removes_leftover_sessions(self):
        op = self.start_loop()
        old = self.curator()
        with self.m() as m:
            m.session_status(old, "done")
        planner = sessions.create(self.cfg, "planner")["name"]
        with self.m() as m:
            m.session_status(planner, "expired")
            m.loop_stop("x")
            m.loop_resume()  # phase plan -> curate
        cur = self.curator()
        with self.as_session(cur):
            removed = set(curate.prepare(self.cfg)["removed"])
        self.assertEqual(removed, {old, planner})
        self.assertFalse(os.path.exists(os.path.join(self.root, old)))
        with self.m() as m:
            self.assertEqual({s["name"] for s in m.list("session")}, {op, cur})


class TestFaults(CurateCase):
    def test_publish_recovers_after_crash_between_repos(self):
        planner, (w1,) = self.cycle_with_workers(("f.txt", "one"))
        cur = self.curator()
        with self.as_session(cur):
            curate.select(self.cfg)
            curate.merge(self.cfg, [planner, w1])
        rc, _, _ = self.run_step(cur, "publish", "--report", "r", "--accepted", w1,
                                 TENKM_FAULT="publish:after-ff:project")
        self.assertEqual(rc, 99)
        self.assertEqual(self.central("project", "f.txt"), "one")
        with self.m() as m:
            self.assertEqual(m.cycle_get()["status"], "open")
        rc, out, err = self.run_step(cur, "publish", "--report", "r", "--accepted", w1)
        self.assertEqual(rc, 0, err)
        with self.m() as m:
            self.assertEqual(m.cycle_get()["status"], "closed")
        rc, out, err = self.run_step(cur, "publish", "--report", "r", "--accepted", w1)
        self.assertEqual((rc, json.loads(out)["already_closed"]), (0, True))

    def test_session_creation_crash_leaves_no_blocking_state(self):
        env = dict(os.environ, TENKM_FAULT="session:after-worktree:loop")
        p = subprocess.run([os.path.join(BIN, "session"), "operator", "mars"], env=env,
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 99)
        s = sessions.create(self.cfg, "operator", "mars")  # a new session still works
        self.assertTrue(os.path.isdir(os.path.join(s["working_directory"], "project")))


class TestGate(CurateCase):
    def test_passed_gate_is_skipped_and_failures_keep_evidence(self):
        op = sessions.create(self.cfg, "operator", "mars")["name"]
        with self.m() as m:
            session = dict(m.get_row("session", op))
        cfg = self.reload(VALIDATION_GATES="echo passing")
        [(repo, command)] = gate.gates(cfg, "validation")
        self.assertEqual(gate.run_gate(cfg, session, repo, command, 30)[0], "passed")
        self.assertEqual(gate.run_gate(cfg, session, repo, command, 30)[0], "skipped")
        failing = "echo failing; exit 3"
        first = gate.run_gate(cfg, session, repo, failing, 30)
        second = gate.run_gate(cfg, session, repo, failing, 30)
        self.assertEqual((first[0], second[0]), ("failed", "failed"))
        self.assertNotEqual(first[1], second[1])
        with open(first[1]) as f:
            self.assertIn("failing", f.read())

    def test_still_running_gate_is_waited_on_not_restarted(self):
        op = sessions.create(self.cfg, "operator", "mars")["name"]
        with self.m() as m:
            session = dict(m.get_row("session", op))
        command = "sleep 2; echo done"
        state, log = gate.run_gate(self.cfg, session, "project", command, 0)
        self.assertEqual(state, "running")
        state2, log2 = gate.run_gate(self.cfg, session, "project", command, 10)
        self.assertEqual((state2, log2), ("passed", log))

    def test_repo_prefix_selects_repo(self):
        cfg = self.reload(VALIDATION_GATES="loop: make check\nnpm test")
        self.assertEqual(gate.gates(cfg, "validation"),
                         [("loop", "make check"), ("project", "npm test")])
