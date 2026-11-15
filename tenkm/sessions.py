"""tenkm.sessions: create and remove sessions.

A session is a record in the database, a directory, and a branch and worktree in
every repo, all named after the session. Creation is serialised with a file lock
and rolled back completely if any step fails.
"""
import fcntl
import os
import shutil
from contextlib import contextmanager

from . import gitutil, state

EAGAIN = 4  # the session's branch name is already taken
EGIT = 5    # git or worktree creation failed


class SessionError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


@contextmanager
def lock(cfg, name, blocking=True):
    """An exclusive file lock in the loop's state directory."""
    os.makedirs(cfg.state_dir, exist_ok=True)
    with open(os.path.join(cfg.state_dir, f"{name}.lock"), "w") as f:
        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(f, flags)
        except BlockingIOError:
            yield False
            return
        yield True


def create(cfg, role, username=None):
    """Create a session for a role. Returns its record; raises SessionError.

    Codes: those of `msm session create` (1 EINVAL, 2 EPERM, 3 ENOENT),
    4 if the branch name is taken, 5 on git errors.
    """
    with lock(cfg, "session"):
        try:
            with state.transaction(cfg.db) as m:
                session = m.session_create(role, username, cfg.root)
        except state.MsmError as e:
            raise SessionError(e.code, e.message)
        name, directory = session["name"], session["working_directory"]
        created = []
        try:
            os.makedirs(directory, exist_ok=True)
            for repo in cfg.repos():
                if gitutil.branch_exists(cfg, repo, name):
                    raise SessionError(EAGAIN, f"branch {name} exists in {repo}")
                base = gitutil.main_branch(cfg, repo)
                try:
                    gitutil.git(cfg, cfg.repo_path(repo), "worktree", "add", "-q", "-b", name,
                                os.path.join(directory, repo), base)
                except gitutil.GitError as e:
                    raise SessionError(EGIT, str(e))
                created.append(repo)
        except BaseException:
            _undo(cfg, name, directory, created)
            raise
        return session


def _undo(cfg, name, directory, repos):
    for repo in repos:
        gitutil.ok(cfg, cfg.repo_path(repo), "worktree", "remove", "--force",
                   os.path.join(directory, repo))
        gitutil.ok(cfg, cfg.repo_path(repo), "branch", "-D", name)
    shutil.rmtree(directory, ignore_errors=True)
    try:
        with state.transaction(cfg.db) as m:
            m.session_remove(name)
    except state.MsmError:
        pass


def protected_branches(m):
    """Branches referenced by open issues. Scripts never remove these."""
    return {i["branch"] for i in m.list("issue", '{"status": "open"}') if i.get("branch")}


def remove(cfg, name, protected=()):
    """Remove a session's worktrees, unprotected branches, directory and record."""
    directory = os.path.join(cfg.root, name)
    for repo in cfg.repos():
        path = cfg.repo_path(repo)
        if not os.path.isdir(path):
            continue
        gitutil.ok(cfg, path, "worktree", "remove", "--force", os.path.join(directory, repo))
        if name not in protected:
            gitutil.ok(cfg, path, "branch", "-D", name)
        gitutil.ok(cfg, path, "worktree", "prune")
    shutil.rmtree(directory, ignore_errors=True)
    try:
        with state.transaction(cfg.db) as m:
            m.session_remove(name)
    except state.MsmError:
        pass
