"""tenkm.gate: run the configured gates for a session.

    gate worker        WORKER_GATES (Workers, before done)
    gate validation    VALIDATION_GATES (the Curator, Step 7)

Each gate is one line of the setting: `command`, or `repo: command` to run it in
another repo's worktree (default: the first project repo). Gates run in the
calling session's worktree (LOOP_SESSION), with SCRATCH_DIR set to the
session's scratch directory.

- A gate already passed on the same tree is skipped.
- A gate runs detached, so a tool-call time limit can't kill it; `gate` waits up
  to GATE_WAIT seconds, and rerunning it waits on the same run.
- Every run's log is kept as evidence and never overwritten.

A pass is only cached for committed work: with uncommitted changes the gate runs
but its result isn't reused.

Exit status: 0 all passed, 1 a gate failed, 2 refused, 3 still running (rerun to wait).
"""
import hashlib
import json
import os
import subprocess
import sys
import time

from . import config, gitutil, msm
from .launchers import process
from .locks import lock

EXIT_FAILED, EXIT_RUNNING = 1, 3


def gates(cfg, tier):
    setting = {"worker": "WORKER_GATES", "validation": "VALIDATION_GATES"}[tier]
    projects = cfg.projects()
    default = projects[0] if projects else "loop"
    out = []
    for line in cfg.lines(setting):
        repo, sep, command = line.partition(": ")
        if sep and repo in cfg.repos():
            out.append((repo, command))
        else:
            out.append((default, line))
    return out


def _evidence(cfg):
    path = os.path.join(cfg.state_dir, "evidence")
    os.makedirs(path, exist_ok=True)
    return path


def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def _new_log(evidence, name):
    """A log path that doesn't exist yet: evidence is never overwritten."""
    n = 0
    while True:
        path = os.path.join(evidence, f"{name}{'-' + str(n) if n else ''}.log")
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return path
        except FileExistsError:
            n += 1


def run_gate(cfg, session, repo, command, wait):
    """Run one gate. Returns (status, log): status 'passed', 'skipped', 'failed', 'running'."""
    cwd = os.path.join(session["working_directory"], repo)
    cacheable = not gitutil.git(cfg, cwd, "status", "--porcelain")
    tree = gitutil.git(cfg, cwd, "rev-parse", "HEAD^{tree}")
    key = f"{hashlib.sha1(command.encode()).hexdigest()[:12]}-{tree[:12]}"
    if not cacheable:
        key += f"-dirty-{session['name']}"
    evidence = _evidence(cfg)
    passed_path = os.path.join(evidence, "passed.json")
    running_path = os.path.join(evidence, f"running-{key}.json")
    with lock(cfg, "gate"):
        passed = _load(passed_path, {})
        if cacheable and key in passed:
            return "skipped", passed[key]
        run = _load(running_path, None)
        if run is None or os.path.exists(run["rc"]) and _rc(run) != 0:
            log = _new_log(evidence, f"{session['name']}-{repo}-{key}")
            rc_path = log[:-4] + ".rc"
            scratch = os.path.join(session["working_directory"], "scratch")
            os.makedirs(scratch, exist_ok=True)
            # The command runs in a subshell, so its own exit or set -e can't skip
            # recording its status.
            script = (f'(\n{command}\n)\nrc=$?\n'
                      f'echo "$rc" > "{rc_path}.tmp" && mv "{rc_path}.tmp" "{rc_path}"\n')
            with open(log, "ab") as f:
                f.write(f"$ {command}\n# repo {repo}, tree {tree}\n".encode())
                f.flush()
                child = subprocess.Popen(["bash", "-c", script], cwd=cwd, stdout=f, stderr=f,
                                         stdin=subprocess.DEVNULL, start_new_session=True,
                                         env=dict(os.environ, SCRATCH_DIR=scratch))
            run = {"log": log, "rc": rc_path, "command": command, "repo": repo,
                   "pgid": child.pid}
            _save(running_path, run)
    deadline = time.time() + wait
    while not os.path.exists(run["rc"]):
        if not process._group_exists(run["pgid"]) and not os.path.exists(run["rc"]):
            with open(run["rc"], "w") as f:  # killed before it could record its status
                f.write("137\n")
            break
        if time.time() >= deadline:
            return "running", run["log"]
        time.sleep(1)
    with lock(cfg, "gate"):
        if _rc(run) == 0:
            if cacheable:
                passed = _load(passed_path, {})
                passed[key] = run["log"]
                _save(passed_path, passed)
            try:
                os.remove(running_path)
            except FileNotFoundError:
                pass
            return "passed", run["log"]
        try:
            os.remove(running_path)  # a failed run is retried on the next call
        except FileNotFoundError:
            pass
        return "failed", run["log"]


def _rc(run):
    try:
        with open(run["rc"]) as f:
            return int(f.read().strip() or 1)
    except (OSError, ValueError):
        return 1


def _tail(path, n=40):
    try:
        with open(path, errors="replace") as f:
            return "".join(f.readlines()[-n:])
    except OSError:
        return ""


def main(argv):
    if len(argv) != 1 or argv[0] not in ("worker", "validation"):
        print("usage: gate worker|validation", file=sys.stderr)
        return 2
    cfg = config.load()
    name = os.environ.get("LOOP_SESSION", "")
    with msm.transaction(cfg.db) as m:
        session = m.one("SELECT * FROM sessions WHERE name = ?", name) if name else None
    if session is None or session["status"] != "active":
        print(f"LOOP_SESSION {name or '(unset)'} is not an active session; stop.", file=sys.stderr)
        return 2
    session = dict(session)
    wait = cfg.int("GATE_WAIT", 540)
    results, status = [], 0
    for repo, command in gates(cfg, argv[0]):
        state, log = run_gate(cfg, session, repo, command, wait)
        results.append({"repo": repo, "command": command, "result": state, "log": log})
        if state == "running":
            status = EXIT_RUNNING
            break
        if state == "failed":
            print(f"gate failed: {command} (in {repo})\n--- last lines of {log} ---\n"
                  f"{_tail(log)}", file=sys.stderr)
            status = EXIT_FAILED
            break
    print(json.dumps(results, indent=1))
    return status
