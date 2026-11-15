"""tenkm.doctor: check that a loop can run, without changing anything.

    10km doctor    one line per check, `ok` or `FAIL` and why; exit 1 on any failure

It checks the tools (bash, git, Python), the git version (GIT_MIN, what
`10km init` needs), the loop root, config.env, each central repo (its worktree,
main branch, extensions.worktreeConfig and the hooks dir `10km init`
generates), the database, the launcher, the agent command of every role and the
gates. Commands are only resolved on the agents' PATH (as the Dispatcher sets
it), never run. The database is opened read-only.

    from tenkm import doctor
    results = doctor.checks(cfg)      # [(ok, name, detail), ...]
"""
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys

from . import gate, gitutil, init, launchers, msm
from .config import BIN

GIT_MIN = (2, 26)
PYTHON_MIN = (3, 9)
ROLES = ("planner", "worker", "curator", "auditor", "operator")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def agent_path(cfg):
    """The PATH agents and gates get: the loop's bin, this code's bin, then PATH."""
    return os.pathsep.join([os.path.join(cfg.central, "loop", "bin"), BIN,
                            os.environ.get("PATH", "")])


def first_word(command):
    """The program a shell command starts with, skipping VAR=value assignments.
    None if it is empty; raises ValueError if it can't be parsed."""
    words = shlex.split(command, comments=True)
    while words and ASSIGNMENT.match(words[0]):
        words.pop(0)
    return words[0] if words else None


def resolve(word, path, cwd=None):
    """Where bash would find word (a path, builtin or keyword), or None. Nothing runs
    but `command -v`."""
    if "/" in word:
        full = os.path.join(cwd or os.getcwd(), word)
        return full if os.path.isfile(full) and os.access(full, os.X_OK) else None
    p = subprocess.run(["bash", "-c", 'command -v -- "$1"', "doctor", word],
                       env=dict(os.environ, PATH=path), capture_output=True, text=True)
    return p.stdout.strip() or None if p.returncode == 0 else None


def check_command(command, path, cwd=None):
    """(ok, why) for a shell command: its program resolves."""
    try:
        word = first_word(command)
    except ValueError as e:
        return False, f"can't parse {command!r}: {e}"
    if word is None:
        return False, "empty"
    where = resolve(word, path, cwd)
    if where is None:
        return False, f"{word}: not found"
    return True, f"{word} ({where})"


def _git_version():
    p = subprocess.run(["git", "--version"], capture_output=True, text=True)
    m = re.search(r"(\d+)\.(\d+)", p.stdout)
    return (int(m.group(1)), int(m.group(2))) if p.returncode == 0 and m else None, \
        p.stdout.strip()


def check_tools(cfg):
    out = []
    for tool in ("bash", "git"):
        where = shutil.which(tool)
        out.append((bool(where), tool, where or "not found on PATH"))
    version = sys.version_info[:2]
    out.append((version >= PYTHON_MIN, "python",
                f"{sys.version.split()[0]} ({sys.executable})"
                + ("" if version >= PYTHON_MIN else
                   f"; needs {'.'.join(map(str, PYTHON_MIN))} or later")))
    if shutil.which("git"):
        found, text = _git_version()
        good = found is not None and found >= GIT_MIN
        out.append((good, "git version", text + ("" if good else
                    f"; needs {'.'.join(map(str, GIT_MIN))} or later")))
    return out


def check_config(cfg):
    out = [(os.path.isdir(cfg.root), "loop root", cfg.root)]
    path = cfg.get("LOOP_CONFIG_PATH", "")
    if not os.path.exists(path):
        out.append((False, "config.env", f"{path}: missing"))
    elif cfg.get("TENKM_CONFIG_ERROR"):
        out.append((False, "config.env", f"{path}: {cfg['TENKM_CONFIG_ERROR']}"))
    else:
        out.append((True, "config.env", path))
    return out


