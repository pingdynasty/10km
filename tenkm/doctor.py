"""tenkm.doctor: `10km doctor` checks that a loop can run, changing nothing (see
README, "Checking a loop"). Commands are only resolved, never run; the database
is opened read-only.

    results = doctor.checks(cfg)      # [(ok, name, detail), ...]
"""
import os
import pathlib
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys

from . import gate, gitutil, init, launchers, msm
from .config import BIN

GIT_MIN = (2, 26)  # `10km init` reads config with --show-scope
PYTHON_MIN = (3, 9)
ROLES = ("planner", "worker", "curator", "auditor", "operator")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def agent_path(cfg):
    """The PATH agents and gates get: the loop's bin, this code's bin, then PATH."""
    return os.pathsep.join([os.path.join(cfg.central, "loop", "bin"), BIN,
                            os.environ.get("PATH", "")])


def first_word(command):
    """The program a shell command starts with, after any VAR=value; None if empty.
    Raises ValueError if it can't be parsed."""
    words = shlex.split(command, comments=True)
    while words and ASSIGNMENT.match(words[0]):
        words.pop(0)
    return words[0] if words else None


def resolve(word, path, cwd=None):
    """Where bash would find word (a path, builtin or keyword), or None."""
    if "/" in word:
        full = os.path.join(cwd or os.getcwd(), word)
        return full if os.path.isfile(full) and os.access(full, os.X_OK) else None
    p = subprocess.run(["bash", "-c", 'command -v -- "$1"', "doctor", word],
                       env=dict(os.environ, PATH=path), capture_output=True, text=True)
    return p.stdout.strip() or None


def check_command(name, command, path, cwd=None):
    """A command's program resolves."""
    try:
        word = first_word(command)
    except ValueError as e:
        return False, name, f"can't parse {command!r}: {e}"
    if word is None:
        return False, name, "no command"
    where = resolve(word, path, cwd)
    return bool(where), name, f"{word} ({where})" if where else f"{word}: not found"


def check_version(name, found, minimum, detail):
    """found (a tuple, or None if unknown) is at least minimum."""
    good = found is not None and found >= minimum
    return good, name, detail if good else f"{detail}; needs {'.'.join(map(str, minimum))}+"


def check_tools(cfg):
    out = [(bool(shutil.which(t)), t, shutil.which(t) or "not found") for t in ("bash", "git")]
    out.append(check_version("python", sys.version_info[:2], PYTHON_MIN,
                             f"{sys.version.split()[0]} ({sys.executable})"))
    if shutil.which("git"):
        text = subprocess.run(["git", "--version"], capture_output=True, text=True).stdout
        m = re.search(r"(\d+)\.(\d+)", text)
        out.append(check_version("git version", m and (int(m[1]), int(m[2])), GIT_MIN,
                                 text.strip()))
    return out


def check_config(cfg):
    path, error = cfg.get("LOOP_CONFIG_PATH", ""), cfg.get("TENKM_CONFIG_ERROR")
    if not os.path.exists(path):
        config = (False, "config.env", f"{path}: missing")
    else:
        config = (not error, "config.env", f"{path}: {error}" if error else path)
    return [(os.path.isdir(cfg.root), "loop root", cfg.root), config]


def check_repo(cfg, repo):
    """The central worktree, main branch and generated hooks of a repo."""
    path, name = cfg.repo_path(repo), f"repo {repo}"
    if not gitutil.ok(path, "rev-parse", "--is-inside-work-tree"):
        return [(False, name, f"{path}: not a git worktree")]
    return [(True, name, path), check_main_branch(cfg, repo, f"{name} main branch"),
            check_hooks(cfg, path, f"{name} hooks")]


def check_main_branch(cfg, repo, name):
    branch = gitutil.git(cfg.repo_path(repo), "config", "--get", "tenkm.mainBranch",
                         check=False)
    if not branch:
        return False, name, "tenkm.mainBranch not set; run 10km init"
    if not gitutil.branch_exists(cfg, repo, branch):
        return False, name, f"{branch}: no such branch"
    return True, name, branch


def check_hooks(cfg, path, name):
    """The hooks dir `10km init` generates is in use and has every loop hook."""
    local = gitutil.git(path, "config", "--local", "--type=path", "--get", "core.hooksPath",
                        check=False)
    gen = init.session_hooks_path(path)
    if gen is None:
        if local:
            return True, name, f"own core.hooksPath {local}; loop hooks not used"
        return False, name, "not set up; run 10km init"
    wanted = init._executables(os.path.join(cfg.repo_path("loop"), "hooks"))
    missing = sorted(wanted - init._executables(gen))
    return not missing, name, f"missing {', '.join(missing)}; run 10km init" if missing else gen


def check_repos(cfg):
    if not os.path.isdir(cfg.central):
        return [(False, "repos", f"{cfg.central}: missing")]
    return [c for repo in cfg.repos() for c in check_repo(cfg, repo)]


def check_database(cfg):
    """Its integrity, schema version and loop record, read-only."""
    path = cfg.db
    if not os.path.exists(path):
        return [(False, "database", f"{path}: missing; run 10km init")]
    try:
        uri = pathlib.Path(os.path.abspath(path)).as_uri() + "?mode=ro"
        db = sqlite3.connect(uri, uri=True, timeout=10)
        try:
            integrity = db.execute("PRAGMA quick_check").fetchone()[0]
            version = db.execute("PRAGMA user_version").fetchone()[0]
            row = db.execute("SELECT current_cycle, phase, stopped FROM loop").fetchone()
        finally:
            db.close()
    except sqlite3.Error as e:
        return [(False, "database", f"{path}: {e}")]
    if integrity != "ok":
        return [(False, "database", f"{path}: {integrity}")]
    if row is None:
        return [(False, "database", f"{path}: no loop record; run 10km init")]
    if version > msm.SCHEMA_VERSION:
        return [(False, "database", f"{path}: schema {version} is newer than this code")]
    state = "stopped" if row[2] else "running"
    return [(True, "database", f"{path} (cycle {row[0]}, {row[1]}, {state})")]


def check_launcher(cfg):
    name = cfg.get("LAUNCHER") or "process"
    try:
        module = launchers.get(cfg)
    except Exception as e:  # any import failure is the finding
        return [(False, "launcher", f"{name}: {e}")]
    missing = [f for f in ("launch", "alive", "stop") if not callable(getattr(module, f, None))]
    return [(not missing, "launcher", f"{name}: no {', '.join(missing)}" if missing else name)]


def check_agents(cfg):
    path = agent_path(cfg)
    return [check_command(f"{role} agent", cfg.agent_command(role), path) for role in ROLES]


def check_gates(cfg):
    path = agent_path(cfg)
    return [check_command(f"{tier} gate {i}", command, path, cfg.repo_path(repo))
            for tier in ("worker", "validation")
            for i, (repo, command) in enumerate(gate.gates(cfg, tier), 1)]


def checks(cfg):
    """Every check, in order, as (ok, name, detail)."""
    out = check_tools(cfg) + check_config(cfg)
    if not shutil.which("git"):
        return out
    for group in (check_repos, check_database, check_launcher, check_agents, check_gates):
        out += group(cfg)
    return out


def main(cfg, argv=()):
    if argv:
        print("usage: 10km doctor", file=sys.stderr)
        return 2
    results = checks(cfg)
    for good, name, detail in results:
        print(f"{'ok  ' if good else 'FAIL'} {name}: {detail}")
    return 0 if all(good for good, _, _ in results) else 1
