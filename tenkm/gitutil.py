"""tenkm.gitutil: small git helpers used by sessions and the Curator."""
import subprocess


class GitError(Exception):
    pass


def run(repo_dir, *args):
    """Run git; return (exit status, stdout, stderr) without raising."""
    p = subprocess.run(["git", "-C", repo_dir, *args], capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def git(repo_dir, *args, check=True):
    """Run git in repo_dir; return its stdout. GitError if it fails and check is true."""
    rc, out, err = run(repo_dir, *args)
    if check and rc != 0:
        raise GitError(f"git {' '.join(args)} in {repo_dir}: {err}")
    return out


def ok(repo_dir, *args):
    """True if the git command succeeds."""
    return subprocess.run(["git", "-C", repo_dir, *args], capture_output=True).returncode == 0


def main_branch(cfg, repo):
    """The repo's configured branch (git config tenkm.mainBranch), else the branch
    the central worktree has checked out, else "main"."""
    path = cfg.repo_path(repo)
    rc, out, _ = run(path, "config", "--get", "tenkm.mainBranch")
    if rc == 0 and out:
        return out
    rc, out, _ = run(path, "symbolic-ref", "--short", "HEAD")
    return out if rc == 0 and out else "main"


def main_branches(cfg, repos):
    """{repo: main_branch}, for a step to read once."""
    return {repo: main_branch(cfg, repo) for repo in repos}


def branch_exists(cfg, repo, branch):
    return ok(cfg.repo_path(repo), "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")


def branches(cfg, repo):
    """The repo's local branch names, from one git call (empty if git fails)."""
    rc, out, _ = run(cfg.repo_path(repo), "for-each-ref", "--format=%(refname:lstrip=2)",
                     "refs/heads/")
    return set(out.splitlines()) if rc == 0 else set()
