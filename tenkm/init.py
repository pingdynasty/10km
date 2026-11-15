"""tenkm.init: prepare a loop directory.

    10km init      create the database if there is none, and register the
                   central repos: record each one's branch (tenkm.mainBranch)
                   and install the loop's git hooks, where not already set.

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
        if not gitutil.ok(cfg, path, "config", "--get", "core.hooksPath"):
            gitutil.git(cfg, path, "config", "core.hooksPath", hooks)
        report[repo] = gitutil.main_branch(cfg, repo)
    return report
