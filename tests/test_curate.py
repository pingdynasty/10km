"""Tests for the Curator steps (tenkm.curate), gates (tenkm.gate) and recovery
from crashes at named fault points.

Run: python3 -m unittest discover tests
"""
import json
import os
import subprocess
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv  # noqa: E402,F401  (test config, no caller env: tests/testenv.py)
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
            self.assertEqual(curate.merge(self.cfg, [op])["applied"], [op])
            self.assertIsNone(curate.publish(self.cfg)["cycle"])
            out = curate.cleanup(self.cfg)
        self.assertEqual(out["unpublished_removed"], [])
        self.assertEqual(self.central("project", "goal.txt"), "hello")
        with self.m() as m:
            self.assertEqual([s["name"] for s in m.list("session")], [cur])


class TestDeclarativeMerge(CurateCase):
    def edit_and_rerun(self, cur, words, path, text):
        with open(os.path.join(self.root, cur, "project", path), "w") as f:
            f.write(text)
        return curate.merge(self.cfg, words)

    def test_conflict_resolve_by_editing_and_rerun(self):
        planner, (w1, w2) = self.cycle_with_workers(("f.txt", "one"), ("f.txt", "two"))
        cur = self.curator()
        with self.as_session(cur):
            curate.select(self.cfg)
            words = [planner, w1, w2]
            result = curate.merge(self.cfg, words)
            conflict = result["conflict"]
            self.assertEqual((conflict["item"], conflict["files"]), (w2, ["f.txt"]))
            self.assertIn("curate-merge", conflict["instructions"])
            again = curate.merge(self.cfg, words)  # markers still there: same report
            self.assertEqual(again["conflict"]["item"], w2)
            done = self.edit_and_rerun(cur, words, "f.txt", "both")
            self.assertIsNone(done["conflict"])
            curate.publish(self.cfg, "r", accepted=[w1, w2])
        self.assertEqual(self.central("project", "f.txt"), "both")
        with self.m() as m:
            self.assertEqual({t["status"] for t in m.cycle_get(1)["tasks"]}, {"accepted"})

    def test_agent_can_finish_the_merge_itself(self):
        planner, (w1, w2) = self.cycle_with_workers(("f.txt", "one"), ("f.txt", "two"))
        cur = self.curator()
        wt = os.path.join(self.root, cur, "project")
        with self.as_session(cur):
            curate.select(self.cfg)
            curate.merge(self.cfg, [planner, w1, w2])
            subprocess.run(["git", "-C", wt, "checkout", "--theirs", "f.txt"], check=True)
            subprocess.run(["git", "-C", wt, "add", "f.txt"], check=True)
            subprocess.run(["git", "-C", wt, "commit", "-q", "--no-edit"], check=True)
            self.assertIsNone(curate.merge(self.cfg, [planner, w1, w2])["conflict"])
        with open(os.path.join(wt, "f.txt")) as f:
            self.assertEqual(f.read(), "two")

    def test_leaving_an_item_out_rebuilds_and_keeps_own_commits_and_resolutions(self):
        planner, (w1, w2, w3) = self.cycle_with_workers(
            ("f.txt", "one"), ("f.txt", "two"), ("g.txt", "three"))
        cur = self.curator()
        with self.as_session(cur):
            curate.select(self.cfg)
            words = [planner, w1, w2, w3]
            curate.merge(self.cfg, words)
            self.edit_and_rerun(cur, words, "f.txt", "both")
            self.commit(cur, "loop", "PLAN.md", "updated plan", "Update plan")
            out = curate.merge(self.cfg, [planner, w1, w3])  # drop w2
            self.assertIsNone(out["conflict"])
            curate.merge(self.cfg, words)  # put w2 back: the resolution is replayed
        wt = os.path.join(self.root, cur)
        with open(os.path.join(wt, "project", "f.txt")) as f:
            self.assertEqual(f.read(), "both")
        with open(os.path.join(wt, "loop", "PLAN.md")) as f:
            self.assertEqual(f.read(), "updated plan")
        with open(os.path.join(wt, "project", "g.txt")) as f:
            self.assertEqual(f.read(), "three")

    def test_dropping_the_conflicting_item_abandons_its_merge(self):
        planner, (w1, w2) = self.cycle_with_workers(("f.txt", "one"), ("f.txt", "two"))
        cur = self.curator()
        with self.as_session(cur):
            curate.select(self.cfg)
            curate.merge(self.cfg, [planner, w1, w2])
            self.assertIsNone(curate.merge(self.cfg, [planner, w1])["conflict"])
            curate.publish(self.cfg, "r", accepted=[w1], rejected=[w2])
        self.assertEqual(self.central("project", "f.txt"), "one")

    def test_partial_acceptance_by_commit(self):
        planner, (w1,) = self.cycle_with_workers(("a.txt", "a"))
        self.commit(w1, "project", "b.txt", "b", "second change")
        sha = subprocess.run(["git", "-C", self.cfg.repo_path("project"), "rev-parse", w1],
                             capture_output=True, text=True).stdout.strip()
        cur = self.curator()
        with self.as_session(cur):
            curate.select(self.cfg)
            out = curate.merge(self.cfg, [planner, sha[:10]])
            self.assertIsNone(out["conflict"])
            curate.publish(self.cfg, "r", accepted=[w1])
        self.assertEqual(self.central("project", "b.txt"), "b")
        self.assertIsNone(self.central("project", "a.txt"))

    def test_unknown_item_is_an_error(self):
        self.start_loop()
        cur = self.curator()
        with self.as_session(cur):
            curate.select(self.cfg)
            with self.assertRaises(curate.CurateError):
                curate.merge(self.cfg, ["no-such-session"])

    def assert_main_plus_own(self, cur, own):
        """Each repo's Curator worktree is main plus exactly the given own commit
        subjects, with no merges."""
        for repo in self.cfg.repos():
            wt = os.path.join(self.root, cur, repo)
            log = subprocess.run(["git", "-C", wt, "log", "--format=%s", "main..HEAD"],
                                 capture_output=True, text=True, check=True).stdout.split("\n")
            self.assertEqual([s for s in log if s], own.get(repo, []), repo)

    def test_no_items_rejects_everything_and_keeps_own_commits(self):
        planner, (w1, w2) = self.cycle_with_workers(("f.txt", "one"), ("g.txt", "two"))
        cur = self.curator()
        with self.as_session(cur):
            curate.select(self.cfg)
            self.assertIsNone(curate.merge(self.cfg, [planner, w1, w2])["conflict"])
            self.commit(cur, "loop", "PLAN.md", "plan", "Update plan")
            self.commit(cur, "project", "own.txt", "own", "Own change")
            out = curate.merge(self.cfg, [])
            self.assertEqual((out["applied"], out["conflict"]), ([], None))
            self.assert_main_plus_own(cur, {"loop": ["Update plan"], "project": ["Own change"]})
            self.assertIsNone(curate.merge(self.cfg, [])["conflict"])  # rerun: no change
            self.assert_main_plus_own(cur, {"loop": ["Update plan"], "project": ["Own change"]})
            curate.publish(self.cfg, "r", rejected=[w1, w2])
        self.assertIsNone(self.central("project", "f.txt"))
        self.assertEqual(self.central("project", "own.txt"), "own")
        rc, _, _ = self.run_step(cur, "merge")
        self.assertEqual(rc, 0)

    def test_no_items_after_a_conflict_on_the_first_item_undoes_other_repos(self):
        planner, (w1,) = self.cycle_with_workers(("f.txt", "worker"))
        self.commit(w1, "loop", "w.txt", "worker")
        cur = self.curator()
        with self.as_session(cur):
            curate.select(self.cfg)
            self.commit(cur, "project", "f.txt", "curator", "Own change")
            out = curate.merge(self.cfg, [w1])  # loop merges, project conflicts
            self.assertEqual(out["conflict"]["repo"], "project")
            self.assertIsNone(curate.merge(self.cfg, [])["conflict"])
            self.assert_main_plus_own(cur, {"project": ["Own change"]})


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


