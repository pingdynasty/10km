"""tenkm.gitutil: small git helpers used by sessions and the Curator."""
import os
import subprocess


class GitError(Exception):
    pass


def git(repo_dir, *args, check=True):
    """Run git in repo_dir; return its stdout, stripped.

    Raises GitError if git fails and check is true."""
    env = dict(os.environ)
    p = subprocess.run(["git", "-C", repo_dir, *args], env=env, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise GitError(f"git {' '.join(args)} in {repo_dir}: {p.stderr.strip()}")
    return p.stdout.strip()


def ok(repo_dir, *args):
    """True if the git command succeeds."""
    env = dict(os.environ)
    return subprocess.run(["git", "-C", repo_dir, *args], env=env,
                          capture_output=True).returncode == 0


def main_branch(cfg, repo):
    """The repo's configured branch (git config tenkm.mainBranch), else the branch
    the central worktree has checked out, else "main"."""
    path = cfg.repo_path(repo)
    rc, out, _ = run(cfg, path, "config", "--get", "tenkm.mainBranch")
    if rc == 0 and out:
        return out
    rc, out, _ = run(cfg, path, "symbolic-ref", "--short", "HEAD")
    return out if rc == 0 and out else "main"


def branch_exists(cfg, repo, branch):
    return ok(cfg.repo_path(repo), "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")


def run(cfg, repo_dir, *args):
    """Run git; return (exit status, stdout, stderr) without raising."""
    env = dict(os.environ)
    p = subprocess.run(["git", "-C", repo_dir, *args], env=env, capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()
