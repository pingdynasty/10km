"""Tests for tenkm.usage: usage records kept in usage.jsonl.

Run: python3 -m unittest tests.test_usage
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv  # noqa: E402,F401  (test config, no caller env: tests/testenv.py)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tenkm import dispatch, msm, usage  # noqa: E402
from tenkm.config import Config  # noqa: E402

CLAUDE_RESULT = {
    "type": "result", "subtype": "success", "is_error": False, "duration_ms": 61234,
    "duration_api_ms": 58000, "num_turns": 12, "result": "Done.",
    "session_id": "4f1c-abcd", "total_cost_usd": 1.375,
    "usage": {"input_tokens": 1200, "output_tokens": 3400,
              "cache_read_input_tokens": 450000, "cache_creation_input_tokens": 23000,
              "server_tool_use": {"web_search_requests": 0}}}
FIGURES = {"harness_session_id": "4f1c-abcd", "duration_ms": 61234, "num_turns": 12,
           "total_cost_usd": 1.375, "input_tokens": 1200, "output_tokens": 3400,
           "cache_read_input_tokens": 450000, "cache_creation_input_tokens": 23000}


class UsageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("LOOP_SESSION", None)  # gates run the tests inside a session
        os.environ.pop("MSM_LOG", None)
        self.cfg = Config(LOOP_ROOT=self.root, MSM_DB=os.path.join(self.root, "db", "loop.db"),
                          LAUNCHER="process", LOOP_AGENT="claude -p --output-format json")

    def session(self, name="cycle1-worker1-abc", role="worker", log=None):
        directory = os.path.join(self.root, name)
        os.makedirs(directory, exist_ok=True)
        if log is not None:
            with open(os.path.join(directory, "agent.log"), "w") as f:
                f.write(log)
        return {"name": name, "role": role, "cycle": 1, "working_directory": directory}

    def lines(self):
        with open(self.cfg.usage_log) as f:
            return [json.loads(line) for line in f]

    # --- the path setting ----------------------------------------------------
    def test_path_defaults_next_to_database(self):
        self.assertEqual(self.cfg.usage_log, os.path.join(self.root, "db", "usage.jsonl"))

    def test_path_setting(self):
        self.cfg["USAGE_LOG"] = os.path.join(self.root, "elsewhere.jsonl")
        self.assertEqual(self.cfg.usage_log, os.path.join(self.root, "elsewhere.jsonl"))

    # --- parsing ---------------------------------------------------------------
    def test_parse_claude_result(self):
        self.assertEqual(usage.parse_result(json.dumps(CLAUDE_RESULT)), FIGURES)

    def test_parse_result_after_other_output(self):
        text = "warning: something\n" + json.dumps(CLAUDE_RESULT) + "\n"
        self.assertEqual(usage.parse_result(text), FIGURES)

    def test_parse_non_json_log(self):
        self.assertEqual(usage.parse_result("I did the task.\n{not json\n"), {})
        self.assertEqual(usage.parse_result('{"type": "message"}'), {})
        self.assertEqual(usage.parse_result(""), {})

    def test_missing_figures_are_omitted(self):
        partial = {"type": "result", "num_turns": 2, "usage": {"output_tokens": "many"}}
        self.assertEqual(usage.parse_result(json.dumps(partial)), {"num_turns": 2})

    def test_harness_name(self):
        self.assertEqual(usage.harness_name("/usr/bin/claude -p x"), "claude")
        self.assertEqual(usage.harness_name('codex exec "$FIRST_MESSAGE"'), "codex")
        self.assertEqual(usage.harness_name(""), "")

    # --- recording -------------------------------------------------------------
    def test_record_claude_run(self):
        usage.record(self.cfg, self.session(log=json.dumps(CLAUDE_RESULT)))
        [rec] = self.lines()
        self.assertRegex(rec.pop("recorded_at"), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(rec, dict(FIGURES, session="cycle1-worker1-abc", role="worker",
                                   cycle=1, harness="claude"))

    def test_record_non_json_log(self):
        self.cfg["WORKER_AGENT"] = "fake-agent"
        usage.record(self.cfg, self.session(log="plain text\n"))
        [rec] = self.lines()
        self.assertEqual(set(rec), {"session", "role", "cycle", "recorded_at", "harness"})
        self.assertEqual(rec["harness"], "fake-agent")

    def test_no_duplicate_record(self):
        s = self.session(log=json.dumps(CLAUDE_RESULT))
        self.assertIsNotNone(usage.record(self.cfg, s))
        self.assertIsNone(usage.record(self.cfg, s))
        usage.record(self.cfg, self.session("cycle1-worker2-def", log="x"))
        self.assertEqual([r["session"] for r in self.lines()],
                         ["cycle1-worker1-abc", "cycle1-worker2-def"])

    def test_untrusted_logs(self):
        s = self.session(log='{"type": "result", "duration_ms": NaN, "num_turns": 1e300}')
        self.assertNotIn("duration_ms", usage.record(self.cfg, s))
        fifo = self.session("cycle1-worker2-def")
        os.mkfifo(os.path.join(fifo["working_directory"], "agent.log"))
        self.assertIsNone(usage.record(self.cfg, fifo))  # returns at once, doesn't block

    def test_skips_runs_without_log_and_operators(self):
        self.assertIsNone(usage.record(self.cfg, self.session()))
        self.assertIsNone(usage.record(self.cfg, self.session("op-x", "operator", log="x")))
        self.assertFalse(os.path.exists(self.cfg.usage_log))

    def test_safe_record_never_raises(self):
        self.cfg["USAGE_LOG"] = os.path.join(self.root, "is-a-dir")
        os.makedirs(self.cfg["USAGE_LOG"])
        self.assertIsNone(usage.safe_record(self.cfg, self.session(log="x")))

    # --- the Dispatcher ----------------------------------------------------------
    def test_dispatcher_records_finished_sessions_once(self):
        with msm.transaction(self.cfg.db, create=True) as m:
            m.init()
            m.loop_start()
            s = m.session_create("auditor", None, self.root)
        directory = s["working_directory"]
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, "agent.log"), "w") as f:
            f.write(json.dumps(CLAUDE_RESULT))
        p = dispatch.Pass(self.cfg)
        with mock.patch.object(dispatch, "log"):
            p.record_usage()  # still active: not recorded
            self.assertFalse(os.path.exists(self.cfg.usage_log))
            with msm.transaction(self.cfg.db) as m:
                m.session_status(s["name"], "done")
            p.record_usage()
            p.record_usage()
        [rec] = self.lines()
        self.assertEqual((rec["session"], rec["role"], rec["num_turns"]),
                         (s["name"], "auditor", 12))

    def test_dispatcher_survives_bad_usage_log(self):
        os.makedirs(self.cfg.usage_log)  # unreadable as a file
        p = dispatch.Pass(self.cfg)
        with mock.patch.object(dispatch, "log"):
            p.record_usage()  # no database either: logs and returns


if __name__ == "__main__":
    unittest.main()