class TestReviewFindings(CurateCase):
    """One test per defect found in the Phase 2 review."""

    def resolve_ours(self, cur, repo, path):
        wt = os.path.join(self.root, cur, repo)
        subprocess.run(["git", "-C", wt, "checkout", "--ours", path], check=True)
        subprocess.run(["git", "-C", wt, "add", path], check=True)
        subprocess.run(["git", "-C", wt, "commit", "-q", "--no-edit"], check=True)

    def test_publish_refuses_an_unfinished_merge(self):
        planner, (w1, w2) = self.cycle_with_workers(("f.txt", "one"), ("f.txt", "two"))
        cur = self.curator()
        with self.as_session(cur):
            curate.select(self.cfg)
            curate.merge(self.cfg, [planner, w1, w2])  # w2 conflicts, unresolved
            with self.assertRaises(curate.CurateError):
                curate.publish(self.cfg, "r", accepted=[w1, w2])
        self.assertIsNone(self.central("project", "f.txt"))

    def test_cleanup_before_publish_reports_unpublished_work(self):
        op = sessions.create(self.cfg, "operator", "mars")["name"]
        self.commit(op, "project", "x.txt", "x")
        with self.m() as m:
            m.session_status(op, "done")
            m.loop_start()
        cur = self.curator()
        with self.as_session(cur):
            curate.select(self.cfg)
            out = curate.cleanup(self.cfg)
        self.assertEqual(out["unpublished_removed"],
                         [{"session": op, "repo": "project", "commits": 1}])

    def test_gate_on_uncommitted_changes_runs_uncached_and_exit_keeps_status(self):
        op = sessions.create(self.cfg, "operator", "mars")["name"]
        with self.m() as m:
            session = dict(m.get_row("session", op))
        path = os.path.join(self.root, op, "project", "ok")
        with open(path, "w") as f:
            f.write("x")
        self.assertEqual(gate.run_gate(self.cfg, session, "project", "test -f ok", 10)[0], "passed")
        os.remove(path)
        self.assertEqual(gate.run_gate(self.cfg, session, "project", "test -f ok", 10)[0], "failed")
        self.assertEqual(gate.run_gate(self.cfg, session, "project", "echo hi; exit 0", 10)[0],
                         "passed")
        self.assertEqual(gate.run_gate(self.cfg, session, "project", "set -e; false; true", 10)[0],
                         "failed")

    def test_session_without_branches_is_skipped_by_merge(self):
        op = sessions.create(self.cfg, "operator", "mars")["name"]
        for repo in self.cfg.repos():
            subprocess.run(["git", "-C", self.cfg.repo_path(repo), "worktree", "remove",
                            "--force", os.path.join(self.root, op, repo)], check=True)
            subprocess.run(["git", "-C", self.cfg.repo_path(repo), "branch", "-D", op],
                           check=True, capture_output=True)
        with self.m() as m:
            m.session_status(op, "done")
            m.loop_start()
        cur = self.curator()
        with self.as_session(cur):
            curate.select(self.cfg)
            self.assertEqual(curate.merge(self.cfg, [op])["no_branches"], [op])

    def test_removal_by_an_expired_curator_fails_loudly(self):
        self.start_loop()
        cur = self.curator()
        other = sessions.create(self.cfg, "operator", "mars")["name"]
        with self.m() as m:
            m.session_status(cur, "expired")
        with self.as_session(cur), self.assertRaises(msm.MSMError):
            sessions.remove(self.cfg, other)
        self.assertTrue(os.path.isdir(os.path.join(self.root, other)))

    def test_merge_failure_without_conflict_is_an_error(self):
        planner, (w1,) = self.cycle_with_workers(("new.txt", "theirs"))
        cur = self.curator()
        with open(os.path.join(self.root, cur, "project", "new.txt"), "w") as f:
            f.write("untracked in the way")
        with self.as_session(cur):
            curate.select(self.cfg)
            with self.assertRaises(curate.CurateError):
                curate.merge(self.cfg, [planner, w1])

    def test_main_branch_is_recorded_not_guessed(self):
        central = self.cfg.repo_path("project")
        subprocess.run(["git", "-C", central, "checkout", "-q", "-b", "elsewhere"], check=True)
        from tenkm import gitutil
        self.assertEqual(gitutil.main_branch(self.cfg, "project"), "main")
        with self.assertRaises(curate.CurateError):
            curate.central_on_main(self.cfg, "project")

    def test_rerere_is_not_enabled_in_shared_config(self):
        self.start_loop()
        cur = self.curator()
        with self.as_session(cur):
            curate.prepare(self.cfg)
        out = subprocess.run(["git", "-C", self.cfg.repo_path("project"), "config", "--get",
                              "rerere.enabled"], capture_output=True, text=True).stdout
        self.assertEqual(out.strip(), "")

    def test_exit_codes_separate_conflict_from_error(self):
        planner, (w1, w2) = self.cycle_with_workers(("f.txt", "one"), ("f.txt", "two"))
        cur = self.curator()
        self.run_step(cur, "select")
        rc, _, _ = self.run_step(cur, "merge", planner, w1, w2)
        self.assertEqual(rc, curate.EXIT_CONFLICT)
        rc, _, _ = self.run_step(cur, "merge", "no-such-session")
        self.assertEqual(rc, curate.EXIT_ERROR)

    def test_rebuild_refuses_to_lose_uncommitted_changes(self):
        planner, (w1, w2) = self.cycle_with_workers(("a.txt", "a"), ("b.txt", "b"))
        cur = self.curator()
        path = os.path.join(self.root, cur, "project", "a.txt")
        with self.as_session(cur):
            curate.select(self.cfg)
            curate.merge(self.cfg, [planner, w1, w2])
            with open(path, "w") as f:
                f.write("unsaved")
            with self.assertRaisesRegex(curate.CurateError, "uncommitted"):
                curate.merge(self.cfg, [planner, w1])  # leaving w2 out rebuilds
            with open(path) as f:
                self.assertEqual(f.read(), "unsaved")
            subprocess.run(["git", "-C", os.path.dirname(path), "checkout", "a.txt"], check=True)
            self.assertEqual(curate.merge(self.cfg, [planner, w1])["applied"], [planner, w1])

    def test_repo_added_after_the_curator_started_is_skipped(self):
        op = sessions.create(self.cfg, "operator", "mars")["name"]
        self.commit(op, "project", "x.txt", "x")
        with self.m() as m:
            m.session_status(op, "done")
            m.loop_start()
        cur = self.curator()
        late = self.cfg.repo_path("late")
        subprocess.run(["git", "init", "-q", "-b", "main", late], check=True)
        subprocess.run(["git", "-C", late, "commit", "-q", "--allow-empty", "-m", "start"],
                       check=True)
        with self.as_session(cur):
            curate.select(self.cfg)
            self.assertEqual(curate.merge(self.cfg, [op])["applied"], [op])
            self.assertEqual(curate.merge(self.cfg, [op])["applied"], [])
            self.assertEqual(curate.publish(self.cfg)["published"], ["project", "loop"])
        self.assertEqual(self.central("project", "x.txt"), "x")
