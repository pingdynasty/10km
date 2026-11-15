"""End-to-end scenarios: the real bin/ scripts and the fake agent (tests/fake-agent)
run a temporary loop through whole cycles.

A scenario sets the fake agent's behaviour per session with FAKE_* settings (see
tests/fake-agent), drives Dispatcher passes until a condition holds, then checks
the loop state, the repos and the issues. Scenarios wait on conditions, not on
time: to time out a hanging Worker, drive until it has committed (`committed()`),
then drive with a short WORKER_TIMEOUT. Between passes, drive() waits on events
(a database write, an agent exiting) and conditions read the state in-process, so
a scenario starts few processes besides the loop's own.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv  # noqa: E402  (test config, no caller env: tests/testenv.py)
from test_scripts import ScriptCase  # noqa: E402
from tenkm import msm  # noqa: E402


def alive(pid):
    """True while process pid exists (agents are not our children: no zombies)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


@unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "needs bash and jq")
class ScenarioCase(ScriptCase):
    """A temporary loop run by Dispatcher passes with the fake agent.

    Class `settings` apply to every pass; `drive(..., **env)` adds settings for the
    passes it runs (agents launched in those passes inherit them)."""

    settings = {
        "LOOP_AGENT": testenv.FAKE_AGENT,
        "AUDIT_TIME": "", "AUDIT_CYCLES_LIMIT": "0",  # no Auditor unless a scenario asks
        "SESSION_TIMEOUT": "900", "START_GRACE": "300", "KILL_GRACE": "1",
        "GATE_WAIT": "30",
    }

    def drive(self, until, timeout=None, interval=1.0, **env):
        """Run Dispatcher passes until `until()` is true; fail with the loop's state
        if it isn't within `timeout` seconds. A pass that did something (launched or
        expired a session) is followed by the next at once. After an idle one, the
        next runs as soon as an agent changes the loop state or exits, else after
        `interval` seconds, for what only time brings (time-outs, the start grace).
        Idle passes would only take CPU from the agents."""
        deadline = time.time() + (timeout or testenv.DEADLINE)
        while time.time() < deadline:
            busy = self.dispatch(**env).strip()
            mark = self.writes(), self.agents()
            if until():
                return
            if not busy:
                self.wait_for_change(mark, min(interval, max(0, deadline - time.time())))
        self.fail(f"scenario did not reach its condition:\n{self.describe()}")

    def writes(self):
        """A mark of the database files (mtime and size of the database and its
        WAL): every committed change moves it, reads leave it alone."""
        mark = []
        for path in (self.loop.db, self.loop.db + "-wal"):
            try:
                st = os.stat(path)
                mark.append((st.st_mtime_ns, st.st_size))
            except OSError:
                mark.append(None)
        return tuple(mark)

    def agents(self):
        """The process ids of the sessions' agents that are running (process
        launcher), done sessions' too: the Dispatcher records usage once one exits."""
        pids = []
        for s in self.sessions():
            handle = (s.get("handle") or "").split(":")
            if handle[0] == "process" and len(handle) > 1 and handle[1].isdigit():
                pids.append(int(handle[1]))
        return [p for p in pids if alive(p)]

    def wait_for_change(self, mark, timeout, poll=0.02):
        """Wait at most timeout seconds until the database is written or one of
        the agents exits (mark: writes() and agents()). Polls file stats and the
        processes: nothing is started while agents work."""
        written, pids = mark
        end = time.time() + timeout
        while time.time() < end:
            if self.writes() != written or not all(map(alive, pids)):
                return
            time.sleep(poll)

    def state(self):
        """describe(), only when shown: an assertion message that runs no msm
        process unless the assertion fails."""
        case = self

        class State:
            def __str__(self):
                return case.describe()
        return State()

    def read(self, resource, filt=None):
        """`msm <resource> list [filt]`, read in this process: conditions polled by
        drive() would otherwise start an msm process per check."""
        with msm.transaction(self.loop.db) as m:
            return m.list(resource, json.dumps(filt) if filt else None)

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

    def cycles(self):
        return self.read("cycle")

    def cycle_planned(self, n):
        return lambda: any(c["id"] == n for c in self.cycles())

    def cycle_closed(self, n):
        return lambda: any(c["id"] == n and c["status"] == "closed" for c in self.cycles())

    def tasks(self, cycle=1):
        """The cycle's tasks by shortname."""
        return {t["shortname"]: t for t in self.read("task", {"cycle": cycle})}

    def committed(self, shortname, cycle=1):
        """True once the task's Worker has committed and recorded its branch."""
        task = self.tasks(cycle).get(shortname)
        return bool(task and task["session"] and task["branch"] == task["session"])

    def sessions(self, role=None):
        return [s for s in self.read("session") if role is None or s["role"] == role]

    def active(self, role=None):
        return [s for s in self.sessions(role) if s["status"] == "active"]

    def loop_state(self):
        """`msm loop get`, read in this process."""
        with msm.transaction(self.loop.db) as m:
            return m.loop_get()

    def backlog(self):
        """Open backlog issues by branch."""
        return {i["branch"]: i for i in self.read("issue", {"type": "backlog"})
                if i["status"] == "open"}

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
        if issue is None:
            self.fail(f"no backlog item for {branch}: {self.describe()}")
        self.assertTrue(issue["title"].startswith(why), issue["title"])
        self.assertIn(branch, self.loop.branches("project"))
        self.assertIsNotNone(self.show(branch, f"{task['shortname']}.txt"))
        self.assertFalse(self.on_main(f"{task['shortname']}.txt"))


