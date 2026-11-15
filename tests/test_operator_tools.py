"""Operator tools (GOALS DEL5): `10km doctor`, `10km launch-test` and `10km gate`,
run as subprocesses against a temporary loop (ScriptLoop). R28 (launcher and agent
commands), R34 (worker and validation gates)."""
import glob
import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv  # noqa: E402  (test config, no caller env: tests/testenv.py)
from test_scripts import ScriptCase  # noqa: E402


def snapshot(root):
    """Every path under root with its size and mtime: what a read-only run must keep."""
    out = {}
    for d, _, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            try:
                st = os.lstat(p)
            except FileNotFoundError:
                continue
            out[p] = (st.st_size, st.st_mtime_ns)
    return out


class OperatorCase(ScriptCase):
    def tenkm(self, *args, **env):
        return self.loop.run("10km", *args, env=dict({"TMPDIR": self.tmp}, **env))

    def lines(self, p):
        """{check name: (ok, detail)} from doctor's output."""
        out = {}
        for line in p.stdout.splitlines():
            status, rest = line.split(" ", 1)
            name, _, detail = rest.strip().partition(": ")
            out[name] = (status == "ok", detail)
        return out


class TestDoctor(OperatorCase):
    def test_healthy_loop_passes_every_check_and_changes_nothing(self):  # R28 R34
        before = snapshot(self.tmp)
        p = self.tenkm("doctor", WORKER_GATES="python3 tests/run.py\nloop: test -f config.env")
        self.assertExit(p, 0)
        checks = self.lines(p)
        for name in ("bash", "git", "python", "git version", "config.env", "repo loop",
                     "repo project main branch", "repo project worktreeConfig",
                     "repo project hooks", "database", "launcher", "worker agent",
                     "operator agent", "worker gate 1", "worker gate 2", "validation gates"):
            self.assertIn(name, checks, p.stdout)
            self.assertTrue(checks[name][0], p.stdout)
        self.assertIn("sleep", checks["worker agent"][1])
        after = snapshot(self.tmp)
        changed = {p for p in set(before) | set(after) if before.get(p) != after.get(p)
                   and not p.endswith(("-shm", "-wal"))}  # SQLite's own read locks
        self.assertEqual(changed, set())

    def test_each_problem_fails_its_check_and_exits_1(self):
        project = self.loop.repo("project")
        self.loop.git(project, "config", "--unset", "extensions.worktreeConfig")
        os.remove(self.loop.db)
        p = self.tenkm("doctor", WORKER_AGENT="no-such-agent-cmd --flag",
                       LAUNCHER="no_such_launcher", VALIDATION_GATES="no-such-gate-cmd")
        self.assertExit(p, 1)
        checks = self.lines(p)
        failed = {name for name, (good, _) in checks.items() if not good}
        self.assertEqual(failed, {"repo project worktreeConfig", "database", "launcher",
                                  "worker agent", "validation gate 1"}, p.stdout)
        self.assertIn("no-such-agent-cmd: not found", checks["worker agent"][1])
        self.assertTrue(checks["planner agent"][0])  # LOOP_AGENT still resolves

    def test_missing_hooks_and_main_branch_are_reported(self):
        project = self.loop.repo("project")
        gen = self.loop.git(project, "rev-parse", "--absolute-git-dir")
        subprocess.run(["rm", "-rf", os.path.join(gen, "tenkm-hooks")], check=True)
        self.loop.git(project, "config", "tenkm.mainBranch", "gone")
        p = self.tenkm("doctor")
        self.assertExit(p, 1)
        checks = self.lines(p)
        self.assertFalse(checks["repo project hooks"][0])
        self.assertIn("run 10km init", checks["repo project hooks"][1])
        self.assertEqual(checks["repo project main branch"], (False, "gone: no such branch"))

    def test_broken_config_and_old_git_fail(self):
        fake = os.path.join(self.tmp, "fakebin")
        os.makedirs(fake)
        real = subprocess.run(["bash", "-c", "command -v git"], capture_output=True,
                              text=True).stdout.strip()
        with open(os.path.join(fake, "git"), "w") as f:
            f.write(f'#!/bin/sh\n[ "$1" = --version ] && {{ echo "git version 2.20.1"; exit; }}\n'
                    f'exec {real} "$@"\n')
        os.chmod(os.path.join(fake, "git"), 0o755)
        config = os.path.join(self.tmp, "broken.env")
        with open(config, "w") as f:
            f.write("exit 3\n")
        p = self.tenkm("doctor", PATH=fake + os.pathsep + os.environ["PATH"], LOOP_CONFIG=config)
        self.assertExit(p, 1)
        checks = self.lines(p)
        self.assertFalse(checks["git version"][0])
        self.assertIn("needs 2.26", checks["git version"][1])
        self.assertFalse(checks["config.env"][0])


