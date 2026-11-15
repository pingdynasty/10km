"""Script tests: drive the bin/ entry points (session, gate, dispatch) as
subprocesses against a temporary loop, never the live one.

`ScriptLoop` builds a loop root with a loop repo, a project repo and a database
outside the root, and runs scripts with an environment that points only at it.
`ScriptCase` gives each test a fresh one. Script tests for curate-* and later
cycles can reuse both.

Run: python3 -m unittest discover tests
"""
import fcntl
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

CODE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(CODE, "bin")
sys.path.insert(0, CODE)
from tenkm import init  # noqa: E402

GIT_ID = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
          "GIT_COMMITTER_EMAIL": "t@t"}
SUFFIX = r"[a-z0-9]{8}"
# Keep the host's system and global git config (hooks, for one, which slow every
# commit) out of test loops; tests of inherited config set their own.
HOST_GIT_OFF = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}


def _settings():
    """Names set in config.env: the caller's values must not leak into a test loop."""
    with open(os.path.join(CODE, "config.env")) as f:
        return set(re.findall(r"^\s*(?:\[.*\]\s*\|\|\s*)?([A-Z_]+)=", f.read(), re.M))


LEAKY = re.compile(r"^(LOOP_|MSM_|TENKM_)|^(SESSION|PROMPT_FILE|FIRST_MESSAGE|ONE_SHOT|"
                   r"SCRATCH_DIR|PYTHONPATH)$|_(AGENT|TIMEOUT|GATES)$")


def clean_env():
    """os.environ without anything that could point a script at another loop
    (agents run these tests inside a live loop session)."""
    drop = _settings()
    return {k: v for k, v in os.environ.items() if not LEAKY.search(k) and k not in drop}