class TestDriveWaits(ScenarioCase):
    """drive() waits between idle passes on events, not on time."""

    def test_wait_ends_on_a_state_change_an_agent_exit_or_the_timeout(self):  # test helper
        written = self.writes()
        self.loop.msm("loop", "get")  # reads don't count
        self.cycles()
        self.assertEqual(self.writes(), written)
        timer = threading.Timer(0.2, self.loop.start)  # a state change, from elsewhere
        timer.start()
        self.addCleanup(timer.cancel)
        self.wait_for_change((written, []), testenv.DEADLINE)
        self.assertNotEqual(self.writes(), written)
        self.assertEqual(self.loop_state()["phase"], "plan")
        # An agent: a process that is not our child, so it leaves no zombie.
        pid = int(subprocess.run(["sh", "-c", "sleep 0.2 >/dev/null & echo $!"],
                                 capture_output=True, text=True, check=True).stdout)
        self.wait_for_change((self.writes(), [pid]), testenv.DEADLINE)
        self.assertFalse(alive(pid))
        start = time.time()
        self.wait_for_change((self.writes(), [os.getpid()]), 0.2)  # nothing happens
        self.assertGreaterEqual(time.time() - start, 0.2)


class TestExpiry(ScenarioCase):
    def test_hanging_and_dead_workers_are_expired_their_work_backlogged(self):
        """R29, R138, R155, R157, R159, R67, R110, R225, R227, R175, R206, R73,
        R111, R141."""
        settings = dict(FAKE_TASKS="a b c", FAKE_WORKER2="hang", FAKE_WORKER3="die",
                        MAX_WORKERS="3", START_GRACE="1")
        self.loop.start()
        self.drive(lambda: self.committed("b") and self.tasks(1)["a"]["status"] == "done"
                   and self.tasks(1)["c"]["status"] == "expired", **settings)
        self.drive(self.cycle_planned(2), WORKER_TIMEOUT="1", **settings)
        tasks = self.tasks(1)
        self.assertEqual({k: t["status"] for k, t in tasks.items()},
                         {"a": "accepted", "b": "expired", "c": "expired"})
        self.assertRegex(tasks["b"]["session"], r"^cycle1-worker2-")
        self.assertRegex(tasks["c"]["session"], r"^cycle1-worker3-")  # not relaunched
        self.assertEqual(self.show("main", "a.txt"), "a")
        self.assertBacklogged(tasks["b"], "Expired")
        self.assertBacklogged(tasks["c"], "Expired")
        # Both agents were stopped: no escalation that one may still be running.
        self.assertEqual(self.loop.msm("issue", "list", '{"type": "escalation"}'), [])

    def test_dead_planner_is_relaunched_until_it_succeeds(self):
        """R159, R161, R162, R168, R90, R141."""
        self.loop.start()
        self.drive(lambda: any(s["status"] == "expired" for s in self.sessions("planner")),
                   FAKE_PLANNER="die", START_GRACE="1")
        self.assertEqual(self.loop.msm("loop", "get")["phase"], "plan")
        self.drive(self.cycle_planned(1), START_GRACE="1")
        planners = self.loop.sessions("planner")
        self.assertGreaterEqual(len(planners), 2)
        self.assertTrue(all(p["name"].startswith("cycle1-planner-") for p in planners))
        self.assertEqual(self.cycles()[0]["planner_session"], planners[-1]["name"])


class TestRejection(ScenarioCase):
    def test_conflicting_and_failing_branches_are_rejected_and_backlogged(self):
        """R34, R221, R222, R225, R226, R233, R234, R236, R237, R239, R240, R242,
        R175, R206, R251, R83, R111, R141."""
        self.loop.start()
        self.drive(self.cycle_planned(2), FAKE_TASKS="one two bad", MAX_WORKERS="3",
                   FAKE_WORKER1="conflict", FAKE_WORKER2="conflict", FAKE_WORKER3="broken",
                   VALIDATION_GATES="test ! -e broken.txt")
        tasks = self.tasks(1)
        self.assertEqual(tasks["bad"]["status"], "rejected")
        self.assertIsNotNone(tasks["bad"]["curated_at"])
        self.assertFalse(self.on_main("broken.txt"))
        self.assertBacklogged(tasks["bad"], "Rejected")
        self.assertEqual(self.show(tasks["bad"]["session"], "broken.txt"), "broken")
        verdicts = {t["status"]: t for k, t in tasks.items() if k != "bad"}
        self.assertEqual(sorted(verdicts), ["accepted", "rejected"])
        accepted, rejected = verdicts["accepted"], verdicts["rejected"]
        self.assertEqual(self.show("main", "shared.txt"), accepted["session"])
        self.assertEqual(self.show(rejected["session"], "shared.txt"), rejected["session"])
        issue = self.backlog().get(rejected["session"])
        self.assertIsNotNone(issue, self.state())
        self.assertTrue(issue["title"].startswith("Rejected"))
        self.assertIn(rejected["session"], self.loop.branches("project"))


class TestStopAndResume(ScenarioCase):
    def test_stop_mid_cycle_then_resume_continues_the_same_cycle(self):
        """R41, R76, R138, R139, R155, R169, R170, R172, R173, R75, R113, R140, R142,
        R212, R213, R110, R111."""
        settings = dict(FAKE_TASKS="a b c", MAX_WORKERS="2", FAKE_WORKER1="slow",
                        FAKE_DELAY="2", FAKE_WORKER2="hang")
        self.loop.start()
        self.drive(lambda: len(self.active("worker")) == 2, **settings)
        self.loop.msm("loop", "stop", "test")
        self.drive(lambda: self.committed("b") and self.tasks(1)["a"]["status"] == "done",
                   **settings)
        self.drive(lambda: not self.active(), WORKER_TIMEOUT="1", **settings)
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
