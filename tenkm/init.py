"""tenkm.init: prepare a loop directory.

    10km init      create the database if there is none, and register the
                   central repos: record each one's branch (tenkm.mainBranch)
                   and install the loop's git hooks, where not already set.

Hooks: init generates tenkm-hooks/ in each repo's git common dir. Each hook
there runs the loop's hook of that name (hooks/), then the one git would run
without the loop: in a core.hooksPath inherited from global or system config,
else in the repo's own hooks dir. Rerun init when the inherited dir changes.
Init sets no core.hooksPath in the central repos, so commits made there (for
example on the host, when central/ is mounted from it) run the host's own hooks.
It enables extensions.worktreeConfig instead, and each session worktree points
its own core.hooksPath at the generated dir (`git config --worktree`, set by
tenkm.sessions.create via session_hooks_path), so agent commits get the
Loop-Session trailer and then run the chained hooks. A repo whose local
core.hooksPath is set elsewhere keeps it, in every worktree; a local one that
points at the generated dir (left by an older init) is removed, and the existing
session worktrees get it per worktree instead. Needs git 2.26 (config
--show-scope; --worktree needs 2.20).

Kickoff (`10km kickoff`) calls this; run it again after adding a repo to central/.
The central worktrees are the source of truth for which repos the loop has: init
never clones or creates project repos. `create_loop_repo` makes a loop repo from a
copy of 10km, for the container's first start and for tests.
"""
import os
import shlex
import shutil
import subprocess

from . import gitutil, msm
from .config import CODE_ROOT


