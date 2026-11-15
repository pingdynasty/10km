"""tenkm.sessions: create (R114-R135) and remove sessions."""
import os
import shutil

from . import faults, gitutil, init, msm, usage
from .locks import lock

EAGAIN = 4  # the session's branch name is already taken
EGIT = 5    # git or worktree creation failed


class SessionError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def repo_setup(cfg):
    """{repo: (base, hooks)}: the branch a new worktree starts from and the
    core.hooksPath it sets (init.session_hooks_path), for a step to read once."""
    mains = gitutil.main_branches(cfg, cfg.repos())
    return {repo: (mains[repo], init.session_hooks_path(cfg.repo_path(repo)))
            for repo in cfg.repos()}


def _add_worktree(cfg, repo, name, worktree, base):
    """`git worktree add -b name`; SessionError EAGAIN if the branch exists (R134)."""
    try:
        gitutil.git(cfg.repo_path(repo), "worktree", "add", "-q", "-b", name, worktree, base)
    except gitutil.GitError as e:
        if "already exists" in str(e) and gitutil.branch_exists(cfg, repo, name):
            raise SessionError(EAGAIN, f"branch {name} exists in {repo}")
        raise


def create(cfg, role, username=None, setup=None):
    """Create a session for a role (R128-R131). Returns its record; raises
    SessionError with the codes of R132-R135. Callers creating several sessions
    share one setup dict; the first to need it fills it with repo_setup(cfg)."""
    setup = {} if setup is None else setup
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
                if not setup.keys() >= set(cfg.repos()):  # first call, or a repo added
                    setup.update(repo_setup(cfg))
                for repo in cfg.repos():
                    base, hooks = setup[repo]
                    worktree = os.path.join(directory, repo)
                    _add_worktree(cfg, repo, name, worktree, base)
                    created.append(repo)
                    if hooks:
                        gitutil.git(worktree, "config", "--worktree", "core.hooksPath", hooks)
                    faults.point(f"session:after-worktree:{repo}")
            except (gitutil.GitError, OSError) as e:
                raise SessionError(EGIT, str(e))
        except BaseException:
            _undo(cfg, name, directory, created)
            raise
        return session


def _undo(cfg, name, directory, repos):
    for repo in repos:
        gitutil.ok(cfg.repo_path(repo), "worktree", "remove", "--force",
                   os.path.join(directory, repo))
        gitutil.ok(cfg.repo_path(repo), "branch", "-D", name)
    shutil.rmtree(directory, ignore_errors=True)
    try:
        with msm.transaction(cfg.db) as m:
            m.session_remove(name)
    except msm.MSMError:
        pass


def protected_branches(m):
    """Branches of unresolved issues (R206)."""
    return {i["branch"] for i in m.list("issue")
            if i["status"] in msm.UNRESOLVED and i.get("branch")}


def remove(cfg, name, protected=()):
    """Remove a session's worktrees, unprotected branches, directory and record.
    An expired caller removes nothing (R87); usage is recorded first."""
    remove_all(cfg, [name], protected)


def remove_all(cfg, names, protected=()):
    """remove() for several sessions, with one `branch -D` and `worktree prune` per
    repo. Records go last, so a rerun after a crash finishes the job."""
    names = list(dict.fromkeys(names))
    if not names:
        return
    with msm.transaction(cfg.db) as m:
        m.check_caller()
        records = [m.one("SELECT * FROM sessions WHERE name = ?", n) for n in names]
    for session in records:
        if session is not None:
            usage.safe_record(cfg, dict(session))
    branches = [n for n in names if n not in protected]
    for repo in cfg.repos():
        path = cfg.repo_path(repo)
        if not os.path.isdir(path):
            continue
        for name in names:
            gitutil.ok(path, "worktree", "remove", "--force",
                       os.path.join(cfg.root, name, repo))
        if branches:  # deletes those that exist, even if some don't
            gitutil.ok(path, "branch", "-D", *branches)
        gitutil.ok(path, "worktree", "prune")
    for name in names:
        shutil.rmtree(os.path.join(cfg.root, name), ignore_errors=True)
    with msm.transaction(cfg.db) as m:
        for name in names:
            if m.one("SELECT 1 FROM sessions WHERE name = ?", name):
                m.session_remove(name)
