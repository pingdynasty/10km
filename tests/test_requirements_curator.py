"""Requirements on the Curator not covered by tests/test_curate_scripts.py or
tests/test_curate.py."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv  # noqa: E402  (test config, no caller env: tests/testenv.py)
from testenv import CODE  # noqa: E402
from test_curate_scripts import CurateScriptCase  # noqa: E402

PROMPT = os.path.join(CODE, "prompts", "curator.md")
STEP = re.compile(r"^(\d+)\. (\w+)", re.MULTILINE)


def prompt_steps():
    """The Curator prompt's numbered steps: [(number, first word, text)]."""
    with open(PROMPT) as f:
        text = f.read()
    marks = list(STEP.finditer(text))
    return [(int(m.group(1)), m.group(2), text[m.start():marks[i + 1].start()
                                               if i + 1 < len(marks) else len(text)])
            for i, m in enumerate(marks)]


class TestPromptSteps(unittest.TestCase):
    def test_the_prompt_runs_eleven_steps_in_order_calling_the_scripts(self):
        """R203, R204, R207, R210, R216, R249, R254."""
        steps = prompt_steps()
        self.assertEqual([(n, word) for n, word, _ in steps],
                         list(enumerate(["Prepare", "Select", "Merge", "Triage", "Read",
                                         "Evaluate", "Validate", "Assess", "Publish",
                                         "Clean", "Exit"], start=1)))
        scripted = {1: "curate-prepare", 2: "curate-select", 3: "curate-merge",
                    9: "curate-publish", 10: "curate-cleanup"}
        for n, script in scripted.items():
            self.assertIn(f"`{script}", steps[n - 1][2])
            self.assertTrue(os.access(os.path.join(CODE, "bin", script), os.X_OK), script)


class TestIdleLimit(unittest.TestCase):
    def test_config_env_sets_the_idle_limit_the_prompt_names(self):
        """R247. The prompt's phrase is checked, whitespace-normalised, by the
        conformance map (R32, R247)."""
        self.assertRegex(testenv.read(os.path.join(CODE, "config.env")),
                         r"(?m)^IDLE_CYCLE_LIMIT=")


class TestSelectRoles(CurateScriptCase):
    def test_a_done_auditor_is_selected_before_the_cycle(self):
        """R211, R212, R213."""
        planner, (w1,) = self.cycle(("a.txt", "a"))
        auditor = self.loop.session("auditor")["name"]
        self.loop.commit(auditor, "loop", "AUDIT.md", "audit")
        self.loop.done(auditor)
        cur = self.curator()
        out = self.step_ok(cur, "select")
        self.assertEqual([(s["name"], s["role"]) for s in out], [(auditor, "auditor")])
        self.step_ok(cur, "merge", auditor)
        self.step_ok(cur, "publish")
        self.step_ok(cur, "cleanup")
        self.assertEqual(self.central("loop", "AUDIT.md"), "audit")
        self.loop.done(cur)
        cur = self.curator()
        self.assertEqual({s["name"] for s in self.step_ok(cur, "select")}, {planner, w1})

    def test_done_workers_are_not_selected_before_the_curate_phase(self):
        """R212, R213, R214."""
        self.loop.start()
        self.loop.plan("a", "b")
        w1 = self.loop.session("worker")["name"]
        self.loop.done(w1)
        op = self.loop.contribute()
        self.assertEqual(self.loop.msm("loop", "get")["phase"], "execute")
        cur = self.curator()
        self.assertEqual([s["name"] for s in self.step_ok(cur, "select")], [op])
        self.step_ok(cur, "merge", op)
        self.step_ok(cur, "publish")
        self.step_ok(cur, "cleanup")
        self.assertEqual(self.step_ok(cur, "select"), [])
        self.assertIn(w1, self.names())


if __name__ == "__main__":
    unittest.main()
