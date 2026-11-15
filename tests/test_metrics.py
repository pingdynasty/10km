"""Tests for tenkm.metrics and `10km metrics`."""
import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_loop import LoopCase  # noqa: E402
from tenkm import cli, metrics, msm  # noqa: E402


class MetricsCase(LoopCase):
    def commit(self, repo, session, message="work"):
        subprocess.run(["git", "-C", self.cfg.repo_path(repo), "commit", "-q", "--allow-empty",
                        "-m", f"{message}\n\nLoop-Session: {session}"], check=True)

    def write_usage(self, *records):
        with open(os.path.join(os.path.dirname(self.cfg.db), "usage.jsonl"), "a") as f:
            for r in records:
                f.write((r if isinstance(r, str) else json.dumps(r)) + "\n")

    def one_cycle(self):
        """A loop through one curated cycle with two Workers; the planner, accepted
        Worker and curator sessions removed, as the Curator's cleanup leaves them."""
        self.start_loop()
        with self.m() as m:
            planner = m.session_create("planner")["name"]
        with msm.transaction(self.cfg.db, caller=planner) as m:
            m.cycle_create({"planner_session": planner, "headline": "h", "tasks": [
                {"shortname": "a", "instructions": "i", "branch": planner},
                {"shortname": "b", "instructions": "i", "branch": planner}]})
            m.session_status(planner, "done")
        with self.m() as m:
            w1 = m.session_create("worker")["name"]
            w2 = m.session_create("worker")["name"]
        with msm.transaction(self.cfg.db, caller=w1) as m:
            m.session_status(w1, "done")
        with self.m() as m:
            m.session_status(w2, "expired")
            curator = m.session_create("curator")["name"]
        with msm.transaction(self.cfg.db, caller=curator) as m:
            tasks = m.cycle_get()["tasks"]
            m.cycle_curate({"curator_session": curator, "report": "r", "tasks": [
                {"id": tasks[0]["id"], "status": "accepted"},
                {"id": tasks[1]["id"], "status": "rejected"}]})
            m.session_status(curator, "done")
        with self.m() as m:
            for name in (planner, w1, curator):
                m.session_remove(name)
        return planner, w1, w2, curator


