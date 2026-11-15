"""tenkm.init: prepare a loop directory.

    10km init      create the database if there is none, and register the
                   central repos: record each one's branch (tenkm.mainBranch)
                   and install the loop's git hooks, where not already set.

Hooks: init generates tenkm-hooks/ in each repo's git common dir. Each hook
there runs the loop's hook of that name (hooks/), then the one git would run
without the loop: in a core.hooksPath inherited from global or system config,
else in the repo's own hooks dir. Rerun init when the inherited dir changes.
Init sets no core.hooksPath in the central repos, so commits made there run the
host's own hooks; it enables extensions.worktreeConfig, and each session worktree
sets its own core.hooksPath to the generated dir (session_hooks_path). A repo
with a local core.hooksPath keeps it, in every worktree. Needs git 2.26.

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

    From a git checkout, copy only the tracked files as they are in the working
    copy; else (the container's /opt/10km) the whole tree, less .git, caches,
    databases and editor files."""
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
    """The paths git tracks in source if it is the top of a git work tree, else None."""
    def git(*args):
        return subprocess.run(["git", "-C", source, *args], capture_output=True)
    top = git("rev-parse", "--show-toplevel")
    if top.returncode or not _same_dir(os.fsdecode(top.stdout.strip()), source):
        return None
    listed = git("ls-files", "-z")
    if listed.returncode:
        return None
    return [os.fsdecode(p) for p in listed.stdout.split(b"\0") if p]


def _copy_files(source, dest, paths):
    """Copy paths (relative to source) to dest, keeping symlinks and modes and
    skipping those deleted from the working copy."""
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
    """Generate the repo's hooks dir and enable per-worktree config, unless the repo
    has a local core.hooksPath. Reads config with --show-scope (git 2.26+)."""
    rc, out, err = gitutil.run(path, "config", "--show-scope", "--type=path", "--get-all",
                               "core.hooksPath")
    if rc not in (0, 1):  # 1: not set
        raise msm.MSMError(msm.EINVAL, f"10km init needs git 2.26 or later: {err}")
    values = dict(line.split("\t", 1) for line in out.splitlines() if "\t" in line)
    if values.get("local"):
        return
    gen = generated_dir(path)
    # Chain what git would run without us: the global or system hooksPath (relative
    # to the worktree, as git resolves it), else the repo's own hooks dir.
    inherited = (values.get("global") or values.get("system")
                 or os.path.join(os.path.dirname(gen), "hooks"))
    inherited = os.path.join(path, inherited)
    if _same_dir(inherited, gen):
        inherited = ""
    write_hooks(gen, hooks, inherited)
    gitutil.git(path, "config", "--local", "extensions.worktreeConfig", "true")


def generated_dir(path):
    """The generated hooks dir of the repo at path: tenkm-hooks/ in its common dir."""
    common = gitutil.git(path, "rev-parse", "--git-common-dir")
    return os.path.abspath(os.path.join(path, common, "tenkm-hooks"))


def session_hooks_path(path):
    """The core.hooksPath for `git config --worktree` in a new session worktree of
    the central repo at path: its generated hooks dir, or None if init hasn't set
    the repo up for it or the repo has a local core.hooksPath."""
    if gitutil.ok(path, "config", "--local", "--get", "core.hooksPath"):
        return None
    enabled = gitutil.git(path, "config", "--local", "--type=bool", "--get",
                          "extensions.worktreeConfig", check=False)
    gen = generated_dir(path)
    return gen if enabled == "true" and os.path.isdir(gen) else None


def _same_dir(a, b):
    return os.path.realpath(a) == os.path.realpath(b)
