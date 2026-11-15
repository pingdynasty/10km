"""tenkm.sessions: create and remove sessions.

A session is a record in the database, a directory, and a branch and worktree in
every repo, all named after the session. Creation is serialised with a file lock
and rolled back completely if any step fails.
"""
import os
import shutil

from . import faults, gitutil, msm, usage
from .locks import lock

EAGAIN = 4  # the session's branch name is already taken
EGIT = 5    # git or worktree creation failed


class SessionError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def create(cfg, role, username=None):
    """Create a session for a role. Returns its record; raises SessionError.

    Codes: those of `msm session create` (1 EINVAL, 2 EPERM, 3 ENOENT),
    4 if the branch name is taken, 5 on git errors.
    """
    with lock(cfg, "session"):
        try:
            with msm.transaction(cfg.db) as m:
                session = m.session_create(role, username, cfg.root)
        except msm.MSMError as e:
            raise SessionError(e.code, e.message)
        name, directory = session["name"], session["working_directory"]
        faults.point("session:after-record")
        created = []
        try:
            try:
                os.makedirs(directory, exist_ok=True)
                for repo in cfg.repos():
                    if gitutil.branch_exists(cfg, repo, name):
                        raise SessionError(EAGAIN, f"branch {name} exists in {repo}")
                    base = gitutil.main_branch(cfg, repo)
                    gitutil.git(cfg, cfg.repo_path(repo), "worktree", "add", "-q", "-b", name,
                                os.path.join(directory, repo), base)
                    created.append(repo)
                    faults.point(f"session:after-worktree:{repo}")
            except (gitutil.GitError, OSError) as e:
                raise SessionError(EGIT, str(e))
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
        with msm.transaction(cfg.db) as m:
            m.session_remove(name)
    except msm.MSMError:
        pass


def protected_branches(m):
    """Branches referenced by unresolved (open or answered) issues (R206). Scripts never
    remove these."""
    return {i["branch"] for i in m.list("issue")
            if i["status"] in msm.UNRESOLVED and i.get("branch")}


def remove(cfg, name, protected=()):
    """Remove a session's worktrees, unprotected branches, directory and record.

    Checks the caller first, so an expired caller removes nothing. Records the
    session's usage first, if the Dispatcher hasn't yet.
    """
    with msm.transaction(cfg.db) as m:
        m.check_caller()
        session = m.one("SELECT * FROM sessions WHERE name = ?", name)
    if session is not None:
        usage.safe_record(cfg, dict(session))
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
    with msm.transaction(cfg.db) as m:
        if m.one("SELECT 1 FROM sessions WHERE name = ?", name):
            m.session_remove(name)
