"""End to end: `10km metrics` on a curated fake loop. A Planner, two Workers (one
accepted, one rejected) and a Curator run with the fake agent printing usage
(FAKE_USAGE=1); the metrics then list every session with its role, cycle,
outcome, usage and commits. See tests/test_scenarios.py for `ScenarioCase`.

Durations are only checked to be present: how times are pieced together for
removed sessions is covered in tests/test_metrics.py.

Run: python3 -m unittest tests.test_metrics_e2e   (needs bash, git and jq)
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv  # noqa: E402,F401  (test config, no caller env: tests/testenv.py)
from test_scenarios import ScenarioCase  # noqa: E402

# What tests/fake-agent reports per run with FAKE_USAGE=1.
FAKE = {"runs": 1, "duration_ms": 1500, "num_turns": 3, "total_cost_usd": 0.25,
        "input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 1000,
        "cache_creation_input_tokens": 200}


class TestMetricsOfACuratedLoop(ScenarioCase):
    def usage_recorded(self, *names):
        """Every named session has a usage record."""
        try:
            with open(os.path.join(os.path.dirname(self.loop.db), "usage.jsonl")) as f:
                recorded = {json.loads(line)["session"] for line in f if line.strip()}
        except OSError:
            return False
        return set(names) <= recorded

    def metrics(self, *args):
        p = self.loop.run("10km", "metrics", *args)
        self.assertExit(p, 0)
        return p.stdout

    def test_metrics_report_every_session_of_a_curated_cycle(self):
        """After a cycle with an accepted and a rejected Worker is curated, `10km
        metrics --json` lists its Planner, Workers and Curator with role, cycle and
        outcome; usage per session and per cycle and role add up to the harness
        figures; commits on main are counted by Loop-Session trailer; `--cycle`
        filters; the text output runs.

        R26, R267.
        """
        # Both Workers change shared.txt: the second merge conflicts and is
        # rejected (quicker than a failing validation gate).
        settings = dict(FAKE_TASKS="one two", FAKE_WORKER="conflict",
                        MAX_WORKERS="2", FAKE_USAGE="1", FAKE_CYCLE2_PLANNER="hang")

        def curated_and_recorded():
            cycles = self.cycles()
            if not (cycles and cycles[0]["status"] == "closed"):
                return False
            c = cycles[0]
            workers = [t["session"] for t in self.tasks(1).values()]
            return self.usage_recorded(c["planner_session"], c["curator_session"], *workers)

        self.loop.start()
        self.drive(curated_and_recorded, **settings)
        cycle = self.cycles()[0]
        verdicts = {t["status"]: t for t in self.tasks(1).values()}
        self.assertEqual(sorted(verdicts), ["accepted", "rejected"], self.describe())
        good, bad = verdicts["accepted"]["session"], verdicts["rejected"]["session"]

        data = json.loads(self.metrics("--json", "--cycle", "1"))
        by_name = {r["session"]: r for r in data["sessions"]}
        # A Planner's or Curator's outcome is what it did for the cycle, whether
        # or not its session row is still there.
        expected = {cycle["planner_session"]: ("planner", None, "planned"),
                    good: ("worker", verdicts["accepted"]["shortname"], "accepted"),
                    bad: ("worker", verdicts["rejected"]["shortname"], "rejected"),
                    cycle["curator_session"]: ("curator", None, "curated")}
        self.assertEqual(set(by_name), set(expected), self.describe())
        for name, (role, task, outcome) in expected.items():
            r = by_name[name]
            self.assertEqual((r["role"], r["cycle"], r["task"]), (role, 1, task), r)
            self.assertEqual(r["outcome"], outcome, r)
            self.assertEqual(r["usage"], FAKE, r)
            self.assertIn("duration_s", r)
            self.assertIn("times_from", r)
        # Only the accepted Worker's commit reached main, with its trailer.
        self.assertEqual(by_name[good]["commits"], {"project": 1})
        self.assertEqual(by_name[bad]["commits"], {})

        summary = {g["role"]: g for g in data["summary"]}
        self.assertEqual(sorted(summary), ["curator", "planner", "worker"])
        self.assertTrue(all(g["cycle"] == 1 for g in data["summary"]))
        for role, n in (("planner", 1), ("worker", 2), ("curator", 1)):
            g = summary[role]
            self.assertEqual(g["sessions"], n, g)
            self.assertEqual(g["usage"], {k: v * n for k, v in FAKE.items()}, g)
        self.assertEqual(summary["worker"]["commits"], 1)

        # Unfiltered, cycle 2's hanging Planner is listed too; cycle 1 is unchanged.
        everything = json.loads(self.metrics("--json"))
        cycles = {r["session"]: r["cycle"] for r in everything["sessions"]}
        self.assertTrue(set(expected) <= set(cycles))
        self.assertIn(2, cycles.values())
        self.assertEqual([r for r in everything["sessions"] if r["cycle"] == 1],
                         data["sessions"])
        self.assertEqual(json.loads(self.metrics("--json", "--cycle", "2"))["sessions"],
                         [r for r in everything["sessions"] if r["cycle"] == 2])

        out = self.metrics("--cycle", "1")
        self.assertIn("Sessions:", out)
        self.assertIn("By cycle and role:", out)
        for name in expected:
            self.assertIn(name, out)
        self.assertIn("$0.25", out)
        self.assertIn("$0.50", out)  # the two Workers


if __name__ == "__main__":
    unittest.main()