def create_loop_repo(dest, source=CODE_ROOT, branch="main"):
    """Create a loop repo at dest from a copy of the 10km code, with one commit.

    If source is the top of a git work tree, only its tracked files are copied, as
    they are in the working copy (uncommitted edits included, deleted files left
    out), so a loop root or other untracked files in the checkout stay out. Else
    (the container image's /opt/10km has no .git) the whole tree is copied, less
    .git, caches, databases and editor files."""
    tracked = _tracked_files(source)
    if tracked is None:
        shutil.copytree(source, dest, symlinks=True,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.db*", ".#*", "*~"))
    else:
        _copy_files(source, dest, tracked)
    env = dict(os.environ)
    env.setdefault("GIT_AUTHOR_NAME", "10km")
    env.setdefault("GIT_AUTHOR_EMAIL", "10km@localhost")
    env.setdefault("GIT_COMMITTER_NAME", env["GIT_AUTHOR_NAME"])
    env.setdefault("GIT_COMMITTER_EMAIL", env["GIT_AUTHOR_EMAIL"])
    for args in (["init", "-q", "-b", branch], ["add", "-A"], ["commit", "-q", "-m", "Loop repo"]):
        subprocess.run(["git", "-C", dest, *args], env=env, check=True, capture_output=True)


def _tracked_files(source):
    """The paths git tracks in source, relative to it, if source is the top of a git
    work tree; else None."""
    def git(*args):
        return subprocess.run(["git", "-C", source, *args], capture_output=True)
    top = git("rev-parse", "--show-toplevel")
    if top.returncode or not _same_dir(os.fsdecode(top.stdout.strip()), source):
        return None
    listed = git("ls-files", "-z", "--cached")
    if listed.returncode:
        return None
    return [os.fsdecode(p) for p in listed.stdout.split(b"\0") if p]


def _copy_files(source, dest, paths):
    """Copy paths (relative to source) to dest as they are in source: symlinks as
    symlinks, modes kept. Paths missing from source (deleted, not yet committed)
    are skipped."""
    os.makedirs(dest)
    for rel in paths:
        src, dst = os.path.join(source, rel), os.path.join(dest, rel)
        if not os.path.lexists(src):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isdir(src) and not os.path.islink(src):  # a submodule
            shutil.copytree(src, dst, symlinks=True, ignore=shutil.ignore_patterns(".git"))
        else:
            shutil.copy2(src, dst, follow_symlinks=False)


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
        if not gitutil.ok(path, "config", "--get", "tenkm.mainBranch"):
            gitutil.git(path, "config", "tenkm.mainBranch",
                        gitutil.git(path, "symbolic-ref", "--short", "HEAD"))
        install_hooks(path, hooks)
        report[repo] = gitutil.main_branch(cfg, repo)
    return report


def _executables(d):
    """The names of the executable files in dir d; hook names have no dot (*.sample)."""
    if not d or not os.path.isdir(d):
        return set()
    return {n for n in os.listdir(d) if "." not in n
            and os.path.isfile(os.path.join(d, n)) and os.access(os.path.join(d, n), os.X_OK)}


def _hook_script(own, inherited):
    """A hook that runs own, if given, then inherited, if given and still there."""
    lines = ["#!/bin/sh", "# Generated by 10km init; rerun init to update."]
    if own:
        lines.append(f'{shlex.quote(own)} "$@" || exit')
    if inherited:
        q = shlex.quote(inherited)
        lines += [f"[ -x {q} ] || exit 0", f'exec {q} "$@"']
    return "\n".join(lines) + "\n"


def write_hooks(gen, hooks, inherited):
    """Make gen hold a wrapper for each hook in hooks or inherited, and nothing else.
    Files are replaced atomically, so a crash leaves working hooks."""
    own, chained = _executables(hooks), _executables(inherited)
    names = own | chained
    os.makedirs(gen, exist_ok=True)
    for name in sorted(names):
        tmp = os.path.join(gen, f".{name}.tmp")
        with open(tmp, "w") as f:
            f.write(_hook_script(os.path.join(hooks, name) if name in own else None,
                                 os.path.join(inherited, name) if name in chained else None))
        os.chmod(tmp, 0o755)
        os.replace(tmp, os.path.join(gen, name))
    for name in set(os.listdir(gen)) - names:
        os.remove(os.path.join(gen, name))


def install_hooks(path, hooks):
    """Generate the repo's hooks dir and enable per-worktree config, unless its
    local core.hooksPath is set elsewhere. Remove a local core.hooksPath that points
    at the generated dir, moving it to each existing linked worktree. Reads config
    with --show-scope (git 2.26+)."""
    rc, out, err = gitutil.run(path, "config", "--show-scope", "--type=path", "--get-all",
                               "core.hooksPath")
    if rc not in (0, 1):  # 1: not set
        raise msm.MSMError(msm.EINVAL, f"10km init needs git 2.26 or later: {err}")
    values = dict(line.split("\t", 1) for line in out.splitlines() if "\t" in line)
    common = gitutil.git(path, "rev-parse", "--git-common-dir")
    gen = generated_dir(path)
    local = values.get("local", "")
    if local and not _same_dir(local, gen):
        return
    # Chain what git would run without us: the global or system hooksPath (relative
    # to the worktree, as git resolves it), else the repo's own hooks dir.
    inherited = values.get("global") or values.get("system") or os.path.join(common, "hooks")
    inherited = os.path.join(path, inherited)
    if _same_dir(inherited, gen):
        inherited = ""
    write_hooks(gen, hooks, inherited)
    gitutil.git(path, "config", "--local", "extensions.worktreeConfig", "true")
    if local:  # an older init's setting, which applies to every worktree
        for worktree in _linked_worktrees(path):
            gitutil.git(worktree, "config", "--worktree", "core.hooksPath", gen)
        gitutil.git(path, "config", "--local", "--unset-all", "core.hooksPath")


def generated_dir(path):
    """The generated hooks dir of the repo at path: tenkm-hooks/ in its common dir."""
    common = gitutil.git(path, "rev-parse", "--git-common-dir")
    return os.path.abspath(os.path.join(path, common, "tenkm-hooks"))


def session_hooks_path(path):
    """The core.hooksPath a new worktree of the central repo at path should set with
    `git config --worktree`: its generated hooks dir, once init has made it and
    enabled extensions.worktreeConfig. None if init hasn't, or if the repo's local
    core.hooksPath is the user's own (it applies to every worktree)."""
    gen = generated_dir(path)
    local = gitutil.git(path, "config", "--local", "--type=path", "--get", "core.hooksPath",
                        check=False)
    if local and not _same_dir(local, gen):
        return None
    enabled = gitutil.git(path, "config", "--local", "--type=bool", "--get",
                          "extensions.worktreeConfig", check=False)
    return gen if enabled == "true" and os.path.isdir(gen) else None


def _linked_worktrees(path):
    """The existing linked worktrees of the repo at path (not the main one)."""
    out = gitutil.git(path, "worktree", "list", "--porcelain")
    paths = [line[len("worktree "):] for line in out.splitlines()
             if line.startswith("worktree ")]
    return [p for p in paths[1:] if os.path.isdir(p)]


def _same_dir(a, b):
    return os.path.realpath(a) == os.path.realpath(b)