class TestLaunchTest(OperatorCase):
    def test_runs_the_role_agent_outside_the_loop_state(self):  # R28
        before = self.loop.sessions()
        p = self.tenkm("launch-test", "planner", LOOP_AGENT="false",
                       PLANNER_AGENT=testenv.FAKE_AGENT)
        self.assertExit(p, 0)
        self.assertRegex(p.stdout, r"launch-test planner: exit 0 in [\d.]+s")
        log = p.stdout.split("log: ", 1)[1].splitlines()[0]
        self.assertTrue(log.startswith(self.tmp), log)
        with open(log) as f:
            text = f.read()
        self.assertIn("launch test", text)
        where = text.split("fake agent in ", 1)[1].split(":", 1)[0]
        self.assertEqual(os.path.realpath(where), os.path.realpath(os.path.dirname(log)))
        self.assertEqual(self.loop.sessions(), before)  # no session in msm
        self.assertEqual(self.loop.msm("cycle", "list"), [])

    def test_reports_failure_and_default_role_is_worker(self):
        p = self.tenkm("launch-test", LOOP_AGENT=testenv.FAKE_AGENT, FAKE_LAUNCH_TEST="7")
        self.assertExit(p, 1)
        self.assertIn("launch-test worker: exit 7", p.stdout)

    def test_agent_gets_no_session_and_no_live_database(self):
        dump = "env > env.txt"
        p = self.tenkm("launch-test", LOOP_AGENT=dump, LOOP_SESSION="cycle1-worker1-x")
        self.assertExit(p, 0)
        log = p.stdout.split("log: ", 1)[1].splitlines()[0]
        env = testenv.read_env(os.path.join(os.path.dirname(log), "env.txt"))
        self.assertNotIn("LOOP_SESSION", env)
        self.assertEqual(env["LAUNCH_TEST"], "1")
        self.assertEqual(env["SESSION"], "launch-test-worker")
        self.assertNotEqual(env["MSM_DB"], self.loop.db)
        self.assertTrue(env["MSM_DB"].startswith(os.path.dirname(log)))

    def test_times_out_and_stops_a_hanging_agent(self):
        p = self.tenkm("launch-test", "--timeout", "2", LOOP_AGENT=testenv.FAKE_AGENT,
                       FAKE_LAUNCH_TEST="hang")
        self.assertExit(p, 1)
        self.assertIn("timed out after 2s", p.stdout)

    def test_bad_role_is_refused(self):
        self.assertExit(self.tenkm("launch-test", "operator"), 1)
        self.assertExit(self.tenkm("launch-test", "worker", "planner"), 1)


class TestOperatorGate(OperatorCase):
    def test_runs_in_central_worktrees_without_a_session(self):  # R34
        gates = 'pwd > "$SCRATCH_DIR/where"; git rev-parse --show-toplevel\nloop: true'
        p = self.tenkm("gate", "worker", WORKER_GATES=gates)
        self.assertExit(p, 0)
        results = json.loads(p.stdout)
        self.assertEqual([(r["repo"], r["result"]) for r in results],
                         [("project", "passed"), ("loop", "passed")])
        operator = os.path.join(self.loop.root, ".10km", "evidence", "operator")
        self.assertTrue(results[0]["log"].startswith(operator + os.sep))
        with open(os.path.join(operator, "scratch", "where")) as f:
            self.assertEqual(os.path.realpath(f.read().strip()),
                             os.path.realpath(self.loop.repo("project")))
        self.assertEqual(self.loop.sessions(), [])
        # Cached for the operator only: a session on the same tree still runs it.
        again = json.loads(self.tenkm("gate", "worker", WORKER_GATES=gates).stdout)
        self.assertEqual([r["result"] for r in again], ["skipped", "skipped"])
        name = self.loop.session("operator", "mars")["name"]
        p = self.loop.run("gate", "worker", session=name, env={"WORKER_GATES": gates})
        self.assertEqual([r["result"] for r in json.loads(p.stdout)], ["passed", "passed"])
        self.assertFalse(glob.glob(os.path.join(operator, f"{name}-*")))

    def test_failure_and_usage(self):
        p = self.tenkm("gate", "validation", VALIDATION_GATES="echo nope; false",
                       LOOP_SESSION="no-such-session")
        self.assertExit(p, 1)
        self.assertIn("gate failed: echo nope; false", p.stderr)
        self.assertIn("nope", p.stderr)
        self.assertExit(self.tenkm("gate"), 2)
        self.assertExit(self.tenkm("gate", "everything"), 2)

    def test_session_gate_still_refuses_without_a_session(self):
        self.assertExit(self.loop.run("gate", "worker", env={"WORKER_GATES": "true"}), 2)


if __name__ == "__main__":
    unittest.main()
