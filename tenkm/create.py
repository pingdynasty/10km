"""tenkm.create: a new loop root from the 10km checkout it runs from (R339-R341).

    10km create <dir> [--agent NAME] [--branch NAME]

It clones the checkout into <dir>/central/loop, on a branch of the loop's own
(default: <dir>'s name), so main keeps following the source and updates can be
merged from it. In the clone, `local` is the checkout and `origin` the
checkout's origin, both fetched from and never pushed to. It writes <dir>/host.env,
with a preset's agent commands if --agent names one and the lines that let an
operator's shell source it to get LOOP_ROOT and the loop's commands (R343), and
runs init: `10km status` works at once, and kickoff comes next.
"""
import os
import subprocess
import sys

from . import config, init, presets
from .config import CODE_ROOT

STATE_SETTINGS = ("MSM_DB", "MSM_LOG", "USAGE_LOG", "LOOP_CONFIG")


class CreateError(Exception):
    pass


def _git(cwd, *args, check=True):
    p = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True)
    if check and p.returncode:
        raise CreateError(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout.strip() if p.returncode == 0 else None


def _same(a, b):
    return os.path.realpath(a) == os.path.realpath(b)


def host_env_text(dest, agent):
    lines = [f"# This host's settings for the loop in {dest}: read before",
             "# central/loop/config.env by every 10km command, run-loop and agent, and",
             "# exported to agents and gates. It is in no repo, and agents don't change it.",
             '# Write settings as X="${X-value}", so the environment can override them.',
             "# Don't put keys here: agents can read this file.",
             "#",
             '# PATH="$HOME/tools/bin:$PATH"',
             "",
             "# For your shell: `. ./host.env` sets LOOP_ROOT and puts this loop's 10km and",
             "# msm on PATH. 10km reads this file with LOOP_ROOT already set. Don't unset",
             "# LOOP_SESSION here: agents' sessions read this file too.",
             'LOOP_ROOT="${LOOP_ROOT-$(cd "$(dirname "${BASH_SOURCE[0]:-${(%):-%x}}")" && pwd)}"',
             'case ":$PATH:" in',
             '  *":$LOOP_ROOT/central/loop/bin:"*) ;;',
             '  *) PATH="$LOOP_ROOT/central/loop/bin:$PATH" ;;',
             "esac",
             "export LOOP_ROOT PATH",
             ""]
    if agent:
        lines += presets.host_env_lines(agent)
    else:
        lines.append(f"# Agent commands: none set; presets for {', '.join(presets.PRESETS)} "
                     "are in tenkm/presets.py.")
    return "\n".join(lines) + "\n"


def run(dest, agent=None, branch=None, source=CODE_ROOT, out=print):
    """Create the loop root at dest. Returns its central loop path."""
    dest = os.path.abspath(dest)
    loop = os.path.join(dest, "central", "loop")
    if agent and agent not in presets.PRESETS:
        raise CreateError(f"no preset {agent!r}; presets: {', '.join(presets.PRESETS)}")
    if os.path.lexists(loop):
        raise CreateError(f"{loop} already exists")
    top = _git(source, "rev-parse", "--show-toplevel", check=False)
    if not top or not _same(top, source):
        raise CreateError(f"{source} is not a git checkout: 10km create clones it")
    branch = branch or os.path.basename(dest)
    if branch == "main" or _git(source, "check-ref-format", "--branch", branch,
                                check=False) is None:
        raise CreateError(f"{branch!r} can't be the loop's branch: give --branch NAME "
                          "(not main, which follows the source)")
    if _git(source, "status", "--porcelain"):
        out(f"warning: {source} has uncommitted changes; only committed work is cloned")
    origin = _git(source, "remote", "get-url", "origin", check=False)
    if _git(source, "rev-parse", "--is-shallow-repository") == "true":
        out(f"warning: {source} is shallow: updates must come from origin, after "
            "`git fetch --unshallow origin` in the loop repo")

    os.makedirs(os.path.dirname(loop), exist_ok=True)
    _git(dest, "clone", "-q", "--origin", "local", source, loop)
    _git(loop, "remote", "set-url", "--push", "local", "no-push")
    if origin:
        _git(loop, "remote", "add", "origin", origin)
        _git(loop, "remote", "set-url", "--push", "origin", "no-push")
    _git(loop, "switch", "-q", "-c", branch)

    host = config.host_env_path(dest)
    if os.path.exists(host):
        out(f"{host} exists: left as it is")
    else:
        with open(host, "w", encoding="utf-8") as f:
            f.write(host_env_text(dest, agent))
    for name in STATE_SETTINGS:  # another loop's database must not be initialised
        os.environ.pop(name, None)
    init.run(config.load(dest))

    out(f"Created the loop in {dest}, branch {branch} of {loop}")
    out(f"  local:  {source} (fetch only)"
        + (f"\n  origin: {origin} (fetch only)" if origin else ""))
    if not agent:
        out(f"  no agent commands yet: set them in {host}")
    out(f"Next:\n  . {host}\n  10km kickoff")
    return loop


def main(argv):
    args, opts, i = [], {}, 0
    while i < len(argv):
        if argv[i] in ("--agent", "--branch") and i + 1 < len(argv):
            opts[argv[i][2:]] = argv[i + 1]
            i += 2
        elif argv[i].startswith("-"):
            args = []
            break
        else:
            args.append(argv[i])
            i += 1
    if len(args) != 1:
        print("usage: 10km create <dir> [--agent NAME] [--branch NAME]", file=sys.stderr)
        return 1
    try:
        run(args[0], **opts)
    except CreateError as e:
        print(f"10km create: {e}", file=sys.stderr)
        return 1
    return 0
