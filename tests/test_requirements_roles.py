"""Requirements on issues and roles (REQUIREMENTS.md, Issues to Worker) and on the
State Machine and configuration not covered elsewhere. Each test names the IDs it
checks.

Run: python3 -m unittest discover tests
"""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_requirements_msm import MsmCase  # noqa: E402
from tenkm import config  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
