"""End-to-end scenarios: the real bin/ scripts and the fake agent (tests/fake-agent)
run a temporary loop through whole cycles, on the host or in the container.

`ScenarioCase` drives Dispatcher passes until a condition holds. A scenario sets
the fake agent's behaviour per session with FAKE_* settings (see tests/fake-agent),
small time-outs, then checks the loop state, the repos and the issues. Add a
scenario as a test method or a ScenarioCase subclass with its own `settings`.

Each requirement checked is cited by ID in the test's docstring.

Run: python3 -m unittest tests.test_scenarios   (needs bash, git and jq)
"""
import json
import os
import shutil
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_scripts import CODE, ScriptCase  # noqa: E402

FAKE_AGENT = os.path.join(CODE, "tests", "fake-agent")


@unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "needs bash and jq")
class ScenarioCase(ScriptCase):
    """A temporary loop run by Dispatcher passes with the fake agent.

    Class `settings` apply to every pass; `drive(..., **env)` adds settings for the
    passes it runs (agents launched in those passes inherit them)."""

    settings = {
        "LOOP_AGENT": FAKE_AGENT,
        "AUDIT_TIME": "", "AUDIT_CYCLES_LIMIT": "0",  # no Auditor unless a scenario asks
        "SESSION_TIMEOUT": "60", "START_GRACE": "60", "KILL_GRACE": "1",
        "GATE_WAIT": "30",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
    }
    timeout = 60  # seconds per drive(): generous, for parallel runs (tests/run.py)

    # --- driving -----------------------------------------------------------
    def dispatch(self, **env):
        p = self.loop.run("dispatch", env=env)
        self.assertExit(p, 0)
        return p.stdout

    def drive(self, until, timeout=None, interval=0.3, **env):
        """Run Dispatcher passes until `until()` is true; fail with the loop's state
        if it isn't within `timeout` seconds."""
        deadline = time.time() + (timeout or self.timeout)
        while time.time() < deadline:
            self.dispatch(**env)
            if until():
                return
            time.sleep(interval)
        self.fail(f"scenario did not reach its condition:\n{self.describe()}")

    def describe(self):
        """The loop state and agent logs, for failure messages."""
        parts = []
        for what in (["loop", "get"], ["session", "list"], ["cycle", "list"],
                     ["task", "list"], ["issue", "list"]):
            p = self.loop.run("msm", *what)
            parts.append(f"msm {' '.join(what)}: {p.stdout.strip()} {p.stderr.strip()}")
        for name in sorted(os.listdir(self.loop.root)):
            log = os.path.join(self.loop.root, name, "agent.log")
            if os.path.exists(log):
                with open(log) as f:
                    parts.append(f"{name}/agent.log:\n{f.read()[-2000:]}")
        return "\n".join(parts)

    # --- state -------------------------------------------------------------
    def cycles(self):
        return self.loop.msm("cycle", "list")

    def cycle_planned(self, n):
        return lambda: any(c["id"] == n for c in self.cycles())

    def cycle_closed(self, n):
        return lambda: any(c["id"] == n and c["status"] == "closed" for c in self.cycles())

    def tasks(self, cycle=1):
        """The cycle's tasks by shortname."""
        return {t["shortname"]: t for t in self.loop.msm("task", "list", json.dumps({"cycle": cycle}))}

    def active(self, role=None):
        return [s for s in self.loop.sessions(role) if s["status"] == "active"]

    def backlog(self):
        """Open backlog issues by branch."""
        return {i["branch"]: i for i in self.loop.msm("issue", "list", '{"type": "backlog"}')
                if i["status"] == "open"}

    # --- repos -------------------------------------------------------------
    def on_main(self, path, repo="project"):
        return self.show("main", path, repo) is not None

    def show(self, ref, path, repo="project"):
        """A file's content at ref, or None."""
        p = subprocess.run(["git", "-C", self.loop.repo(repo), "show", f"{ref}:{path}"],
                           env=self.loop.env, capture_output=True, text=True)
        return p.stdout.strip() if p.returncode == 0 else None

    def assertBacklogged(self, task, why):
        """The task's unmerged work is kept on its branch, named by an open backlog item."""
        branch = task["session"]
        self.assertEqual(task["branch"], branch)
        issue = self.backlog().get(branch)
        self.assertIsNotNone(issue, f"no backlog item for {branch}: {self.describe()}")
        self.assertTrue(issue["title"].startswith(why), issue["title"])
        self.assertIn(branch, self.loop.branches("project"))
        self.assertIsNotNone(self.show(branch, f"{task['shortname']}.txt"))
        self.assertFalse(self.on_main(f"{task['shortname']}.txt"))


