"""tenkm.init: prepare a loop: database, central loop repo and project repos.

Repos that already exist are used as they are, so init also works for a loop being
migrated into place. Fails if the database already exists.
"""
import os
import shutil
import subprocess

from . import gitutil, msm
from .config import CODE_ROOT


def _clone_or_create_loop(cfg):
    dest = cfg.repo_path("loop")
    if os.path.isdir(os.path.join(dest, ".git")):
        return "existing"
    if subprocess.run(["git", "-C", CODE_ROOT, "rev-parse", "--git-dir"],
                      capture_output=True).returncode == 0:
        subprocess.run(["git", "clone", "-q", CODE_ROOT, dest], check=True)
        return "cloned"
    shutil.copytree(CODE_ROOT, dest, symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.db*", ".#*", "*~"))
    branch = cfg.get("MAIN_BRANCH") or "main"
    gitutil.git(cfg, dest, "init", "-q", "-b", branch)
    gitutil.git(cfg, dest, "add", "-A")
    gitutil.git(cfg, dest, *_identity(cfg), "commit", "-q", "-m", "Initial loop")
    return "created"


def _identity(cfg):
    return ["-c", f"user.name={cfg.get('GIT_NAME') or '10km'}",
            "-c", f"user.email={cfg.get('GIT_EMAIL') or '10km@localhost'}"]


def _project(cfg, name, url):
    dest = cfg.repo_path(name)
    if os.path.isdir(os.path.join(dest, ".git")):
        return "existing"
    if url:
        subprocess.run(["git", "clone", "-q", url, dest], check=True)
        return "cloned"
    branch = cfg.get("MAIN_BRANCH") or "main"
    subprocess.run(["git", "init", "-q", "-b", branch, dest], check=True)
    gitutil.git(cfg, dest, *_identity(cfg), "commit", "-q", "--allow-empty", "-m", "Initial commit")
    return "created"


def run(cfg):
    with msm.transaction(cfg.db, create=True) as m:
        m.init()
    os.makedirs(cfg.central, exist_ok=True)
    report = {"loop": _clone_or_create_loop(cfg)}
    for name, url in cfg.projects():
        report[name] = _project(cfg, name, url)
    hooks = os.path.join(cfg.repo_path("loop"), "hooks")
    for repo in cfg.repos():
        gitutil.git(cfg, cfg.repo_path(repo), "config", "core.hooksPath", hooks)
    return report
