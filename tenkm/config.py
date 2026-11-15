"""tenkm.config: loop settings.

Settings come from `config.env` in the central loop worktree, sourced as shell, so
it can use `${NAME-default}` to let the environment override it. Before the central
worktree exists (during init), the config.env next to this code is used.

    from tenkm import config
    cfg = config.load()
    cfg.root, cfg.central, cfg.repos(), cfg.int("MAX_WORKERS", 4)
"""
import os
import subprocess

CODE_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
BIN = os.path.join(CODE_ROOT, "bin")


class Config(dict):
    """Settings as a dict of strings, with typed accessors and derived paths."""

    @property
    def root(self):
        return self.get("LOOP_ROOT") or "/loop"

    @property
    def central(self):
        return os.path.join(self.root, "central")

    @property
    def state_dir(self):
        """Per-loop runtime files (locks, notices): <root>/.10km."""
        return os.path.join(self.root, ".10km")

    @property
    def db(self):
        return self.get("MSM_DB") or os.path.join(self.state_dir, "loop.db")

    def int(self, name, default):
        value = self.get(name, "")
        try:
            return int(value) if value != "" else default
        except ValueError:
            return default

    def lines(self, name):
        """A setting holding one item per line, without blanks."""
        return [line.strip() for line in self.get(name, "").splitlines() if line.strip()]

    def projects(self):
        """Project repos as (name, url-or-None) from PROJECT_REPOS."""
        out = []
        for spec in self.get("PROJECT_REPOS", "").split():
            name, _, url = spec.partition("=")
            out.append((name, url or None))
        return out

    def repos(self):
        """Every repo with a worktree per session: the loop repo, then the projects."""
        return ["loop"] + [name for name, _ in self.projects()]

    def repo_path(self, repo):
        return os.path.join(self.central, repo)

    def timeout(self, role):
        """Session time-out in seconds: <ROLE>_TIMEOUT, else SESSION_TIMEOUT."""
        return self.int(f"{role.upper()}_TIMEOUT", self.int("SESSION_TIMEOUT", 3600))

    def agent_command(self, role):
        """The process launcher's command for a role: <ROLE>_AGENT, else LOOP_AGENT."""
        return self.get(f"{role.upper()}_AGENT") or self.get("LOOP_AGENT", "")

    def git_env(self):
        """Environment for git commits with the configured identity."""
        env = {}
        if self.get("GIT_NAME"):
            env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = self["GIT_NAME"]
        if self.get("GIT_EMAIL"):
            env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = self["GIT_EMAIL"]
        return env


def config_path(root):
    path = os.environ.get("LOOP_CONFIG") or os.path.join(root, "central", "loop", "config.env")
    if not os.path.exists(path):
        path = os.path.join(CODE_ROOT, "config.env")
    return path


def load(root=None):
    """Read config.env with the current environment applied, and return a Config."""
    env = dict(os.environ)
    if root:
        env["LOOP_ROOT"] = root
    env.setdefault("LOOP_ROOT", "/loop")
    path = config_path(env["LOOP_ROOT"])
    if os.path.exists(path):
        script = 'set -a; . "$1" >&2 || exit $?; set +a; printf "TENKM_CONFIG_OK=1\\0"; env -0'
        out = subprocess.run(["bash", "-c", script, "config", path],
                             env=env, capture_output=True, check=False)
        loaded = dict(item.split("=", 1) for item in out.stdout.decode().split("\0") if "=" in item)
        if out.returncode == 0 and loaded.pop("TENKM_CONFIG_OK", None) == "1":
            env = loaded
        else:
            # A broken config must not stop the loop; keep the environment and report.
            env["TENKM_CONFIG_ERROR"] = out.stderr.decode().strip() or "config.env failed"
    cfg = Config(env)
    cfg["LOOP_CONFIG_PATH"] = path
    return cfg