def check_repo(cfg, repo):
    """The central worktree, main branch, worktreeConfig and generated hooks of a repo."""
    path, name = cfg.repo_path(repo), f"repo {repo}"
    if not gitutil.ok(path, "rev-parse", "--is-inside-work-tree"):
        return [(False, name, f"{path}: not a git worktree")]
    out = [(True, name, path)]
    configured = gitutil.git(path, "config", "--get", "tenkm.mainBranch", check=False)
    branch = gitutil.main_branch(cfg, repo)
    if not configured:
        out.append((False, f"{name} main branch", "tenkm.mainBranch not set; run 10km init"))
    elif not gitutil.branch_exists(cfg, repo, branch):
        out.append((False, f"{name} main branch", f"{branch}: no such branch"))
    else:
        out.append((True, f"{name} main branch", branch))
    local = gitutil.git(path, "config", "--local", "--type=path", "--get", "core.hooksPath",
                        check=False)
    gen = init.generated_dir(path)
    if local and not init._same_dir(local, gen):
        out.append((True, f"{name} hooks", f"own core.hooksPath {local}; loop hooks not used"))
        return out
    enabled = gitutil.git(path, "config", "--local", "--type=bool", "--get",
                          "extensions.worktreeConfig", check=False) == "true"
    out.append((enabled, f"{name} worktreeConfig",
                "enabled" if enabled else "extensions.worktreeConfig not set; run 10km init"))
    if not os.path.isdir(gen):
        out.append((False, f"{name} hooks", f"{gen}: missing; run 10km init"))
        return out
    wanted = init._executables(os.path.join(cfg.repo_path("loop"), "hooks"))
    missing = sorted(wanted - init._executables(gen))
    out.append((not missing, f"{name} hooks",
                f"{gen}: missing {', '.join(missing)}; run 10km init" if missing else gen))
    return out


def check_repos(cfg):
    if not os.path.isdir(cfg.central):
        return [(False, "repos", f"{cfg.central}: missing")]
    return [c for repo in cfg.repos() for c in check_repo(cfg, repo)]


def check_database(cfg):
    """Open the database read-only: its schema version, integrity and loop record."""
    path = cfg.db
    if not os.path.exists(path):
        return [(False, "database", f"{path}: missing; run 10km init")]
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        try:
            integrity = db.execute("PRAGMA quick_check").fetchone()[0]
            version = db.execute("PRAGMA user_version").fetchone()[0]
            has_loop = db.execute(
                "SELECT name FROM sqlite_master WHERE name = 'loop'").fetchone()
            row = db.execute("SELECT current_cycle, phase, stopped, reason FROM loop"
                             ).fetchone() if has_loop else None
        finally:
            db.close()
    except sqlite3.Error as e:
        return [(False, "database", f"{path}: {e}")]
    if integrity != "ok":
        return [(False, "database", f"{path}: {integrity}")]
    if row is None:
        return [(False, "database", f"{path}: no loop record; run 10km init")]
    if version > msm.SCHEMA_VERSION:
        return [(False, "database", f"{path}: schema {version} is newer than this code's "
                                    f"{msm.SCHEMA_VERSION}")]
    state = f"stopped: {row[3] or 'not started'}" if row[2] else "running"
    return [(True, "database", f"{path} (cycle {row[0]}, phase {row[1]}, {state}, "
                               f"schema {version})")]


def check_launcher(cfg):
    name = cfg.get("LAUNCHER") or "process"
    try:
        module = launchers.get(cfg)
    except Exception as e:  # any import failure is the finding
        return [(False, "launcher", f"{name}: {e}")]
    missing = [f for f in ("launch", "alive", "stop") if not callable(getattr(module, f, None))]
    if missing:
        return [(False, "launcher", f"{name}: no {', '.join(missing)}")]
    return [(True, "launcher", name)]


def check_agents(cfg):
    path = agent_path(cfg)
    out = []
    for role in ROLES:
        command = cfg.agent_command(role)
        if not command:
            out.append((False, f"{role} agent", f"no command: set LOOP_AGENT or "
                                                f"{role.upper()}_AGENT"))
            continue
        good, why = check_command(command, path)
        out.append((good, f"{role} agent", why))
    return out


def check_gates(cfg):
    path = agent_path(cfg)
    out = []
    for tier in ("worker", "validation"):
        tier_gates = gate.gates(cfg, tier)
        if not tier_gates:
            out.append((True, f"{tier} gates", "none configured"))
        for i, (repo, command) in enumerate(tier_gates, 1):
            good, why = check_command(command, path, cfg.repo_path(repo))
            out.append((good, f"{tier} gate {i}", f"{repo}: {why}"))
    return out


def checks(cfg):
    """Every check, in order, as (ok, name, detail)."""
    out = check_tools(cfg) + check_config(cfg)
    if not shutil.which("git"):
        return out + [(False, "repos", "git not found")]
    for group in (check_repos, check_database, check_launcher, check_agents, check_gates):
        out += group(cfg)
    return out


def main(cfg, argv=()):
    if argv:
        print("usage: 10km doctor", file=sys.stderr)
        return 1
    results = checks(cfg)
    for good, name, detail in results:
        print(f"{'ok  ' if good else 'FAIL'} {name}: {detail}")
    return 0 if all(good for good, _, _ in results) else 1
