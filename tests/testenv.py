"""The environment every test runs in: the test config, and nothing from the caller.

Importing this module (every test module does, first) removes from os.environ
whatever could point the tests at a live loop or a real agent harness (LOOP_*,
MSM_*, TENKM_*, *_AGENT, the session variables, and the names config.env sets),
and sets LOOP_CONFIG to tests/config.env, in which every agent command fails
loudly unless the test sets its own fake. Subprocesses the tests start inherit it.

`clean_env()` gives the same environment as a dict, for tests that build their
own. tests/run.py imports this module in each test process too.
"""
import os
import re

TESTS = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.dirname(TESTS)
CONFIG = os.path.join(TESTS, "config.env")
AGENT_VARS = ("LOOP_AGENT", "PLANNER_AGENT", "WORKER_AGENT", "CURATOR_AGENT",
              "AUDITOR_AGENT", "OPERATOR_AGENT")
# Real agent harnesses: no default test may run one.
HARNESSES = ("claude", "codex", "kiro-cli")

LEAKY = re.compile(r"^(LOOP_|MSM_|TENKM_)|^(SESSION|PROMPT_FILE|FIRST_MESSAGE|ONE_SHOT|"
                   r"SCRATCH_DIR|PYTHONPATH|USAGE_LOG)$|_(AGENT|TIMEOUT|GATES)$")


def settings():
    """Names set in the code's config.env: the caller's values must not leak in."""
    with open(os.path.join(CODE, "config.env")) as f:
        return set(re.findall(r"^\s*(?:\[.*\]\s*\|\|\s*)?([A-Z_]+)=", f.read(), re.M))


def clean_env(env=None):
    """env (default os.environ) without anything that could point a test at another
    loop or a real agent (agents run these tests inside a live loop session), and
    with LOOP_CONFIG set to the test config."""
    drop = settings()
    env = os.environ if env is None else env
    clean = {k: v for k, v in env.items() if not LEAKY.search(k) and k not in drop}
    clean["LOOP_CONFIG"] = CONFIG
    return clean


def isolate():
    """Apply clean_env() to os.environ, in place."""
    clean = clean_env()
    os.environ.clear()
    os.environ.update(clean)


isolate()