def wait_for(predicate, timeout=30, interval=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


class ScriptLoop:
    """A temporary loop: <base>/root with central/loop and central/project, and its
    database at <base>/state/loop.db. Settings are passed as environment variables."""

    def __init__(self, base, **settings):
        self.base = base
        self.root = os.path.join(base, "root")
        self.db = os.path.join(base, "state", "loop.db")
        os.makedirs(os.path.dirname(self.db))
        self.env = dict(clean_env(), **GIT_ID)
        self.env.update(LOOP_ROOT=self.root, MSM_DB=self.db, NOTIFY_CMD="",
                        LOOP_AGENT="sleep 30", KILL_GRACE="2", **HOST_GIT_OFF)
        self.env.update(settings)
        self.central = os.path.join(self.root, "central")
        old = dict(os.environ)
        try:  # create_loop_repo reads the git identity from os.environ
            os.environ.update(GIT_ID)
            init.create_loop_repo(os.path.join(self.central, "loop"), source=CODE)
        finally:
            os.environ.clear()
            os.environ.update(old)
        project = os.path.join(self.central, "project")
        self.git(None, "init", "-q", "-b", "main", project)
        self.git(project, "commit", "-q", "--allow-empty", "-m", "start")
        self.ok("init")

    # --- running scripts ---------------------------------------------------
    def run(self, script, *args, session=None, env=None, timeout=120):
        """Run bin/<script> with the loop's environment. session sets LOOP_SESSION."""
        e = dict(self.env, **(env or {}))
        if session:
            e["LOOP_SESSION"] = session
        return subprocess.run([os.path.join(BIN, script), *args], env=e, capture_output=True,
                              text=True, timeout=timeout)

    def ok(self, script, *args, **kw):
        """Run a script that must succeed; return its stdout as JSON if it is JSON."""
        p = self.run(script, *args, **kw)
        if p.returncode != 0:
            raise AssertionError(f"{script} {' '.join(args)} exited {p.returncode}:\n"
                                 f"{p.stdout}\n{p.stderr}")
        try:
            return json.loads(p.stdout)
        except ValueError:
            return p.stdout

    def msm(self, *args, session=None):
        return self.ok("msm", *args, session=session)

    def git(self, cwd, *args):
        command = ["git"] + (["-C", cwd] if cwd else []) + list(args)
        return subprocess.run(command, env=self.env, check=True, capture_output=True,
                              text=True).stdout.strip()

    # --- loop state --------------------------------------------------------
    def sessions(self, role=None):
        return [s for s in self.msm("session", "list") if role is None or s["role"] == role]

    def session(self, role, username=None, **kw):
        args = [role] + ([username] if username else [])
        return self.ok("session", *args, **kw)

    def done(self, name):
        return self.msm("session", "done", name, session=name)

    def start(self):
        """Start the loop as the operator: phase plan."""
        return self.msm("loop", "start")

    def plan(self, *shortnames):
        """Run a Planner by hand: one task per shortname. Leaves phase = execute."""
        planner = self.session("planner")["name"]
        tasks = [{"shortname": s, "instructions": f"do {s}", "branch": planner}
                 for s in shortnames]
        self.msm("cycle", "create", json.dumps({"planner_session": planner,
                                                "headline": "test", "tasks": tasks}),
                 session=planner)
        self.done(planner)
        return planner

    def contribute(self, username="mars"):
        """A done operator session: work the Curator takes in any phase."""
        name = self.session("operator", username)["name"]
        self.done(name)
        return name

    # --- files -------------------------------------------------------------
    def worktree(self, session, repo="project"):
        return os.path.join(self.root, session, repo)

    def repo(self, repo):
        return os.path.join(self.central, repo)

    def commit(self, session, repo, path, text, message="change"):
        wt = self.worktree(session, repo)
        with open(os.path.join(wt, path), "w") as f:
            f.write(text)
        self.git(wt, "add", path)
        subprocess.run(["git", "-C", wt, "commit", "-q", "-m", message], check=True,
                       capture_output=True, env=dict(self.env, LOOP_SESSION=session))

    def branches(self, repo):
        return self.git(self.repo(repo), "branch", "--format=%(refname:short)").split()

    def evidence(self, pattern="*"):
        return sorted(glob.glob(os.path.join(self.root, ".10km", "evidence", pattern)))

    def kill_all(self):
        """Kill agents and gate runs left running."""
        groups = []
        try:
            groups += [int(s["handle"].split(":")[1]) for s in self.sessions()
                       if (s.get("handle") or "").startswith("process:")]
        except (AssertionError, ValueError, IndexError):
            pass
        for path in self.evidence("running-*.json"):
            try:
                with open(path) as f:
                    groups.append(int(json.load(f)["pgid"]))
            except (OSError, ValueError, KeyError):
                pass
        for pgid in groups:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass


class ScriptCase(unittest.TestCase):
    """A fresh ScriptLoop per test, with `settings` as its environment."""

    settings = {}

    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="10km-scripts-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.loop = ScriptLoop(tmp, **self.settings)
        self.addCleanup(self.loop.kill_all)
        self.tmp = tmp

    def assertExit(self, p, code):
        self.assertEqual(p.returncode, code, f"stdout:\n{p.stdout}\nstderr:\n{p.stderr}")

    def assertError(self, p, code):
        """A failed script: exit status code, and the same code in its JSON error."""
        self.assertExit(p, code)
        self.assertEqual(json.loads(p.stderr.strip().splitlines()[-1])["code"], code)


# --- session -----------------------------------------------------------------

class TestSessionScript(ScriptCase):
    def test_creates_record_directory_branch_and_worktree_per_repo(self):
        s = self.loop.session("operator", "mars")
        name = s["name"]
        self.assertRegex(name, rf"^operator-mars-{SUFFIX}$")
        self.assertEqual(s["working_directory"], os.path.join(self.loop.root, name))
        self.assertEqual(self.loop.msm("session", "get", name)["status"], "active")
        for repo in ("loop", "project"):
            wt = self.loop.worktree(name, repo)
            self.assertEqual(self.loop.git(wt, "symbolic-ref", "--short", "HEAD"), name)
            self.assertEqual(self.loop.git(wt, "rev-parse", "HEAD"),
                             self.loop.git(self.loop.repo(repo), "rev-parse", "main"))

    def test_names_follow_role_cycle_and_counters(self):
        self.loop.start()
        planner = self.loop.plan("a", "b")
        self.assertRegex(planner, rf"^cycle1-planner-{SUFFIX}$")
        w1 = self.loop.session("worker")["name"]
        w2 = self.loop.session("worker")["name"]
        self.assertRegex(w1, rf"^cycle1-worker1-{SUFFIX}$")
        self.assertRegex(w2, rf"^cycle1-worker2-{SUFFIX}$")
        self.assertEqual(self.loop.msm("task", "get", "--session", w1)["shortname"], "a")
        self.assertEqual(self.loop.msm("task", "get", "--session", w2)["shortname"], "b")
        self.assertRegex(self.loop.session("auditor")["name"], rf"^auditor1-{SUFFIX}$")

    def test_precondition_failures_exit_with_msm_code_and_leave_nothing(self):
        cases = [(["planner"], 2),               # loop stopped
                 (["curator"], 2),               # stopped
                 (["nobody"], 1),                # unknown role
                 (["operator"], 1),              # operator needs a username
                 (["planner", "mars"], 1),       # only operators take one
                 (["operator", "Bad_Name"], 1)]  # username syntax
        for args, code in cases:
            with self.subTest(args=args):
                self.assertError(self.loop.run("session", *args), code)
        self.loop.start()
        self.loop.session("planner")
        self.assertError(self.loop.run("session", "planner"), 2)  # one active Planner
        self.assertError(self.loop.run("session", "worker"), 2)   # phase is plan
        self.assertEqual([s["role"] for s in self.loop.sessions()], ["planner"])
        self.assertEqual(sorted(os.listdir(self.loop.root)), [".10km", "central"] +
                         [s["name"] for s in self.loop.sessions()])

    def test_usage_errors_are_einval_not_a_traceback(self):
        for args in ([], ["operator", "mars", "extra"]):
            with self.subTest(args=args):
                p = self.loop.run("session", *args)
                self.assertExit(p, 1)
                self.assertNotIn("Traceback", p.stderr)
        self.assertEqual(self.loop.sessions(), [])

    def test_branch_name_taken_is_eagain_and_rolls_back_other_repos(self):
        # Make the random suffix predictable, then take the name in the second repo.
        site = os.path.join(self.tmp, "site")
        os.makedirs(site)
        with open(os.path.join(site, "sitecustomize.py"), "w") as f:
            f.write("import secrets\nsecrets.choice = lambda seq: seq[0]\n")
        env = {"PYTHONPATH": site}
        taken = "operator-mars-aaaaaaaa"
        self.loop.git(self.loop.repo("project"), "branch", taken)
        p = self.loop.run("session", "operator", "mars", env=env)
        self.assertError(p, 4)
        self.assertEqual(self.loop.sessions(), [])
        self.assertFalse(os.path.exists(os.path.join(self.loop.root, taken)))
        self.assertNotIn(taken, self.loop.branches("loop"))  # the loop worktree was undone
        self.assertIn(taken, self.loop.branches("project"))  # someone else's: kept
        self.assertEqual(self.loop.git(self.loop.repo("loop"), "worktree", "list").count("\n"), 0)

    def test_git_failure_is_egit_and_rolls_back(self):
        self.loop.git(self.loop.repo("project"), "config", "tenkm.mainBranch", "missing")
        self.assertError(self.loop.run("session", "operator", "mars"), 5)
        self.assertEqual(self.loop.sessions(), [])
        self.assertEqual([b for b in self.loop.branches("loop") if b != "main"], [])
        self.assertEqual(sorted(os.listdir(self.loop.root)), [".10km", "central"])

    def test_crash_after_the_record_is_recovered_by_the_dispatcher(self):
        self.loop.start()
        self.loop.contribute()
        p = self.loop.run("session", "curator", env={"TENKM_FAULT": "session:after-record"})
        self.assertExit(p, 99)
        [crashed] = self.loop.sessions("curator")
        self.assertEqual((crashed["status"], crashed.get("handle")), ("active", None))
        self.assertError(self.loop.run("session", "curator"), 2)  # it still holds the role
        # The Dispatcher times the handle-less session out, and launches a new Curator.
        self.loop.ok("dispatch", env={"CURATOR_TIMEOUT": "-1"})
        curators = {s["name"]: s for s in self.loop.sessions("curator")}
        self.assertEqual(curators.pop(crashed["name"])["status"], "expired")
        [new] = curators.values()
        self.assertEqual(new["status"], "active")
        self.assertTrue(new["handle"].startswith("process:"))
        issues = self.loop.msm("issue", "list")
        self.assertTrue(any(crashed["name"] in i["title"] for i in issues))

    def test_crash_between_worktrees_leaves_a_retryable_loop(self):
        self.loop.start()
        p = self.loop.run("session", "planner",
                          env={"TENKM_FAULT": "session:after-worktree:loop"})
        self.assertExit(p, 99)
        [crashed] = self.loop.sessions("planner")
        # Expiry frees the role; a new Planner gets the same cycle and fresh worktrees.
        self.loop.msm("session", "expired", crashed["name"])
        planner = self.loop.session("planner")["name"]
        self.assertRegex(planner, rf"^cycle1-planner-{SUFFIX}$")
        self.assertTrue(os.path.isdir(self.loop.worktree(planner, "project")))


# --- gate --------------------------------------------------------------------

class GateCase(ScriptCase):
    def setUp(self):
        super().setUp()
        self.name = self.loop.session("operator", "mars")["name"]

    def gate(self, gates, tier="worker", name=None, **env):
        setting = {"worker": "WORKER_GATES", "validation": "VALIDATION_GATES"}[tier]
        p = self.loop.run("gate", tier, session=name or self.name,
                          env=dict({setting: gates}, **env))
        try:
            results = json.loads(p.stdout)
        except ValueError:
            results = None
        return p, results


class TestGateScript(GateCase):
    def test_refuses_without_an_active_session(self):
        self.assertExit(self.loop.run("gate", "worker"), 2)  # LOOP_SESSION unset
        self.assertExit(self.loop.run("gate", "worker", session="no-such-session"), 2)
        self.assertExit(self.loop.run("gate", session=self.name), 2)
        self.assertExit(self.loop.run("gate", "everything", session=self.name), 2)
        self.loop.done(self.name)
        p, _ = self.gate("true")
        self.assertExit(p, 2)
        self.assertIn("not an active session", p.stderr)

    def test_no_gates_pass(self):
        p, results = self.gate("")
        self.assertExit(p, 0)
        self.assertEqual(results, [])

    def test_passes_then_skips_on_the_same_tree_in_any_session(self):
        gates = "echo one\nloop: test -f config.env"
        p, results = self.gate(gates)
        self.assertExit(p, 0)
        self.assertEqual([(r["repo"], r["result"]) for r in results],
                         [("project", "passed"), ("loop", "passed")])
        with open(results[0]["log"]) as f:
            self.assertIn("one", f.read())
        p, again = self.gate(gates)
        self.assertEqual([r["result"] for r in again], ["skipped", "skipped"])
        self.assertEqual([r["log"] for r in again], [r["log"] for r in results])
        other = self.loop.session("operator", "venus")["name"]
        p, theirs = self.gate(gates, name=other)
        self.assertEqual([r["result"] for r in theirs], ["skipped", "skipped"])
        self.loop.commit(other, "project", "f", "x")
        p, changed = self.gate(gates, name=other)
        self.assertEqual([r["result"] for r in changed], ["passed", "skipped"])

    def test_tiers_read_their_own_setting(self):
        p = self.loop.run("gate", "validation", session=self.name,
                          env={"WORKER_GATES": "false", "VALIDATION_GATES": "true"})
        self.assertExit(p, 0)
        p = self.loop.run("gate", "worker", session=self.name,
                          env={"WORKER_GATES": "false", "VALIDATION_GATES": "true"})
        self.assertExit(p, 1)

    def test_failure_stops_reports_and_keeps_every_run_as_evidence(self):
        gates = "echo checking; test -f ok\necho never"
        p, results = self.gate(gates)
        self.assertExit(p, 1)
        self.assertEqual([r["result"] for r in results], ["failed"])  # stops at the first
        self.assertIn("gate failed: echo checking; test -f ok (in project)", p.stderr)
        self.assertIn("checking", p.stderr)  # the log's tail
        first = results[0]["log"]
        p, results = self.gate(gates)
        self.assertExit(p, 1)
        second = results[0]["log"]
        self.assertNotEqual(first, second)  # a failure is rerun, into a new log
        self.loop.commit(self.name, "project", "ok", "fixed")
        p, results = self.gate(gates)
        self.assertExit(p, 0)
        self.assertEqual([r["result"] for r in results], ["passed", "passed"])
        for log in (first, second):
            with open(log) as f:
                self.assertIn("checking", f.read())

    def test_exit_and_errexit_in_a_gate_still_record_its_status(self):
        for command, code in (("exit 0", 0), ("exit 4", 1), ("set -e; false; true", 1)):
            with self.subTest(command=command):
                self.assertExit(self.gate(command)[0], code)

    def test_gate_runs_in_the_session_worktree_with_scratch_dir(self):
        scratch = os.path.join(self.loop.root, self.name, "scratch")
        wt = self.loop.worktree(self.name, "project")
        command = (f'test "$(pwd -P)" = "$(cd {wt} && pwd -P)" && '
                   f'test "$SCRATCH_DIR" = "{scratch}" && test -d "$SCRATCH_DIR"')
        p, _ = self.gate(command)
        self.assertExit(p, 0)

    def test_still_running_exits_3_and_a_rerun_waits_on_the_same_run(self):
        command = "sleep 1; echo finished"
        p, results = self.gate(command, GATE_WAIT="0")
        self.assertExit(p, 3)
        self.assertEqual(results[0]["result"], "running")
        p, again = self.gate(command, GATE_WAIT="30")
        self.assertExit(p, 0)
        self.assertEqual((again[0]["result"], again[0]["log"]), ("passed", results[0]["log"]))
        self.assertEqual(len(self.loop.evidence(f"{self.name}-*.log")), 1)

    def test_killed_gate_counts_as_failed_and_is_rerun(self):
        command = "sleep 60"
        p, results = self.gate(command, GATE_WAIT="0")
        self.assertExit(p, 3)
        [running] = self.loop.evidence("running-*.json")
        with open(running) as f:
            os.killpg(json.load(f)["pgid"], signal.SIGKILL)
        p, failed = self.gate(command, GATE_WAIT="10")
        self.assertExit(p, 1)
        self.assertEqual(failed[0]["log"], results[0]["log"])
        with open(results[0]["log"][:-4] + ".rc") as f:
            self.assertEqual(f.read().strip(), "137")
        p, rerun = self.gate(command, GATE_WAIT="0")
        self.assertExit(p, 3)
        self.assertNotEqual(rerun[0]["log"], results[0]["log"])


# --- dispatch ----------------------------------------------------------------

class TestDispatchScript(ScriptCase):
    def dispatch(self, **env):
        p = self.loop.run("dispatch", env=env)
        self.assertExit(p, 0)
        return p.stdout

    def test_stopped_loop_launches_nothing(self):
        self.loop.contribute()
        self.dispatch()
        self.assertEqual([s["role"] for s in self.loop.sessions()], ["operator"])

    def test_launches_agent_with_prompt_handle_and_environment(self):
        self.loop.start()
        agent = 'env > env.txt; msm session done "$SESSION"'
        out = self.dispatch(LOOP_AGENT=agent)
        [planner] = self.loop.sessions("planner")
        name, directory = planner["name"], planner["working_directory"]
        self.assertIn(f"launched {name} (process:", out)
        self.assertTrue(planner["handle"].startswith("process:"))
        self.assertTrue(wait_for(lambda: self.loop.msm("session", "get", name)["status"]
                                 == "done"))
        with open(os.path.join(directory, "env.txt")) as f:
            env = dict(line.split("=", 1) for line in f.read().splitlines() if "=" in line)
        prompt = os.path.join(directory, "prompt.txt")
        for key, value in (("SESSION", name), ("LOOP_SESSION", name), ("PROMPT_FILE", prompt),
                           ("LOOP_ROOT", self.loop.root), ("MSM_DB", self.loop.db)):
            self.assertEqual(env[key], value)
        self.assertIn(name, env["FIRST_MESSAGE"])
        self.assertIn(prompt, env["FIRST_MESSAGE"])
        # Agents use the loop repo's own code.
        self.assertEqual(env["PATH"].split(os.pathsep)[0],
                         os.path.join(self.loop.central, "loop", "bin"))
        with open(prompt) as f:
            text = f.read()
        self.assertIn(f"Session: {name}", text)
        self.assertIn("Repos: loop, project", text)
        with open(os.path.join(CODE, "prompts", "planner.md")) as f:
            self.assertIn(f.read(), text)
        self.assertTrue(os.path.exists(os.path.join(directory, "agent.log")))

    def test_rerun_launches_nothing_twice(self):
        self.loop.start()
        self.dispatch()
        self.dispatch()
        self.assertEqual(len(self.loop.sessions("planner")), 1)

    def test_contributions_get_a_curator_in_any_phase(self):
        self.loop.start()
        self.loop.contribute()
        self.dispatch()
        self.assertEqual(sorted(s["role"] for s in self.loop.sessions()
                                if s["status"] == "active"), ["curator", "planner"])

    def test_workers_up_to_max_then_as_slots_free(self):
        self.loop.start()
        self.loop.plan("a", "b", "c")
        self.dispatch(MAX_WORKERS="2")
        workers = self.loop.sessions("worker")
        self.assertEqual(len(workers), 2)
        self.dispatch(MAX_WORKERS="2")
        self.assertEqual(len(self.loop.sessions("worker")), 2)
        self.loop.done(workers[0]["name"])
        self.dispatch(MAX_WORKERS="2")
        self.assertEqual(len(self.loop.sessions("worker")), 3)
        self.dispatch(MAX_WORKERS="5")  # no waiting task: launches fail harmlessly
        self.assertEqual(len(self.loop.sessions("worker")), 3)
        self.assertEqual({t["status"] for t in self.loop.msm("task", "list")},
                         {"done", "active"})
        self.assertEqual(self.loop.sessions("curator"), [])

    def test_time_out_sends_sigterm_first_and_relaunches_the_role(self):
        self.loop.start()
        agent = "trap 'echo term > term.txt; exit 0' TERM; while :; do sleep 0.1; done"
        self.dispatch(LOOP_AGENT=agent)
        [first] = self.loop.sessions("planner")
        time.sleep(0.5)  # let the trap be installed
        out = self.dispatch(LOOP_AGENT=agent, PLANNER_TIMEOUT="-1", KILL_GRACE="10")
        self.assertIn(f"expired {first['name']} (timed out)", out)
        self.assertTrue(os.path.exists(os.path.join(first["working_directory"], "term.txt")))
        planners = {s["name"]: s["status"] for s in self.loop.sessions("planner")}
        self.assertEqual(planners.pop(first["name"]), "expired")
        self.assertEqual(list(planners.values()), ["active"])  # the next Planner
        self.assertEqual(self.loop.msm("issue", "list"), [])  # the stop was confirmed
        # The expired agent can no longer change state.
        p = self.loop.run("msm", "session", "done", first["name"], session=first["name"])
        self.assertError(p, 2)

    def test_agent_ignoring_sigterm_is_killed(self):
        self.loop.start()
        agent = "trap '' TERM; while :; do sleep 0.1; done"
        self.dispatch(LOOP_AGENT=agent)
        [first] = self.loop.sessions("planner")
        pgid = int(first["handle"].split(":")[1])
        time.sleep(0.5)
        start = time.time()
        self.dispatch(LOOP_AGENT="sleep 30", PLANNER_TIMEOUT="-1", KILL_GRACE="1")
        self.assertGreaterEqual(time.time() - start, 1)
        with self.assertRaises(ProcessLookupError):
            os.killpg(pgid, 0)
        self.assertEqual(self.loop.msm("session", "get", first["name"])["status"], "expired")
        self.assertEqual(self.loop.msm("issue", "list"), [])

    def test_agent_that_died_is_expired_after_the_start_grace(self):
        self.loop.start()
        self.dispatch(LOOP_AGENT="exit 1")
        [first] = self.loop.sessions("planner")
        time.sleep(0.5)
        self.dispatch(LOOP_AGENT="sleep 30")  # within START_GRACE: left alone
        self.assertEqual(self.loop.msm("session", "get", first["name"])["status"], "active")
        out = self.dispatch(LOOP_AGENT="sleep 30", START_GRACE="0")
        self.assertIn(f"expired {first['name']} (not running)", out)

    def test_launcher_failure_removes_the_session(self):
        self.loop.start()
        out = self.dispatch(LOOP_AGENT="")
        self.assertIn("launch planner failed", out)
        self.assertEqual(self.loop.sessions(), [])
        self.assertEqual(self.loop.branches("loop"), ["main"])
        self.assertEqual(sorted(os.listdir(self.loop.root)), [".10km", "central"])
        self.dispatch()  # once fixed, the next pass launches
        self.assertEqual(len(self.loop.sessions("planner")), 1)

    def test_taken_branch_names_are_retried_then_given_up(self):
        site = os.path.join(self.tmp, "site")
        os.makedirs(site)
        with open(os.path.join(site, "sitecustomize.py"), "w") as f:
            f.write("import secrets\nsecrets.choice = lambda seq: seq[0]\n")
        self.loop.start()
        self.loop.git(self.loop.repo("loop"), "branch", "cycle1-planner-aaaaaaaa")
        self.dispatch(PYTHONPATH=site)
        self.assertEqual(self.loop.sessions(), [])

    def test_concurrent_pass_is_skipped(self):
        self.loop.start()
        os.makedirs(os.path.join(self.loop.root, ".10km"), exist_ok=True)
        with open(os.path.join(self.loop.root, ".10km", "dispatch.lock"), "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            self.dispatch()
            self.assertEqual(self.loop.sessions(), [])
        self.dispatch()
        self.assertEqual(len(self.loop.sessions("planner")), 1)

    def test_calling_session_is_ignored(self):
        self.loop.start()
        # Run from inside a session that no longer exists: the Dispatcher acts for
        # the operator, so this must not make msm refuse its changes.
        self.dispatch(LOOP_SESSION="cycle9-worker1-gonegone")
        [planner] = self.loop.sessions("planner")
        self.assertTrue(planner["handle"].startswith("process:"))

    def test_broken_config_is_reported_and_the_pass_still_runs(self):
        self.loop.start()
        bad = os.path.join(self.tmp, "bad.env")
        with open(bad, "w") as f:
            f.write("if then\n")
        out = self.dispatch(LOOP_CONFIG=bad)
        self.assertIn("config error", out)
        self.assertEqual(len(self.loop.sessions("planner")), 1)


if __name__ == "__main__":
    unittest.main()