class TestExpiry(ScenarioCase):
    def test_hanging_worker_is_expired_its_work_backlogged_and_the_loop_goes_on(self):
        """A Worker that hangs past WORKER_TIMEOUT is stopped and expired; its task
        expires, the other Worker's work is merged, the expired work stays on its
        branch with a backlog item, and the next cycle is planned.

        R29, R138, R155, R157, R67, R110, R225, R227, R175, R206, R73, R111, R141.
        """
        self.loop.start()
        self.drive(self.cycle_planned(2), FAKE_TASKS="a b", FAKE_WORKER2="hang",
                   WORKER_TIMEOUT="10", MAX_WORKERS="2")  # time to commit, under load
        tasks = self.tasks(1)
        self.assertEqual((tasks["a"]["status"], tasks["b"]["status"]), ("accepted", "expired"))
        self.assertRegex(tasks["b"]["session"], r"^cycle1-worker2-")
        self.assertEqual(self.show("main", "a.txt"), "a")
        self.assertBacklogged(tasks["b"], "Expired")
        # The hanging agent was stopped: no escalation that it may still be running.
        self.assertEqual(self.loop.msm("issue", "list", '{"type": "escalation"}'), [])

    def test_dead_worker_is_expired_after_the_start_grace(self):
        """A Worker that exits without setting its session done is expired once the
        launcher reports it not running after START_GRACE; it is not relaunched: the
        cycle is curated without it, its work backlogged.

        R159, R67, R110, R227, R175, R206, R111.
        """
        self.loop.start()
        self.drive(self.cycle_planned(2), FAKE_WORKER="die", START_GRACE="1")
        tasks = self.tasks(1)
        self.assertEqual(tasks["hello"]["status"], "expired")
        self.assertEqual(len([t for t in self.loop.msm("task", "list") if t["cycle"] == 1]), 1)
        self.assertBacklogged(tasks["hello"], "Expired")

    def test_dead_planner_is_relaunched_until_it_succeeds(self):
        """A Planner that dies is expired; the phase stays plan, so the next pass
        launches another Planner for the same cycle.

        R159, R161, R162, R168, R90, R141.
        """
        self.loop.start()
        self.drive(lambda: any(s["status"] == "expired" for s in self.loop.sessions("planner")),
                   FAKE_PLANNER="die", START_GRACE="1")
        self.assertEqual(self.loop.msm("loop", "get")["phase"], "plan")
        self.drive(self.cycle_planned(1), START_GRACE="1")
        planners = self.loop.sessions("planner")
        self.assertGreaterEqual(len(planners), 2)
        self.assertTrue(all(p["name"].startswith("cycle1-planner-") for p in planners))
        self.assertEqual(self.cycles()[0]["planner_session"], planners[-1]["name"])


