"""Runs the conformance check (tests/conformance.py) under `make test`, and tests
the checker itself on small inputs.

Run: python3 -m unittest discover tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv  # noqa: E402,F401  (test config, no caller env: tests/testenv.py)
import conformance  # noqa: E402

TEST = "tests/test_conformance.py:TestChecker.test_reports_each_kind_of_problem"
TEXT = """# Title
## One
**R1** a
```
cmd  # R2
```
## Two
**R3** b
"""


class TestConformance(unittest.TestCase):
    def test_every_requirement_is_mapped_or_pending(self):
        result = conformance.check()
        self.assertEqual(result["errors"], [], "\n".join(result["errors"]))
        if result["pending"]:
            sys.stderr.write(f"\nconformance: {len(result['pending'])} of {result['total']} "
                             "requirement IDs pending (python3 tests/conformance.py)\n")


class TestChecker(unittest.TestCase):
    def check(self, *maps):
        return conformance.check(TEXT, [(f"/x/{i}.py", *m) for i, m in enumerate(maps)])

    def test_parses_bold_and_code_block_ids_by_section(self):
        ids, dups = conformance.parse_requirements(TEXT + "**R3** again\n")
        self.assertEqual(ids, {"R1": "One", "R2": "One", "R3": "Two"})
        self.assertEqual(dups, ["R3"])

    def test_complete_map_passes(self):
        r = self.check(("One", {"R1": TEST, "R2": ("prompts/worker.md", "carry out")}, set()),
                       ("Two", {}, {"R3"}))
        self.assertEqual((r["errors"], r["pending"], r["mapped"]), ([], ["R3"], ["R1", "R2"]))

    def test_reports_each_kind_of_problem(self):
        r = self.check(("One", {"R1": "tests/test_conformance.py:TestChecker.nope",
                                "R9": TEST}, {"R1"}),
                       ("Two", {"R2": TEST, "R3": ("prompts/worker.md", "no such phrase")},
                        set()),
                       ("Two", {}, set()))
        errors = "\n".join(r["errors"])
        for expected in ("R1 is also in", "no method nope", "R9 is not in REQUIREMENTS.md",
                         "R2 belongs to section 'One'", "phrase not found",
                         "section 'Two' is also in"):
            self.assertIn(expected, errors)
        r = self.check(("One", {"R1": TEST}, set()))
        self.assertEqual(r["unmapped"], ["R2", "R3"])

    def test_new_ids_cannot_be_pending(self):
        text = TEXT + f"**R{conformance.LAST_PENDABLE + 1}** new\n"
        r = conformance.check(text, [("/x/a.py", "One", {"R1": TEST, "R2": TEST}, set()),
                                     ("/x/b.py", "Two", {"R3": TEST},
                                      {f"R{conformance.LAST_PENDABLE + 1}"})])
        self.assertTrue(any("can't be pending" in e for e in r["errors"]), r["errors"])


if __name__ == "__main__":
    unittest.main()
