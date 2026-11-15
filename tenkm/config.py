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
STATE_PATHS = ("MSM_DB", "MSM_LOG")  # settings msm itself reads from the environment


class Config(dict):
    """Settings as a dict of strings, with typed accessors and derived paths."""

    @property
    def root(self):
        return self.get("LOOP_ROOT") or default_root()

    @property
    def central(self):
        return os.path.join(self.root, "central")

    @property
    def state_dir(self):
        """Per-loop runtime files (locks, notices): <root>/.10km."""
        return os.path.join(self.root, ".10km")

    @property
    def db(self):
        """The state database: MSM_DB, else <root>/.10km/loop.db."""
        return self.get("MSM_DB") or os.path.join(self.state_dir, "loop.db")

    @property
    def action_log(self):
        """The action log: MSM_LOG, else actions.log next to the database."""
        return self.get("MSM_LOG") or os.path.join(os.path.dirname(os.path.abspath(self.db)),
                                                   "actions.log")

    @property
    def usage_log(self):
        """The usage log, one JSON line per agent run: USAGE_LOG, else usage.jsonl
        next to the database."""
        return self.get("USAGE_LOG") or os.path.join(os.path.dirname(os.path.abspath(self.db)),
                                                     "usage.jsonl")

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
        """Project repo names: every git repo in central/ other than the loop repo.

        The central worktrees are the source of truth for which repos the loop has;
        each repo's own git config holds its settings (branch, author, remotes).
        """
        try:
            names = sorted(os.listdir(self.central))
        except OSError:
            return []
        return [n for n in names if n != "loop" and not n.startswith(".")
                and os.path.exists(os.path.join(self.central, n, ".git"))]

    def repos(self):
        """Every repo with a worktree per session: the loop repo, then the projects."""
        return ["loop"] + self.projects()

    def repo_path(self, repo):
        return os.path.join(self.central, repo)

    def timeout(self, role):
        """Session time-out in seconds: <ROLE>_TIMEOUT, else SESSION_TIMEOUT."""
        return self.int(f"{role.upper()}_TIMEOUT", self.int("SESSION_TIMEOUT", 3600))

    def agent_command(self, role):
        """The agent command for a role: <ROLE>_AGENT, else LOOP_AGENT. The operator's
        agent is interactive, so OPERATOR_AGENT doesn't fall back to LOOP_AGENT."""
        if role == "operator":
            return self.get("OPERATOR_AGENT") or "claude"
        return self.get(f"{role.upper()}_AGENT") or self.get("LOOP_AGENT", "")


def default_root():
    """The loop root: the parent of central/ when this code is the central loop
    worktree (run from a loop directory), else /loop."""
    parent = os.path.dirname(CODE_ROOT)
    if os.path.basename(parent) == "central":
        return os.path.dirname(parent)
    return "/loop"


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
    env.setdefault("LOOP_ROOT", default_root())
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
    # msm reads its paths from the environment: apply those set in config.env, so
    # msm calls in this process and its children use them too.
    for name in STATE_PATHS:
        if cfg.get(name):
            os.environ[name] = cfg[name]
    return cfg