class TestRejection(ScenarioCase):
    def test_branch_failing_validation_is_rejected_and_backlogged(self):
        """The Curator merges each done Worker, runs the validation gates, and rejects
        the Worker whose branch fails them: its task is rejected, the other merged, its
        branch kept with a backlog item, and the next cycle is planned.

        R34, R225, R233, R234, R236, R237, R239, R240, R242, R175, R206, R251, R83,
        R111, R141.
        """
        self.loop.start()
        self.drive(self.cycle_planned(2), FAKE_TASKS="good bad", FAKE_WORKER2="broken",
                   VALIDATION_GATES="test ! -e broken.txt", MAX_WORKERS="2")
        tasks = self.tasks(1)
        self.assertEqual((tasks["good"]["status"], tasks["bad"]["status"]),
                         ("accepted", "rejected"))
        self.assertIsNotNone(tasks["bad"]["curated_at"])
        self.assertEqual(self.show("main", "good.txt"), "good")
        self.assertFalse(self.on_main("broken.txt"))
        self.assertBacklogged(tasks["bad"], "Rejected")
        self.assertEqual(self.show(tasks["bad"]["session"], "broken.txt"), "broken")

    def test_conflicting_branch_is_rejected_and_backlogged(self):
        """Two Workers change the same file: the Curator merges one, the other
        conflicts and is left out and rejected, its branch kept with a backlog item.

        R222, R226, R221, R233, R242, R175, R206, R251, R111, R141.
        """
        self.loop.start()
        self.drive(self.cycle_planned(2), FAKE_TASKS="one two", FAKE_WORKER="conflict",
                   MAX_WORKERS="2")
        tasks = self.tasks(1).values()
        verdicts = {t["status"]: t for t in tasks}
        self.assertEqual(sorted(verdicts), ["accepted", "rejected"])
        accepted, rejected = verdicts["accepted"], verdicts["rejected"]
        self.assertEqual(self.show("main", "shared.txt"), accepted["session"])
        self.assertEqual(self.show(rejected["session"], "shared.txt"), rejected["session"])
        issue = self.backlog().get(rejected["session"])
        self.assertIsNotNone(issue, self.describe())
        self.assertTrue(issue["title"].startswith("Rejected"))
        self.assertIn(rejected["session"], self.loop.branches("project"))


class TestStopAndResume(ScenarioCase):
    def test_stop_mid_cycle_then_resume_continues_the_same_cycle(self):
        """`loop stop` mid-cycle: no more launches; the running Worker finishes and
        the hanging one is still timed out. The operator resumes (session, done,
        `loop resume`): the same cycle goes on with the waiting task, the operator
        session is curated in the execute phase, and the cycle is then curated.

        R41, R76, R138, R139, R155, R169, R170, R172, R173, R75, R113, R140, R142,
        R212, R213, R110, R111.
        """
        settings = dict(FAKE_TASKS="a b c", MAX_WORKERS="2", FAKE_WORKER1="slow",
                        FAKE_DELAY="2", FAKE_WORKER2="hang", WORKER_TIMEOUT="12")
        self.loop.start()
        self.drive(lambda: len(self.active("worker")) == 2, **settings)
        self.loop.msm("loop", "stop", "test")
        self.drive(lambda: not self.active(), **settings)
        workers = {s["name"][:len("cycle1-workerN")]: s for s in self.loop.sessions("worker")}
        self.assertEqual({k: s["status"] for k, s in workers.items()},
                         {"cycle1-worker1": "done", "cycle1-worker2": "expired"})
        self.assertEqual(self.tasks(1)["c"]["status"], "waiting")
        for _ in range(3):  # stopped: nothing is launched
            self.dispatch(**settings)
        self.assertEqual(self.active(), [])
        loop = self.loop.msm("loop", "get")
        self.assertEqual((loop["stopped"], loop["phase"], loop["current_cycle"]),
                         (True, "execute", 1))

        operator = self.loop.session("operator", "mars")["name"]
        self.loop.done(operator)
        loop = self.loop.msm("loop", "resume")
        self.assertEqual((loop["stopped"], loop["phase"], loop["current_cycle"]),
                         (False, "execute", 1))
        self.dispatch(**settings)
        roles = sorted(s["role"] for s in self.active())
        self.assertEqual(roles, ["curator", "worker"])  # the operator's work, and task c
        self.drive(self.cycle_closed(1), **settings)
        tasks = self.tasks(1)
        self.assertEqual({k: t["status"] for k, t in tasks.items()},
                         {"a": "accepted", "b": "expired", "c": "accepted"})
        self.assertRegex(tasks["c"]["session"], r"^cycle1-worker3-")
        self.assertNotIn(operator, [s["name"] for s in self.loop.sessions()])
        self.assertTrue(self.on_main("a.txt") and self.on_main("c.txt"))


if __name__ == "__main__":
    unittest.main()
