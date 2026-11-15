"""Requirements on issues and roles (REQUIREMENTS.md, Issues to Worker) and on the
State Machine and configuration not covered elsewhere. Each test names the IDs it
checks.

Run: python3 -m unittest discover tests
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_loop import LoopCase  # noqa: E402
from test_requirements_msm import MSM, MsmCase  # noqa: E402
from test_scripts import CODE, ScriptCase, wait_for  # noqa: E402
from tenkm import config, dispatch, msm  # noqa: E402


def read(path):
    """A file's text, or "" if it doesn't exist yet."""
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return ""


class TestReplacedCycleCount(MsmCase):
    def replan(self, *shortnames):
        """A Planner plans and expires; the next Planner replaces its cycle."""
        planner = self.plan(*shortnames, done=False)
        self.ok("session", "expired", planner)

    def test_a_replaced_cycle_does_not_count_as_an_idle_cycle(self):  # R71 R72
        self.ok("loop", "start")
        self.plan()
        self.curate()
        self.assertEqual(self.loop()["empty_cycles"], 1)
        self.replan()  # empty, replaced by an empty cycle
        self.plan()
        self.assertEqual(self.loop()["empty_cycles"], 2)
        self.curate()
        self.replan("a")  # with tasks, replaced by an empty cycle
        self.assertEqual(self.loop()["empty_cycles"], 0)
        self.plan()
        self.assertEqual(self.loop()["empty_cycles"], 3)
        self.curate()
        self.replan()  # empty, replaced by a cycle with tasks
        self.plan("b")
        self.assertEqual(self.loop()["empty_cycles"], 0)
        self.assertEqual([c["id"] for c in self.ok("cycle", "list")], [1, 2, 3, 4])


FAKE_CLAUDE = """#!/bin/sh
for a in "$@"; do printf '%s\\n' "$a"; done >"$ARGS_FILE"
"""


class TestHarnessSessionName(unittest.TestCase):
    """The default agent commands in config.env, run as the launchers run them."""

    def run_default(self, role, **env):
        """Run the default agent command for role with a fake claude; its argv."""
        with tempfile.TemporaryDirectory() as tmp:
            claude = os.path.join(tmp, "claude")
            with open(claude, "w") as f:
                f.write(FAKE_CLAUDE)
            os.chmod(claude, 0o755)
            base = {k: v for k, v in os.environ.items()
                    if not k.endswith("_AGENT") and k not in ("LOOP_CONFIG", "SESSION", "LOOP_SESSION", "FIRST_MESSAGE",
                                                       "ONE_SHOT")}
            base.update(LOOP_ROOT=os.path.join(tmp, "root"))  # no central: the code's config
            with mock.patch.dict(os.environ, base, clear=True):
                command = config.load().agent_command(role)
            args = os.path.join(tmp, "args")
            run_env = dict(base, PATH=tmp + os.pathsep + base.get("PATH", ""),
                           ARGS_FILE=args, **env)
            subprocess.run(["bash", "-c", command], env=run_env, check=True)
            with open(args) as f:
                return f.read().splitlines()

    def assertNamed(self, argv, name):
        self.assertIn("-n", argv)
        self.assertEqual(argv[argv.index("-n") + 1], name)

    def test_agent_sessions_are_named_after_the_loop_session(self):  # R26
        argv = self.run_default("worker", SESSION="cycle1-worker1-abcd", FIRST_MESSAGE="go")
        self.assertNamed(argv, "cycle1-worker1-abcd")
        self.assertIn("--no-session-persistence", argv)
        self.assertEqual(argv[-2:], ["-p", "go"])

    def test_operator_sessions_are_named_and_kickoff_is_not(self):  # R26
        argv = self.run_default("operator", SESSION="operator1-mars", ONE_SHOT="1",
                                FIRST_MESSAGE="hi")
        self.assertNamed(argv, "operator1-mars")
        self.assertEqual(argv[-2:], ["-p", "hi"])
        self.assertEqual(self.run_default("operator"), [])


class TestIssueTypes(MsmCase):
    def as_session(self, name, *args):
        """Run msm as session name; return (exit code, output)."""
        env, self.env = self.env, dict(self.env, LOOP_SESSION=name)
        try:
            rc, out, _ = self.run_msm(*args)
        finally:
            self.env = env
        return rc, out

    def test_issues_are_escalations_or_backlog_items(self):  # R174
        for kind in ("escalation", "backlog"):
            issue = self.ok("issue", "create", json.dumps({"type": kind, "title": kind}))
            self.assertEqual(issue["type"], kind)
        for kind in ("bug", "", None):
            self.fails(1, "issue", "create", json.dumps({"type": kind, "title": "t"}))
        self.assertEqual(sorted(i["type"] for i in self.ok("issue", "list")),
                         ["backlog", "escalation"])

    def test_agents_and_operators_create_backlog_items(self):  # R179
        self.ok("loop", "start")
        self.plan("a")
        worker = self.ok("session", "create", "worker")["name"]
        operator = self.ok("session", "create", "operator", "mars")["name"]
        for name in (worker, operator):
            rc, issue = self.as_session(name, "issue", "create", json.dumps(
                {"type": "backlog", "title": f"from {name}", "owner_session": name,
                 "urgent_if": "later"}))
            self.assertEqual(rc, 0)
            self.assertEqual((issue["owner_session"], issue["status"]), (name, "open"))
        self.ok("issue", "create", '{"type": "backlog", "title": "from the operator\'s shell"}')
        self.assertEqual(len(self.ok("issue", "list", '{"type": "backlog"}')), 3)


class TestWorkerLaunch(ScriptCase):
    def test_worker_is_launched_with_its_session_name_and_prompt(self):  # R197
        self.loop.start()
        planner = self.loop.plan("a")
        p = self.loop.run("dispatch", env={"LOOP_AGENT": "env > env.txt"})
        self.assertEqual(p.returncode, 0, p.stderr)
        [worker] = self.loop.sessions("worker")
        name, directory = worker["name"], worker["working_directory"]
        path = os.path.join(directory, "env.txt")
        self.assertTrue(wait_for(lambda: "FIRST_MESSAGE=" in read(path)))
        env = dict(line.split("=", 1) for line in read(path).splitlines() if "=" in line)
        self.assertEqual((env["SESSION"], env["LOOP_SESSION"]), (name, name))
        self.assertIn(name, env["FIRST_MESSAGE"])
        with open(os.path.join(directory, "prompt.txt")) as f:
            text = f.read()
        self.assertIn(f"Session: {name}", text)
        with open(os.path.join(CODE, "prompts", "worker.md")) as f:
            self.assertIn(f.read(), text)
        task = self.loop.msm("task", "get", "--session", name)
        self.assertEqual((task["shortname"], task["branch"]), ("a", planner))


class TestStatePathSettings(LoopCase):
    """MSM_DB and MSM_LOG are config.env settings that agents' msm calls follow."""

    def set_in_config(self, old, new):
        path = os.path.join(self.cfg.central, "loop", "config.env")
        with open(path) as f:
            text = f.read()
        self.assertIn(old, text)
        with open(path, "w") as f:
            f.write(text.replace(old, new))

    def test_defaults_are_unchanged(self):  # R27
        self.assertEqual(self.cfg.db, os.path.join(self.root, ".10km", "loop.db"))
        self.assertEqual(self.cfg.action_log, os.path.join(self.root, ".10km", "actions.log"))
        env = dispatch.Pass(self.cfg).agent_env("s", "p", "m")
        self.assertEqual((env["MSM_DB"], env["MSM_LOG"]), (self.cfg.db, self.cfg.action_log))

    def test_config_env_paths_reach_agents_and_this_process(self):  # R27
        log = os.path.join(self.tmp.name, "custom.log")
        self.set_in_config('MSM_LOG="${MSM_LOG-}"', f'MSM_LOG="${{MSM_LOG-{log}}}"')
        cfg = config.load()
        self.assertEqual(cfg.action_log, log)
        self.assertEqual(self.reload(MSM_LOG="/x/env.log").action_log, "/x/env.log")
        cfg = config.load()
        env = dispatch.Pass(cfg).agent_env("cycle1-worker1-x", "p", "m")
        self.assertEqual((env["MSM_DB"], env["MSM_LOG"]), (cfg.db, log))
        env.pop("LOOP_SESSION")  # act as the operator
        subprocess.run([MSM, "issue", "create", '{"type": "backlog", "title": "agent"}'],
                       env=env, check=True, capture_output=True)
        with msm.transaction(cfg.db) as m:  # a script in this process, e.g. a curate step
            m.create("issue", {"type": "backlog", "title": "script"})
        with open(log) as f:
            commands = [json.loads(line)["command"] for line in f.read().splitlines()]
        self.assertEqual(commands, ["issue create", "issue create"])


if __name__ == "__main__":
    unittest.main()
