"""Tests for tests/run.py, the parallel test runner. Run: python3 -m unittest discover tests"""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run  # noqa: E402


class Shared(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ready = True

    def test_a(self):
        self.assertTrue(self.ready)

    def test_b(self):
        self.assertTrue(self.ready)


class TestRunner(unittest.TestCase):
    def test_units_are_tests_except_classes_with_shared_setup(self):
        units = run.discover(["test_run."])
        self.assertIn("test_run.TestRunner.test_units_are_tests_except_classes_with_shared_setup",
                      units)
        self.assertIn("test_run.Shared", units)
        self.assertFalse([u for u in units if u.startswith("test_run.Shared.")])

    def test_slow_modules_go_first(self):
        units = ["test_msm.A.test_x", "test_scripts.B.test_y", "test_scenarios.C.test_z"]
        self.assertEqual(run.order(units), [units[2], units[1], units[0]])

    def test_a_failing_unit_fails_the_run_with_its_output(self):
        ok = run.run_unit("test_run.Shared")
        self.assertEqual(ok[1], 0, ok[2])
        self.assertEqual(run.counts(ok[2]), (2, 0))
        bad = run.run_unit("test_run.NoSuchClass")
        self.assertNotEqual(bad[1], 0)
        self.assertIn("NoSuchClass", bad[2])

    def test_command_line(self):
        p = subprocess.run([sys.executable, run.__file__, "-j", "2", "test_run.Shared"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("Ran 2 tests in 1 processes, 2 jobs", p.stdout)
        p = subprocess.run([sys.executable, run.__file__, "no-such-test"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)


if __name__ == "__main__":
    unittest.main()
