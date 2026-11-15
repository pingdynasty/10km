"""tenkm.init: prepare a loop directory.

    10km init      create the database if there is none, and register the
                   central repos: record each one's branch (tenkm.mainBranch)
                   and install the loop's git hooks, where not already set.

Hooks: init sets the repo's own (local) core.hooksPath to the loop's hooks/ unless
the repo already sets one. A core.hooksPath inherited from system or global config
is recorded in tenkm.chainHooksPath, and the loop's hooks run the hook of the same
name from there (hooks/chain), so those hooks still run.

Kickoff (`10km kickoff`) calls this; run it again after adding a repo to central/.
The central worktrees are the source of truth for which repos the loop has: init
never clones or creates project repos. `create_loop_repo` makes a loop repo from a
copy of 10km, for the container's first start and for tests.
"""
import os
import shutil
import subprocess

from . import gitutil, msm
from .config import CODE_ROOT


def create_loop_repo(dest, source=CODE_ROOT, branch="main"):
    """Create a loop repo at dest from a copy of the 10km code, with one commit."""
    shutil.copytree(source, dest, symlinks=True,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", "*.db*", ".#*", "*~"))
    env = dict(os.environ)
    env.setdefault("GIT_AUTHOR_NAME", "10km")
    env.setdefault("GIT_AUTHOR_EMAIL", "10km@localhost")
    env.setdefault("GIT_COMMITTER_NAME", env["GIT_AUTHOR_NAME"])
    env.setdefault("GIT_COMMITTER_EMAIL", env["GIT_AUTHOR_EMAIL"])
    for args in (["init", "-q", "-b", branch], ["add", "-A"], ["commit", "-q", "-m", "Loop repo"]):
        subprocess.run(["git", "-C", dest, *args], env=env, check=True, capture_output=True)


def run(cfg):
    """Create the database if needed and register the central repos. Safe to rerun."""
    loop = cfg.repo_path("loop")
    if not os.path.exists(os.path.join(loop, ".git")):
        raise msm.MSMError(msm.ENOENT, f"no loop repo at {loop}; run 10km from a loop "
                                       "directory, or set LOOP_ROOT")
    report = {}
    with msm.transaction(cfg.db, create=True) as m:
        if m.one("SELECT name FROM sqlite_master WHERE name = 'loop'"):
            report["database"] = "existing"
        else:
            m.init()
            report["database"] = "created"
    hooks = os.path.join(loop, "hooks")
    for repo in cfg.repos():
        path = cfg.repo_path(repo)
        if not gitutil.ok(cfg, path, "config", "--get", "tenkm.mainBranch"):
            gitutil.git(cfg, path, "config", "tenkm.mainBranch",
                        gitutil.git(cfg, path, "symbolic-ref", "--short", "HEAD"))
        install_hooks(cfg, path, hooks)
        report[repo] = gitutil.main_branch(cfg, repo)
    return report


def _same_dir(a, b):
    return os.path.realpath(a) == os.path.realpath(b)


def install_hooks(cfg, path, hooks):
    """Point the repo at the loop's hooks dir, chaining to any inherited one.

    Only the repo's local core.hooksPath counts: if it is set to anything other
    than the loop's hooks, leave the repo alone. Otherwise set it, and record the
    core.hooksPath from global or system config (global wins, as in git) in
    tenkm.chainHooksPath, or clear it if there is none. Never chains to itself.
    Reads config with --show-scope (git 2.26+), so it sees what git itself uses.
    """
    _, out, _ = gitutil.run(cfg, path, "config", "--show-scope", "--type=path", "--get-all",
                            "core.hooksPath")
    values = dict(line.split("\t", 1) for line in out.splitlines() if "\t" in line)
    local = values.get("local", "")
    if local and not _same_dir(local, hooks):
        return
    inherited = values.get("global") or values.get("system", "")
    if not local:
        gitutil.git(cfg, path, "config", "--local", "core.hooksPath", hooks)
    if inherited and not _same_dir(inherited, hooks):
        gitutil.git(cfg, path, "config", "--local", "tenkm.chainHooksPath", inherited)
    else:
        gitutil.git(cfg, path, "config", "--local", "--unset-all", "tenkm.chainHooksPath",
                    check=False)
