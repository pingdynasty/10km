"""Guard: the default test suite cannot launch a real agent harness.

Tests run with the test config (tests/config.env, set by tests/testenv.py), in
which every agent command fails loudly unless the test sets its own fake. These
tests shadow claude, codex and kiro-cli on PATH with stubs that record any call,
launch agents without a fake, and check that the test config's failing command
ran and no harness did.
"""
import glob
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv  # noqa: E402  (test config, no caller env: tests/testenv.py)
from test_scripts import ScriptCase  # noqa: E402
from tenkm import config  # noqa: E402

ROLES = ("planner", "worker", "curator", "auditor", "operator")
STUB = '#!/bin/sh\necho "$0 $*" >> "{log}"\n'


class TestTestConfig(unittest.TestCase):
    def test_every_agent_command_is_the_failing_one(self):
        self.assertEqual(os.environ.get("LOOP_CONFIG"), testenv.CONFIG)
        for name in testenv.AGENT_VARS:
            self.assertNotIn(name, os.environ)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, LOOP_ROOT=tmp):  # no test loop: code defaults
            cfg = config.load()
        self.assertEqual(cfg["LOOP_CONFIG_PATH"], testenv.CONFIG)
        self.assertEqual(cfg["MAX_TASKS_PER_CYCLE"], "0")  # the code's other settings still apply
        for role in ROLES:
            command = cfg.agent_command(role)
            self.assertIn(f"10km tests: {role.upper()}_AGENT is not set", command)
            self.assertIn("exit 97", command)
            for harness in testenv.HARNESSES:
                self.assertNotIn(harness, command.replace("10km tests", ""))

    def test_every_test_module_imports_testenv_first(self):
        """So `python3 -m unittest discover tests` gets the test config too."""
        for path in glob.glob(os.path.join(testenv.TESTS, "test_*.py")):
            with open(path) as f:
                imports = [line for line in f if line.startswith(("import ", "from "))]
            local = [line for line in imports
                     if line.split()[1].split(".")[0] in ("tenkm", "testenv")
                     or line.split()[1].startswith("test_")]
            self.assertTrue(local and local[0].startswith("import testenv"),
                            f"{os.path.basename(path)} must import testenv before tenkm "
                            "and other test modules")


class TestNoHarness(ScriptCase):
    """Launch agents with no fake set, with the real harnesses shadowed by stubs."""

    def setUp(self):
        super().setUp()
        stubs = os.path.join(self.tmp, "stubs")
        os.makedirs(stubs)
        self.calls = os.path.join(self.tmp, "harness-calls.log")
        for harness in testenv.HARNESSES:
            path = os.path.join(stubs, harness)
            with open(path, "w") as f:
                f.write(STUB.format(log=self.calls))
            os.chmod(path, 0o755)
        self.loop.env.pop("LOOP_AGENT")  # ScriptLoop's default fake
        self.loop.env["PATH"] = stubs + os.pathsep + self.loop.env["PATH"]

    def assertNoHarness(self):
        self.assertFalse(os.path.exists(self.calls), "a real agent harness was called")

    def test_dispatcher_launches_the_failing_command(self):
        self.loop.start()
        self.dispatch()
        planner = self.loop.sessions("planner")[0]
        log = os.path.join(planner["working_directory"], "agent.log")

        self.assertTrue(testenv.wait_for(
            lambda: "10km tests: PLANNER_AGENT is not set" in (testenv.read(log) or "")),
            "the test config's command did not run")
        self.assertNoHarness()

    def test_kickoff_runs_the_failing_operator_command(self):
        p = self.loop.run("10km", "kickoff")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("10km tests: OPERATOR_AGENT is not set", p.stderr)
        self.assertNoHarness()


if __name__ == "__main__":
    unittest.main()
