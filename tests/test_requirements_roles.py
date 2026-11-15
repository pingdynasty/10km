"""Requirements on issues and roles (REQUIREMENTS.md, Issues to Worker) and on the
State Machine and configuration not covered elsewhere. Each test names the IDs it
checks.

Run: python3 -m unittest discover tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_requirements_msm import MsmCase  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
