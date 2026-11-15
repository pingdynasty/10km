"""tenkm.gitutil: small git helpers used by sessions and the Curator."""
import os
import subprocess


class GitError(Exception):
    pass


def git(cfg, repo_dir, *args, check=True):
    """Run git in repo_dir with the loop's commit identity. Returns stdout."""
    env = dict(os.environ, **cfg.git_env())
    p = subprocess.run(["git", "-C", repo_dir, *args], env=env, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise GitError(f"git {' '.join(args)} in {repo_dir}: {p.stderr.strip()}")
    return p.stdout.strip()


def ok(cfg, repo_dir, *args):
    """True if the git command succeeds."""
    env = dict(os.environ, **cfg.git_env())
    return subprocess.run(["git", "-C", repo_dir, *args], env=env,
                          capture_output=True).returncode == 0


def main_branch(cfg, repo):
    """The repo's default branch: MAIN_BRANCH, else the central worktree's branch."""
    if cfg.get("MAIN_BRANCH"):
        return cfg["MAIN_BRANCH"]
    return git(cfg, cfg.repo_path(repo), "symbolic-ref", "--short", "HEAD")


def branch_exists(cfg, repo, branch):
    return ok(cfg, cfg.repo_path(repo), "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")


def run(cfg, repo_dir, *args):
    """Run git; return (exit status, stdout, stderr) without raising."""
    env = dict(os.environ, **cfg.git_env())
    p = subprocess.run(["git", "-C", repo_dir, *args], env=env, capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()
