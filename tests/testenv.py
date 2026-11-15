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
# The git identity of test commits, and of the loop repos tests create.
GIT_ID = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
          "GIT_COMMITTER_EMAIL": "t@t"}
# A loop repo built once per run by tests/run.py, which tests copy (loop_repo()).
TEMPLATE_VAR = "TESTS_LOOP_TEMPLATE"

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


def make_template(dest):
    """Build the run's template loop repo at dest (tests/run.py does, once per run)."""
    import sys
    sys.path.insert(0, CODE)
    from tenkm import init
    saved = dict(os.environ)
    try:  # create_loop_repo reads the git identity from os.environ
        os.environ.update(GIT_ID)
        init.create_loop_repo(dest, source=CODE)
    finally:
        os.environ.clear()
        os.environ.update(saved)


def loop_repo(dest):
    """Create a loop repo at dest as init.create_loop_repo(dest) does, a copy of the
    code with one commit by GIT_ID: a copy of the run's template if tests/run.py
    made one (TEMPLATE_VAR), which is faster than a fresh repo, else a fresh repo."""
    import shutil
    template = os.environ.get(TEMPLATE_VAR)
    if template and os.path.isdir(os.path.join(template, ".git")):
        shutil.copytree(template, dest, symlinks=True)
    else:
        make_template(dest)


def isolate():
    """Apply clean_env() to os.environ, in place."""
    clean = clean_env()
    os.environ.clear()
    os.environ.update(clean)


isolate()