class TestCollect(MetricsCase):
    def test_sessions_outcomes_commits_and_usage(self):
        planner, w1, w2, curator = self.one_cycle()
        self.commit("project", w1)
        self.commit("project", w1)
        self.commit("loop", planner)
        self.commit("project", "cycle9-worker1-old")  # an earlier loop's history
        self.write_usage(
            {"session": w1, "role": "worker", "cycle": 1, "recorded_at": "2026-01-01T10:00:00Z",
             "harness": "claude", "duration_ms": 120000, "num_turns": 3, "input_tokens": 10,
             "output_tokens": 5, "total_cost_usd": 0.5, "something_new": [1]},
            {"session": w1, "role": "worker", "cycle": 1, "recorded_at": "2026-01-01T10:05:00Z",
             "harness": "claude", "num_turns": 2},
            "not json", '["not an object"]',
            {"session": "auditor1-abcd1234", "role": "auditor", "cycle": 1,
             "recorded_at": "2026-01-01T11:00:00Z", "duration_ms": 60000})
        data = metrics.collect(self.cfg)
        by = {r["session"]: r for r in data["sessions"]}

        self.assertEqual(by[w1]["outcome"], "accepted")
        self.assertEqual(by[w1]["task"], "a")
        self.assertEqual(by[w1]["times_from"], "task")
        self.assertIsNotNone(by[w1]["duration_s"])
        self.assertEqual(by[w1]["commits"], {"project": 2})
        self.assertEqual(by[w1]["usage"], {"duration_ms": 120000, "num_turns": 5,
                                           "input_tokens": 10, "output_tokens": 5,
                                           "total_cost_usd": 0.5, "runs": 2})
        self.assertEqual(by[w2]["outcome"], "rejected")  # task verdict beats session status
        self.assertEqual(by[planner]["role"], "planner")
        self.assertEqual(by[planner]["outcome"], "planned")
        self.assertEqual(by[planner]["times_from"], "log")
        self.assertEqual(by[planner]["commits"], {"loop": 1})
        self.assertEqual(by[curator]["outcome"], "curated")
        self.assertEqual((by[curator]["role"], by[curator]["cycle"]), ("curator", 1))
        auditor = by["auditor1-abcd1234"]
        self.assertEqual((auditor["role"], auditor["cycle"], auditor["times_from"]),
                         ("auditor", 1, "usage"))
        self.assertEqual(auditor["start"], "2026-01-01T10:59:00Z")
        self.assertEqual(auditor["duration_s"], 60)
        old = by["cycle9-worker1-old"]
        self.assertEqual((old["role"], old["cycle"], old["outcome"], old["times_from"]),
                         ("worker", 9, "unknown", "commits"))

        workers = [g for g in data["summary"] if (g["cycle"], g["role"]) == (1, "worker")][0]
        self.assertEqual((workers["sessions"], workers["commits"]), (2, 2))
        self.assertEqual(workers["usage"]["input_tokens"], 10)
        self.assertTrue(any("activity window" in n for n in data["notes"]))  # old worker

    def logged(self, name, command):
        with open(self.cfg.action_log) as f:
            lines = [json.loads(x) for x in f.read().splitlines()]
        return [x["at"] for x in lines if (x["command"], x.get("name")) == (command, name)][0]

    def test_removed_curator_gets_exact_times_from_the_log(self):
        planner, w1, w2, curator = self.one_cycle()
        by = {r["session"]: r for r in metrics.collect(self.cfg)["sessions"]}
        row = by[curator]
        start, end = self.logged(curator, "session create"), self.logged(curator, "session done")
        self.assertEqual((row["times_from"], row["start"], row["end"]), ("log", start, end))
        self.assertEqual(row["duration_s"], (metrics.parse_time(end)
                                             - metrics.parse_time(start)).total_seconds())
        self.assertEqual(by[planner]["times_from"], "log")
        self.assertFalse(any("activity window" in n for n in metrics.collect(self.cfg)["notes"]))

    def test_log_without_session_lines_falls_back_to_activity_windows(self):
        planner, w1, w2, curator = self.one_cycle()
        with open(self.cfg.action_log) as f:
            lines = [x for x in f.read().splitlines()
                     if not json.loads(x)["command"].startswith("session ")]
        with open(self.cfg.action_log, "w") as f:
            f.write("".join(x + "\n" for x in lines))
        data = metrics.collect(self.cfg)
        by = {r["session"]: r for r in data["sessions"]}
        self.assertEqual((by[planner]["times_from"], by[curator]["times_from"]),
                         ("actions", "actions"))
        self.assertEqual(by[w1]["times_from"], "task")
        self.assertTrue(any("activity window" in n for n in data["notes"]))
        self.assertIn("~", metrics.text(data))

    def test_cycle_filter_and_missing_usage_log(self):
        planner, w1, w2, curator = self.one_cycle()
        self.commit("project", "cycle9-worker1-old")
        data = metrics.collect(self.cfg, cycle=1)
        self.assertEqual({r["session"] for r in data["sessions"]}, {planner, w1, w2, curator})
        self.assertTrue(any("No usage records" in n for n in data["notes"]))
        self.assertEqual(metrics.collect(self.cfg, cycle=7)["sessions"], [])

    def test_outcomes_do_not_change_when_sessions_are_removed(self):
        """A Planner or Curator the cycle names is planned or curated, and other
        sessions keep their status, with or without their session rows."""
        self.start_loop()
        with self.m() as m:
            planner = m.session_create("planner")["name"]
        with msm.transaction(self.cfg.db, caller=planner) as m:
            m.cycle_create({"planner_session": planner, "headline": "h", "tasks": [
                {"shortname": "a", "instructions": "i", "branch": planner}]})
            m.session_status(planner, "done")
        with self.m() as m:
            lost = m.session_create("curator")["name"]
            m.session_status(lost, "expired")
            curator = m.session_create("curator")["name"]
            auditor = m.session_create("auditor")["name"]
            m.session_status(auditor, "done")
            op = m.session_create("operator", "mars")["name"]
            m.session_status(op, "done")
        with msm.transaction(self.cfg.db, caller=curator) as m:
            task = m.cycle_get()["tasks"][0]
            m.cycle_curate({"curator_session": curator, "report": "r", "tasks": [
                {"id": task["id"], "status": "accepted"}]})
            m.session_status(curator, "done")
        expected = {planner: "planned", curator: "curated", lost: "expired",
                    auditor: "done", op: "done"}

        def outcomes():
            return {r["session"]: r["outcome"] for r in metrics.collect(self.cfg)["sessions"]
                    if r["session"] in expected}
        self.assertEqual(outcomes(), expected)
        with self.m() as m:
            for name in expected:
                m.session_remove(name)
        self.assertEqual(outcomes(), expected)

    def test_operator_session_gets_the_cycle_planned_before_it(self):
        self.one_cycle()
        with self.m() as m:
            op = m.session_create("operator", "mars")["name"]
        data = metrics.collect(self.cfg, cycle=1)
        row = [r for r in data["sessions"] if r["session"] == op][0]
        self.assertEqual((row["role"], row["outcome"], row["end"]), ("operator", "active", None))


class TestCommand(MetricsCase):
    def run_cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main(["metrics", *args])
        return code, out.getvalue()

    def test_text_and_json(self):
        planner, w1, w2, curator = self.one_cycle()
        self.commit("project", w1)
        code, out = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("By cycle and role:", out)
        self.assertIn(w1, out)
        self.assertIn("accepted", out)
        self.assertNotIn("~", out)  # planner and curator times come from the log
        code, out = self.run_cli("--json", "--cycle", "1")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(len(data["sessions"]), 4)
        self.assertEqual(self.run_cli("--cycle")[0], 1)
        self.assertEqual(self.run_cli("--bogus")[0], 1)


if __name__ == "__main__":
    unittest.main()
