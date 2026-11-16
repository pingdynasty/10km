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
import shutil
import subprocess
import sys
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.dirname(TESTS)
BIN = os.path.join(CODE, "bin")
CONFIG = os.path.join(TESTS, "config.env")
FAKE_AGENT = os.path.join(TESTS, "fake-agent")
AGENT_VARS = ("LOOP_AGENT", "PLANNER_AGENT", "WORKER_AGENT", "CURATOR_AGENT",
              "AUDITOR_AGENT", "OPERATOR_AGENT")
# Real agent harnesses: no default test may run one.
HARNESSES = ("claude", "codex", "kiro-cli")
# The git identity of test commits, and of the loop repos tests create.
GIT_ID = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
          "GIT_COMMITTER_EMAIL": "t@t"}
# Keeps the host's system and global git config (hooks, for one, which slow every
# commit) out of test loops; tests of inherited config set their own.
HOST_GIT_OFF = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
# The random suffix of a session name.
SUFFIX = r"[a-z0-9]{8}"
# Seconds a test waits for a condition or a script before it fails: generous, so a
# loaded host (Workers gating at once) makes tests slower, not failing.
DEADLINE = 300
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
    template = os.environ.get(TEMPLATE_VAR)
    if template and os.path.isdir(os.path.join(template, ".git")):
        shutil.copytree(template, dest, symlinks=True)
    else:
        make_template(dest)


def project_repo(path, branch="main"):
    """A git repo at path with one empty commit on branch, as kickoff leaves one."""
    env = dict(os.environ, **GIT_ID, **HOST_GIT_OFF)
    for args in (["init", "-q", "-b", branch, path],
                 ["-C", path, "commit", "-q", "--allow-empty", "-m", "start"]):
        subprocess.run(["git", *args], env=env, check=True, capture_output=True)


def wait_for(predicate, timeout=DEADLINE, interval=0.1):
    """Poll predicate until it is true or timeout seconds pass; its last value."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


def read(path):
    """A file's text, or None if it doesn't exist."""
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return None


def read_env(path):
    """The variables in a file written by `env`."""
    return dict(line.split("=", 1) for line in (read(path) or "").splitlines() if "=" in line)


def fixed_suffix(directory):
    """Env that makes session name suffixes predictable ("aaaaaaaa") in scripts: a
    sitecustomize.py in directory, put on PYTHONPATH."""
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, "sitecustomize.py"), "w") as f:
        f.write("import secrets\nsecrets.choice = lambda seq: seq[0]\n")
    return {"PYTHONPATH": directory}


def isolate():
    """Apply clean_env() to os.environ, in place."""
    clean = clean_env()
    os.environ.clear()
    os.environ.update(clean)


isolate()
