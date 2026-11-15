"""Script tests for the Curator steps: bin/curate-* run as subprocesses against a
temporary loop (ScriptLoop). tests/test_curate.py covers the merge logic at the
library level; these check what an agent sees: exit codes, JSON output and
errors, refusals, the state each step leaves, and that rerunning a step is safe.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv  # noqa: E402  (test config, no caller env: tests/testenv.py)
from test_scripts import ScriptCase  # noqa: E402

STEPS = ("prepare", "select", "merge", "publish", "cleanup")


class CurateScriptCase(ScriptCase):
    """Helpers to run a cycle and the Curator steps through bin/."""

    def step(self, curator, name, *args, **env):
        return self.loop.run(f"curate-{name}", *args, session=curator, env=env)

    def step_ok(self, curator, name, *args, **env):
        return self.loop.ok(f"curate-{name}", *args, session=curator, env=env)

    def assertFails(self, p, code, text=None):
        """A failed step: exit status code and a one-line JSON error on stderr."""
        self.assertExit(p, code)
        self.assertNotIn("Traceback", p.stderr)
        error = json.loads(p.stderr.strip().splitlines()[-1])["error"]
        if text:
            self.assertIn(text, error)
        return error

    def curator(self):
        return self.loop.session("curator")["name"]

    def cycle(self, *edits):
        """Start the loop, plan one task per (path, text) edit, and run a Worker per
        task that commits its edit to the project. Leaves phase = curate."""
        self.loop.start()
        planner = self.loop.plan(*[f"t{i}" for i in range(len(edits))])
        workers = []
        for path, text in edits:
            w = self.loop.session("worker")["name"]
            self.loop.commit(w, "project", path, text)
            self.loop.done(w)
            workers.append(w)
        self.assertEqual(self.loop.msm("loop", "get")["phase"], "curate")
        return planner, workers

    def tasks(self):
        return {t["session"]: t["status"] for t in self.loop.msm("task", "list")}

    def names(self):
        return {s["name"] for s in self.loop.sessions()}

    def central(self, repo, path):
        return testenv.read(os.path.join(self.loop.repo(repo), path))

    def mine(self, curator, repo, path):
        return testenv.read(os.path.join(self.loop.worktree(curator, repo), path))

    def main(self, repo):
        return self.loop.git(self.loop.repo(repo), "rev-parse", "main")

    def worktrees(self, repo):
        out = self.loop.git(self.loop.repo(repo), "worktree", "list", "--porcelain")
        return [os.path.basename(os.path.dirname(line.split(" ", 1)[1]))
                for line in out.splitlines() if line.startswith("worktree ")][1:]


# --- preconditions -------------------------------------------------------------

class TestRefusals(CurateScriptCase):
    def assert_refused_everywhere(self, session):
        for name in STEPS:
            with self.subTest(step=name, session=session):
                p = self.step(session, name)
                self.assertIn("stop", self.assertFails(p, 2))

    def test_every_step_refuses_without_an_active_curator(self):
        """R205, R86, R87."""
        op = self.loop.contribute()
        self.loop.start()
        other = self.loop.session("operator", "venus")["name"]  # active, not a Curator
        planner = self.loop.session("planner")["name"]
        cur = self.curator()
        before = (self.names(), self.main("project"), self.main("loop"))
        for session in (None, "cycle9-curator-gonegone", other, planner):
            self.assert_refused_everywhere(session)
        self.loop.msm("session", "expired", cur)
        self.assert_refused_everywhere(cur)
        self.assertEqual((self.names(), self.main("project"), self.main("loop")), before)
        self.assertTrue(os.path.isdir(self.loop.worktree(op)))
        self.assertFalse(os.path.exists(os.path.join(self.loop.root, cur, "curation.json")))

    def test_done_curator_is_refused(self):
        """R205."""
        self.loop.start()
        self.loop.contribute()
        cur = self.curator()
        self.loop.done(cur)
        self.assert_refused_everywhere(cur)

    def test_curator_expired_mid_pass_removes_nothing(self):
        """R205, R87."""
        self.loop.start()
        op = self.loop.contribute()
        cur = self.curator()
        self.step_ok(cur, "prepare")
        self.step_ok(cur, "select")
        self.step_ok(cur, "merge", op)
        self.loop.msm("session", "expired", cur)
        self.assertFails(self.step(cur, "publish"), 2)
        self.assertFails(self.step(cur, "cleanup"), 2)
        self.assertIn(op, self.names())
        self.assertTrue(os.path.isdir(self.loop.worktree(op)))
        self.assertIn(op, self.loop.branches("project"))

    def test_steps_out_of_order_are_errors(self):
        """R203."""
        self.loop.start()
        self.loop.contribute()
        cur = self.curator()
        self.assertFails(self.step(cur, "publish"), 1, "curate-select")
        self.assertFails(self.step(cur, "cleanup"), 1, "curate-select")

    def test_usage_errors_are_not_a_traceback(self):
        """R203."""
        self.loop.start()
        self.loop.contribute()
        cur = self.curator()
        for name, args in (("select", ["extra"]), ("publish", ["--nope"])):
            with self.subTest(step=name):
                p = self.step(cur, name, *args)
                self.assertNotEqual(p.returncode, 0)
                self.assertNotIn("Traceback", p.stderr)


# --- Step 1: prepare -------------------------------------------------------------

class TestPrepare(CurateScriptCase):
    def closed_cycle_left_behind(self):
        """Cycle 1 published and closed by a Curator that then died before cleanup."""
        planner, (w1,) = self.cycle(("a.txt", "a"))
        old = self.curator()
        self.step_ok(old, "select")
        self.step_ok(old, "merge", planner, w1)
        self.step_ok(old, "publish", "--report", "r", "--accepted", w1)
        self.loop.msm("session", "expired", old)
        return old, planner, w1

    def test_removes_old_curators_and_closed_cycle_sessions(self):
        """R207, R208, R209."""
        old, planner, w1 = self.closed_cycle_left_behind()
        op = self.loop.contribute()
        cur = self.curator()
        out = self.step_ok(cur, "prepare")
        self.assertEqual(set(out["removed"]), {old, planner, w1})
        self.assertEqual(self.names(), {op, cur})
        for name in (old, planner, w1):
            self.assertFalse(os.path.exists(os.path.join(self.loop.root, name)))
            for repo in ("loop", "project"):
                self.assertNotIn(name, self.loop.branches(repo))
        self.assertEqual(sorted(self.worktrees("project")), sorted([op, cur]))

    def test_keeps_branches_of_unresolved_issues(self):
        """R206, R209."""
        old, planner, w1 = self.closed_cycle_left_behind()
        self.loop.msm("issue", "create", json.dumps(
            {"type": "backlog", "title": "finish it", "branch": w1}))
        answered = self.loop.msm("issue", "create", json.dumps(
            {"type": "escalation", "title": "which way", "branch": planner}))["id"]
        self.loop.msm("issue", "update", answered, '{"status": "answered", "resolution": "x"}')
        resolved = self.loop.msm("issue", "create", json.dumps(
            {"type": "backlog", "title": "done", "branch": old}))["id"]
        self.loop.msm("issue", "update", resolved, '{"status": "resolved"}')
        cur = self.curator()
        self.assertLessEqual({w1, planner, old}, set(self.step_ok(cur, "prepare")["removed"]))
        for kept in (w1, planner):
            self.assertIn(kept, self.loop.branches("project"))
            self.assertNotIn(kept, self.worktrees("project"))
        self.assertNotIn(old, self.loop.branches("project"))

    def test_keeps_the_open_cycles_sessions(self):
        """R208, R209."""
        planner, (w1,) = self.cycle(("a.txt", "a"))
        cur = self.curator()
        self.assertEqual(self.step_ok(cur, "prepare")["removed"], [])
        self.assertEqual(self.names(), {planner, w1, cur})

    def test_rerun_after_a_crash_mid_removal_finishes(self):
        """R207, R209."""
        old, planner, w1 = self.closed_cycle_left_behind()
        self.loop.git(self.loop.repo("loop"), "worktree", "remove", "--force",
                      self.loop.worktree(w1, "loop"))
        self.loop.git(self.loop.repo("loop"), "branch", "-D", w1)
        cur = self.curator()
        self.assertEqual(set(self.step_ok(cur, "prepare")["removed"]), {old, planner, w1})
        self.assertEqual(self.names(), {cur})
        self.assertEqual(self.step_ok(cur, "prepare")["removed"], [])


# --- Step 2: select --------------------------------------------------------------

class TestSelect(CurateScriptCase):
    def test_contributions_first_then_the_cycle(self):
        """R211, R212, R213."""
        planner, (w1, w2) = self.cycle(("a.txt", "a"), ("b.txt", "b"))
        op = self.loop.contribute()
        self.loop.session("operator", "venus")  # still active
        cur = self.curator()
        out = self.step_ok(cur, "select")
        self.assertEqual([s["name"] for s in out], [op])
        self.assertEqual(out[0]["role"], "operator")  # full session records
        self.step_ok(cur, "merge", op)
        self.step_ok(cur, "publish")
        self.step_ok(cur, "cleanup")
        self.loop.done(cur)
        self.assertEqual(self.tasks(), {w1: "done", w2: "done"})  # cycle still open
        cur = self.curator()
        self.assertEqual({s["name"] for s in self.step_ok(cur, "select")}, {planner, w1, w2})

    def test_expired_workers_are_selected_too(self):
        """R213, R225."""
        self.loop.start()
        planner = self.loop.plan("a", "b")
        w1 = self.loop.session("worker")["name"]
        w2 = self.loop.session("worker")["name"]
        self.loop.done(w1)
        self.loop.msm("session", "expired", w2)
        cur = self.curator()
        self.assertEqual({s["name"] for s in self.step_ok(cur, "select")}, {planner, w1, w2})

    def test_nothing_outside_the_curate_phase(self):
        """R214, R215."""
        self.loop.start()
        op = self.loop.contribute()
        cur = self.curator()
        self.assertEqual([s["name"] for s in self.step_ok(cur, "select")], [op])
        self.step_ok(cur, "merge", op)
        self.step_ok(cur, "publish")
        self.step_ok(cur, "cleanup")
        self.assertEqual(self.step_ok(cur, "select"), [])
        self.assertEqual(self.step_ok(cur, "select"), [])


# --- Step 3: merge ---------------------------------------------------------------

class TestMerge(CurateScriptCase):
    def test_merges_sessions_and_reports_json(self):
        """R217, R218, R219."""
        planner, (w1,) = self.cycle(("a.txt", "a"))
        self.loop.commit(w1, "loop", "notes.md", "notes")
        cur = self.curator()
        self.step_ok(cur, "select")
        self.loop.commit(cur, "loop", "PLAN.md", "plan", "Update plan")
        out = self.step_ok(cur, "merge", planner, w1)
        self.assertEqual(out, {"applied": [planner, w1], "no_branches": [], "conflict": None})
        self.assertEqual(self.mine(cur, "project", "a.txt"), "a")
        self.assertEqual(self.mine(cur, "loop", "notes.md"), "notes")
        self.assertEqual(self.mine(cur, "loop", "PLAN.md"), "plan")
        again = self.step_ok(cur, "merge", planner, w1)  # rerun: nothing more to do
        self.assertEqual(again["applied"], [])

    def test_conflict_exits_3_with_instructions_then_rerun_completes(self):
        """R222, R223."""
        planner, (w1, w2) = self.cycle(("f.txt", "one\n"), ("f.txt", "two\n"))
        cur = self.curator()
        self.step_ok(cur, "select")
        words = [planner, w1, w2]
        p = self.step(cur, "merge", *words)
        self.assertExit(p, 3)
        wt = self.loop.worktree(cur)
        self.assertIn(f"CONFLICT merging {w2} in project", p.stdout)
        self.assertIn("Conflicted files: f.txt", p.stdout)
        self.assertIn(f"curate-merge {' '.join(words)}", p.stdout)
        self.assertIn(f"curate-merge {planner} {w1}\n", p.stdout + "\n")  # how to drop w2
        self.loop.git(wt, "rev-parse", "--verify", "MERGE_HEAD")  # left mid-merge
        self.assertExit(self.step(cur, "merge", *words), 3)
        with open(os.path.join(wt, "f.txt"), "w") as f:
            f.write("both\n")
        out = self.step_ok(cur, "merge", *words)
        self.assertIsNone(out["conflict"])
        self.assertEqual(self.mine(cur, "project", "f.txt"), "both\n")
        self.assertEqual(self.loop.git(wt, "status", "--porcelain", "--untracked-files=no"), "")

    def test_unknown_and_ambiguous_items_are_errors(self):
        """R218."""
        planner, (w1,) = self.cycle(("a.txt", "a"))
        cur = self.curator()
        self.step_ok(cur, "select")
        self.assertFails(self.step(cur, "merge", "no-such-session"), 1, "neither")
        # A commit in both repos: the loop repo's main, fetched into project.
        loop_sha = self.loop.git(self.loop.repo("loop"), "rev-parse", "main")
        self.loop.git(self.loop.repo("project"), "fetch", "-q", self.loop.repo("loop"), "main")
        self.assertFails(self.step(cur, "merge", loop_sha), 1, "repo:sha")
        out = self.step_ok(cur, "merge", planner, w1)
        self.assertEqual(out["applied"], [planner, w1])

    def test_leaving_a_session_out_rejects_its_work(self):
        """R220, R221, R234."""
        planner, (w1, w2) = self.cycle(("a.txt", "a"), ("b.txt", "b"))
        cur = self.curator()
        self.step_ok(cur, "select")
        self.step_ok(cur, "merge", planner, w1, w2)
        self.assertEqual(self.mine(cur, "project", "b.txt"), "b")
        self.step_ok(cur, "merge", planner, w1)
        self.assertIsNone(self.mine(cur, "project", "b.txt"))
        self.assertEqual(self.mine(cur, "project", "a.txt"), "a")

    def test_rerun_after_a_crash_mid_step_does_not_merge_twice(self):
        """R223, R203."""
        planner, (w1, w2) = self.cycle(("a.txt", "a"), ("b.txt", "b"))
        cur = self.curator()
        self.step_ok(cur, "select")
        wt = self.loop.worktree(cur)
        # As if the step crashed after git merged w1, before recording it.
        self.loop.git(wt, "merge", "-q", "--no-ff", "--no-edit", w1)
        with open(os.path.join(self.loop.root, cur, "curation.json.tmp"), "w") as f:
            f.write("{\"selec")
        self.step_ok(cur, "merge", planner, w1, w2)
        merges = self.loop.git(wt, "log", "--merges", "--format=%s", "main..HEAD").splitlines()
        self.assertEqual(len(merges), 2)
        self.assertEqual((self.mine(cur, "project", "a.txt"), self.mine(cur, "project", "b.txt")),
                         ("a", "b"))


# --- Step 7: validate ------------------------------------------------------------

class TestValidate(CurateScriptCase):
    def test_failing_work_is_left_out_and_revalidated(self):
        """R235, R236, R237, R239, R240."""
        planner, (w1, w2) = self.cycle(("a.txt", "a"), ("bad.txt", "bad"))
        cur = self.curator()
        gates = {"VALIDATION_GATES": "test -f a.txt && test ! -f bad.txt"}
        self.step_ok(cur, "select")
        self.step_ok(cur, "merge", planner, w1, w2)
        p = self.loop.run("gate", "validation", session=cur, env=gates)
        self.assertExit(p, 1)
        self.assertIn("gate failed", p.stderr)
        self.step_ok(cur, "merge", planner, w1)
        self.assertExit(self.loop.run("gate", "validation", session=cur, env=gates), 0)
        self.step_ok(cur, "publish", "--report", "r", "--accepted", w1, "--rejected", w2)
        self.assertEqual(self.central("project", "a.txt"), "a")
        self.assertIsNone(self.central("project", "bad.txt"))

    def test_curator_fix_is_kept_and_published(self):
        """R238, R219."""
        planner, (w1,) = self.cycle(("a.txt", "broken"))
        cur = self.curator()
        gates = {"VALIDATION_GATES": "grep -q fixed a.txt"}
        self.step_ok(cur, "select")
        self.step_ok(cur, "merge", planner, w1)
        self.assertExit(self.loop.run("gate", "validation", session=cur, env=gates), 1)
        self.loop.commit(cur, "project", "a.txt", "fixed", "Fix a.txt")
        self.step_ok(cur, "merge", planner, w1)
        self.assertExit(self.loop.run("gate", "validation", session=cur, env=gates), 0)
        self.step_ok(cur, "publish", "--report", "r", "--accepted", w1)
        self.assertEqual(self.central("project", "a.txt"), "fixed")


# --- Step 9: publish -------------------------------------------------------------

class TestPublish(CurateScriptCase):
    def merged(self):
        planner, (w1, w2) = self.cycle(("a.txt", "a"), ("b.txt", "b"))
        cur = self.curator()
        self.step_ok(cur, "select")
        self.loop.commit(cur, "loop", "PLAN.md", "plan", "Update plan")
        self.step_ok(cur, "merge", planner, w1)
        return cur, w1, w2

    def test_fast_forwards_main_and_closes_the_cycle_with_verdicts(self):
        """R249, R250, R251, R252."""
        cur, w1, w2 = self.merged()
        report = os.path.join(self.tmp, "report.md")
        with open(report, "w") as f:
            f.write("Cycle 1: a accepted, b rejected.\n")
        out = self.step_ok(cur, "publish", "--report-file", report,
                           "--accepted", w1, "--rejected", w2)
        self.assertEqual(out, {"published": ["project", "loop"], "cycle": 1, "warnings": []})
        head = self.loop.git(self.loop.worktree(cur), "rev-parse", "HEAD")
        self.assertEqual(self.main("project"), head)
        self.assertEqual(self.central("project", "a.txt"), "a")  # central worktree updated
        self.assertIsNone(self.central("project", "b.txt"))
        self.assertEqual(self.central("loop", "PLAN.md"), "plan")
        cycle = self.loop.msm("cycle", "get", "1")
        self.assertEqual((cycle["status"], cycle["report"], cycle["curator_session"]),
                         ("closed", "Cycle 1: a accepted, b rejected.\n", cur))
        self.assertEqual(self.tasks(), {w1: "accepted", w2: "rejected"})

    def test_publishes_own_commits_with_nothing_selected(self):
        """R253, R215."""
        self.loop.start()
        op = self.loop.contribute()
        cur = self.curator()
        for name in ("select", "merge", "publish", "cleanup"):
            self.step_ok(cur, name, *([op] if name == "merge" else []))
        self.assertEqual(self.step_ok(cur, "select"), [])
        self.loop.commit(cur, "loop", "PLAN.md", "assessed", "Assess")
        self.step_ok(cur, "merge")
        out = self.step_ok(cur, "publish")
        self.assertIsNone(out["cycle"])
        self.assertEqual(self.central("loop", "PLAN.md"), "assessed")

    def test_bad_verdicts_are_errors_and_publish_nothing(self):
        """R251, R252."""
        cur, w1, w2 = self.merged()
        before = (self.main("project"), self.main("loop"))
        cases = [(["--accepted", w1, "cycle9-worker1-gonegone"], "not selected"),
                 (["--accepted", w1, w2, "--rejected", w2], "both"),
                 (["--accepted", w1], "no verdict")]
        for args, text in cases:
            with self.subTest(args=args):
                self.assertFails(self.step(cur, "publish", "--report", "r", *args), 1, text)
        self.assertEqual((self.main("project"), self.main("loop")), before)
        self.assertEqual(self.loop.msm("cycle", "get")["status"], "open")

    def test_expired_task_needs_no_verdict(self):
        """R251, R227."""
        self.loop.start()
        planner = self.loop.plan("a", "b")
        w1 = self.loop.session("worker")["name"]
        w2 = self.loop.session("worker")["name"]
        self.loop.commit(w1, "project", "a.txt", "a")
        self.loop.done(w1)
        self.loop.msm("session", "expired", w2)
        cur = self.curator()
        self.step_ok(cur, "select")
        self.step_ok(cur, "merge", planner, w1)
        self.step_ok(cur, "publish", "--report", "r", "--accepted", w1)
        self.assertEqual(self.tasks(), {w1: "accepted", w2: "expired"})

    def test_refuses_a_dirty_central_repo(self):
        """R250."""
        cur, w1, w2 = self.merged()
        with open(os.path.join(self.loop.repo("loop"), "config.env"), "a") as f:
            f.write("# local edit\n")
        before = self.main("project")
        self.assertFails(self.step(cur, "publish", "--accepted", w1, "--rejected", w2), 1,
                         "central/loop")
        self.assertEqual(self.main("project"), before)

    def test_moved_main_is_an_error_until_merge_is_rerun(self):
        """R250, R217."""
        cur, w1, w2 = self.merged()
        central = self.loop.repo("project")
        with open(os.path.join(central, "hotfix.txt"), "w") as f:
            f.write("hotfix")
        self.loop.git(central, "add", "hotfix.txt")
        self.loop.git(central, "commit", "-q", "-m", "Hotfix")
        moved = self.main("project")
        args = ("--report", "r", "--accepted", w1, "--rejected", w2)
        self.assertFails(self.step(cur, "publish", *args), 1, "main has moved")
        self.assertEqual(self.main("project"), moved)
        self.step_ok(cur, "merge", self.loop.sessions("planner")[0]["name"], w1)
        self.step_ok(cur, "publish", *args)
        self.assertEqual((self.central("project", "hotfix.txt"),
                          self.central("project", "a.txt")), ("hotfix", "a"))
        self.assertEqual(self.central("loop", "PLAN.md"), "plan")

    def test_rerun_after_a_crash_before_closing_the_cycle(self):
        """R250, R251."""
        cur, w1, w2 = self.merged()
        args = ("--report", "r", "--accepted", w1, "--rejected", w2)
        p = self.step(cur, "publish", *args, TENKM_FAULT="publish:after-ff:loop")
        self.assertExit(p, 99)
        self.assertEqual(self.central("loop", "PLAN.md"), "plan")
        self.assertEqual(self.loop.msm("cycle", "get")["status"], "open")
        out = self.step_ok(cur, "publish", *args)
        self.assertEqual((out["cycle"], out.get("already_closed")), (1, None))
        self.assertEqual(self.loop.msm("cycle", "get")["status"], "closed")
        self.assertTrue(self.step_ok(cur, "publish", *args)["already_closed"])
        self.assertEqual(self.tasks(), {w1: "accepted", w2: "rejected"})

    def test_warns_about_uncommitted_work_in_the_curator_worktree(self):
        """R250."""
        cur, w1, w2 = self.merged()
        with open(os.path.join(self.loop.worktree(cur, "loop"), "PLAN.md"), "w") as f:
            f.write("unsaved")
        out = self.step_ok(cur, "publish", "--report", "r", "--accepted", w1,
                           "--rejected", w2)
        self.assertEqual(len(out["warnings"]), 1)
        self.assertIn("loop worktree", out["warnings"][0])
        self.assertEqual(self.central("loop", "PLAN.md"), "plan")


# --- Step 10: cleanup ------------------------------------------------------------

class TestCleanup(CurateScriptCase):
    def published(self):
        planner, (w1, w2) = self.cycle(("a.txt", "a"), ("b.txt", "b"))
        cur = self.curator()
        self.step_ok(cur, "select")
        self.step_ok(cur, "merge", planner, w1)
        self.step_ok(cur, "publish", "--report", "r", "--accepted", w1, "--rejected", w2)
        return cur, planner, w1, w2

    def test_removes_selected_sessions_and_reports_unpublished_work(self):
        """R254, R255, R256."""
        cur, planner, w1, w2 = self.published()
        out = self.step_ok(cur, "cleanup")
        self.assertEqual(set(out["removed"]), {planner, w1, w2})
        self.assertEqual(out["unpublished_removed"],
                         [{"session": w2, "repo": "project", "commits": 1}])
        self.assertEqual(out["warnings"], [])
        self.assertEqual(self.names(), {cur})
        for repo in ("loop", "project"):
            self.assertEqual(self.worktrees(repo), [cur])
            self.assertEqual(sorted(self.loop.branches(repo)), sorted(["main", cur]))
            self.assertEqual(self.loop.git(self.loop.repo(repo), "status", "--porcelain"), "")
        for name in (planner, w1, w2):
            self.assertFalse(os.path.exists(os.path.join(self.loop.root, name)))
        self.assertEqual(self.central("project", "a.txt"), "a")
        self.loop.done(cur)
        self.assertEqual(self.loop.msm("loop", "get")["phase"], "plan")  # R259

    def test_keeps_branches_of_unresolved_issues(self):
        """R206, R242, R256."""
        cur, planner, w1, w2 = self.published()
        issue = self.loop.msm("issue", "create", json.dumps(
            {"type": "backlog", "title": "redo b", "branch": w2}),
            session=cur)
        self.assertEqual(issue["assigner_role"], "curator")
        self.loop.msm("issue", "update", issue["id"], '{"status": "answered"}', session=cur)
        out = self.step_ok(cur, "cleanup")
        self.assertEqual(out["unpublished_removed"], [])
        self.assertIn(w2, self.loop.branches("project"))
        self.assertNotIn(w2, self.worktrees("project"))
        self.assertNotIn(w2, self.names())

    def test_rerun_after_a_crash_mid_cleanup_finishes(self):
        """R256."""
        cur, planner, w1, w2 = self.published()
        self.loop.msm("session", "remove", planner)
        self.loop.git(self.loop.repo("project"), "worktree", "remove", "--force",
                      self.loop.worktree(w1))
        out = self.step_ok(cur, "cleanup")
        self.assertEqual(set(out["removed"]), {planner, w1, w2})
        self.assertEqual(self.names(), {cur})
        for repo in ("loop", "project"):
            self.assertEqual(sorted(self.loop.branches(repo)), sorted(["main", cur]))
        self.assertEqual(set(self.step_ok(cur, "cleanup")["removed"]), {planner, w1, w2})
        self.assertEqual(self.names(), {cur})

    def test_warns_about_a_dirty_central_repo(self):
        """R255."""
        cur, planner, w1, w2 = self.published()
        with open(os.path.join(self.loop.repo("loop"), "config.env"), "a") as f:
            f.write("# local edit\n")
        out = self.step_ok(cur, "cleanup")
        self.assertEqual(out["warnings"], ["central/loop has uncommitted changes"])


# --- a whole pass ----------------------------------------------------------------

class TestFullPass(CurateScriptCase):
    def test_every_step_twice_in_a_row_gives_the_same_result(self):
        """R203, R207-R256."""
        planner, (w1, w2) = self.cycle(("a.txt", "a"), ("b.txt", "b"))
        op = self.loop.contribute()
        cur = self.curator()
        for _ in range(2):  # the contribution pass, then the cycle pass
            for name, args in (("prepare", []), ("select", []), ("merge", None),
                               ("publish", None), ("cleanup", [])):
                if args is None:
                    selected = [s["name"] for s in self.step_ok(cur, "select")]
                    if name == "merge":
                        args = selected
                    else:
                        workers = [s for s in selected if s in (w1, w2)]
                        args = ["--report", "r"] + (["--accepted"] + workers if workers else [])
                first = self.step_ok(cur, name, *args)
                second = self.step_ok(cur, name, *args)
                if name in ("prepare", "select", "cleanup"):
                    self.assertEqual(first, second, name)
        self.assertEqual(self.names(), {cur})
        self.assertEqual(self.tasks(), {w1: "accepted", w2: "accepted"})
        self.assertEqual((self.central("project", "a.txt"), self.central("project", "b.txt")),
                         ("a", "b"))


if __name__ == "__main__":
    unittest.main()
