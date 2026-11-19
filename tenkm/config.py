"""tenkm.config: loop settings.

Settings come from `config.env` in the central loop worktree, sourced as shell, so
it can use `${NAME-default}` to let the environment override it. Before the central
worktree exists (during init), the config.env next to this code is used.

    from tenkm import config
    cfg = config.load()
    cfg.root, cfg.central, cfg.repos(), cfg.int("MAX_TASKS_PER_CYCLE", 0)
"""
import os
import subprocess

CODE_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
BIN = os.path.join(CODE_ROOT, "bin")
STATE_PATHS = ("MSM_DB", "MSM_LOG", "USAGE_LOG")  # relative to the loop root


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
        """Project repo names: every git repo in central/ other than the loop repo."""
        try:
            names = sorted(os.listdir(self.central))
        except OSError:
            return []
        return [n for n in names if n != "loop" and not n.startswith(".")
                and os.path.exists(os.path.join(self.central, n, ".git"))]

    @property
    def project_name(self):
        """PROJECT_NAME, else the first project repo, else the loop root's basename."""
        return (self.get("PROJECT_NAME") or (self.projects() or [None])[0]
                or os.path.basename(os.path.abspath(self.root)))

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


def _pairs(items):
    return dict(item.split("=", 1) for item in items if "=" in item)


def host_env_path(root):
    """This host's settings: <root>/host.env, outside the repos."""
    return os.path.join(root, "host.env")


def load(root=None):
    """Read host.env, then config.env, with the current environment applied, and
    return a Config. Settings are written X="${X-default}", so the environment
    overrides both, and host.env overrides config.env. What host.env sets is also
    exported, so agents, gates and every command they run inherit it."""
    env = dict(os.environ)
    if root:
        env["LOOP_ROOT"] = root
    env.setdefault("LOOP_ROOT", default_root())
    path = config_path(env["LOOP_ROOT"])
    host = host_env_path(env["LOOP_ROOT"])
    if os.path.exists(path) or os.path.exists(host):
        script = ('set -a; if [ -f "$2" ]; then . "$2" >&2 || exit $?; fi; printf "TENKM_HOST_ENV=1\\0"; env -0; printf "TENKM_HOST_ENV=0\\0"; '
                  'if [ -f "$1" ]; then . "$1" >&2 || exit $?; fi; set +a; '
                  'printf "TENKM_CONFIG_OK=1\\0"; env -0')
        out = subprocess.run(["bash", "-c", script, "config", path, host],
                             env=env, capture_output=True, check=False)
        items = out.stdout.decode().split("\0")
        if out.returncode == 0 and "TENKM_CONFIG_OK=1" in items:
            hosted = _pairs(items[items.index("TENKM_HOST_ENV=1") + 1:
                                  items.index("TENKM_HOST_ENV=0")])
            for k, v in hosted.items():
                if env.get(k) != v:
                    os.environ[k] = v
            env = _pairs(items[items.index("TENKM_CONFIG_OK=1") + 1:])
        else:
            # A broken config must not stop the loop; keep the environment and report.
            failed = "config.env" if "TENKM_HOST_ENV=0" in items else "host.env"
            env["TENKM_CONFIG_ERROR"] = (f"{failed} failed: " + out.stderr.decode().strip()
                                         ).rstrip(": ")
    cfg = Config(env)
    cfg["LOOP_CONFIG_PATH"] = path
    cfg["LOOP_HOST_ENV_PATH"] = host
    # Exported, so msm calls in this process and its children use the same files.
    for name in STATE_PATHS:
        if cfg.get(name):
            cfg[name] = os.path.join(os.path.abspath(cfg.root), cfg[name])
            os.environ[name] = cfg[name]
    return cfg
