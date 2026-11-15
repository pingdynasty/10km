"""tenkm.curate: the Curator's deterministic steps.

    curate-prepare                     Step 1: remove leftover sessions
    curate-select                      Step 2: choose the sessions to curate
    curate-merge [--clean-only] S...   Step 3: merge sessions into the Curator branch
    curate-rebuild --without S...      Step 6: rebuild the branch without rejected work
    curate-publish [--report TEXT | --report-file F] [--accepted S...] [--rejected S...]
                                       Step 8: fast-forward main, close the cycle
    curate-cleanup                     Step 9: remove the curated sessions

Every step runs as the Curator session in LOOP_SESSION and refuses to run unless
that session is active. State between steps is kept in <session>/curation.json.
Each step is safe to rerun.
"""
import argparse
import json
import os
import sys

from . import config, faults, gitutil, msm, sessions

EXIT_CONFLICT = 1
EXIT_REFUSED = 2


class CurateError(Exception):
    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


# --- shared -----------------------------------------------------------------
class Curation:
    """The calling Curator session and its curation state."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.name = os.environ.get("LOOP_SESSION", "")
        with msm.transaction(cfg.db) as m:
            row = m.one("SELECT * FROM sessions WHERE name = ?", self.name) if self.name else None
        if row is None or row["role"] != "curator" or row["status"] != "active":
            raise CurateError(f"LOOP_SESSION {self.name or '(unset)'} is not an active Curator "
                              "session; stop. Don't retry or do this step by hand.", EXIT_REFUSED)
        self.dir = row["working_directory"]
        self.state_path = os.path.join(self.dir, "curation.json")

    def worktree(self, repo):
        return os.path.join(self.dir, repo)

    def load(self):
        try:
            with open(self.state_path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {"selection": None, "merged": [], "excluded": []}

    def save(self, data):
        tmp = self.state_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, self.state_path)

    def selection(self):
        sel = self.load()["selection"]
        if sel is None:
            raise CurateError("no selection; run curate-select first")
        return sel


def git(cfg, path, *args, check=True):
    return gitutil.git(cfg, path, *args, check=check)


def has_branch(cfg, repo, name):
    return gitutil.branch_exists(cfg, repo, name)


def is_merged(cfg, path, name):
    return gitutil.ok(cfg, path, "merge-base", "--is-ancestor", name, "HEAD")


def mid_merge(cfg, path):
    git_dir = git(cfg, path, "rev-parse", "--git-dir")
    if not os.path.isabs(git_dir):
        git_dir = os.path.join(path, git_dir)
    return os.path.exists(os.path.join(git_dir, "MERGE_HEAD"))


def conflicts(cfg, path):
    out = git(cfg, path, "diff", "--name-only", "--diff-filter=U", check=False)
    return [line for line in out.splitlines() if line]


def merges_cleanly(cfg, path, name):
    """True if merging name into HEAD would not conflict. Leaves the worktree alone."""
    rc, _, _ = gitutil.run(cfg, path, "merge-tree", "--write-tree", "--name-only", "HEAD", name)
    if rc in (0, 1):
        return rc == 0
    # git < 2.38 has no merge-tree --write-tree: probe with a real merge, then abort it.
    clean = gitutil.ok(cfg, path, "merge", "--no-commit", "--no-ff", name)
    gitutil.ok(cfg, path, "merge", "--abort")
    return clean


# --- Step 1: prepare --------------------------------------------------------
def prepare(cfg):
    c = Curation(cfg)
    with msm.transaction(cfg.db) as m:
        all_sessions = m.list("session")
        protected = sessions.protected_branches(m)
        try:
            cur = m.cycle_get()
        except msm.MSMError:
            cur = None
    removed = []
    for s in all_sessions:
        if s["name"] == c.name or s["status"] == "active":
            continue
        leftover = s["cycle"] is not None and s["role"] in ("planner", "worker") and (
            cur is None or s["cycle"] < cur["id"]
            or (s["cycle"] == cur["id"] and cur["status"] == "closed"))
        if s["role"] == "curator" or (s["role"] == "planner" and s["status"] == "expired") \
                or leftover:
            sessions.remove(cfg, s["name"], protected)
            removed.append(s["name"])
    for repo in cfg.repos():  # replay recorded conflict resolutions during rebuilds
        git(cfg, c.worktree(repo), "config", "rerere.enabled", "true")
        git(cfg, c.worktree(repo), "config", "rerere.autoUpdate", "true")
    return {"removed": removed}


# --- Step 2: select ---------------------------------------------------------
def select(cfg):
    c = Curation(cfg)
    with msm.transaction(cfg.db) as m:
        loop = m.loop_get()
        everything = m.list("session")
        try:
            cur = m.cycle_get()
        except msm.MSMError:
            cur = None
    inactive = [s for s in everything if s["status"] != "active"]
    chosen = [s for s in inactive if s["role"] in ("operator", "auditor")]
    if not chosen and loop["phase"] == "curate" and cur and cur["status"] == "open":
        chosen = [s for s in inactive if s["role"] in ("planner", "worker")
                  and s["cycle"] == cur["id"]]
    state = c.load()
    state.update(selection=chosen, merged=[], excluded=[])
    c.save(state)
    return chosen


# --- Step 3: merge ----------------------------------------------------------
def merge(cfg, names, clean_only=False):
    """Merge sessions, in order, into the Curator branch of every repo.

    Stops at the first conflict, leaving it in the worktree for the agent to
    resolve and commit; rerunning skips what is already merged. With clean_only,
    a session is merged only if it merges cleanly in every repo, else skipped.
    """
    c = Curation(cfg)
    state = c.load()
    report = {"merged": [], "skipped": [], "not_clean": [], "conflicts": []}
    for name in names:
        repos = [r for r in cfg.repos() if has_branch(cfg, r, name)]
        if not repos:
            raise CurateError(f"no branch {name} in any repo")
        pending = [r for r in repos if not is_merged(cfg, c.worktree(r), name)]
        if not pending:
            report["skipped"].append(name)
            _record_merged(c, state, name)
            continue
        if clean_only and not all(merges_cleanly(cfg, c.worktree(r), name) for r in pending):
            report["not_clean"].append(name)
            continue
        for repo in pending:
            path = c.worktree(repo)
            if mid_merge(cfg, path):
                raise CurateError(f"{repo}: a merge is in progress; resolve and commit it first")
            if not gitutil.ok(cfg, path, "merge", "--no-ff", "--no-edit",
                              "-m", f"Merge {name}", name):
                files = conflicts(cfg, path)
                if not files:  # rerere resolved everything
                    git(cfg, path, "commit", "--no-edit")
                    continue
                report["conflicts"] = [{"session": name, "repo": repo, "files": files}]
                return report
        _record_merged(c, state, name)
        report["merged"].append(name)
    return report


def _record_merged(c, state, name):
    if name not in state["merged"]:
        state["merged"].append(name)
        c.save(state)


# --- Step 6: rebuild --------------------------------------------------------
def rebuild(cfg, without):
    """Reset the Curator branch to main in every repo and re-merge the merged
    sessions except those in `without`. Recorded resolutions are replayed."""
    c = Curation(cfg)
    state = c.load()
    state["excluded"] = sorted(set(state.get("excluded", [])) | set(without))
    keep = [n for n in state["merged"] if n not in state["excluded"]]
    for repo in cfg.repos():
        path = c.worktree(repo)
        if mid_merge(cfg, path):
            git(cfg, path, "merge", "--abort", check=False)
        git(cfg, path, "reset", "-q", "--hard", gitutil.main_branch(cfg, repo))
    state["merged"] = []
    c.save(state)
    result = merge(cfg, keep)
    result["excluded"] = state["excluded"]
    return result


# --- Step 8: publish --------------------------------------------------------
def publish(cfg, report="", accepted=(), rejected=()):
    """Fast-forward main onto the Curator branch, project repos first, then the
    loop repo; then, if a Planner session was selected, close the cycle with the
    verdicts. Rerunning after a crash finishes the job."""
    c = Curation(cfg)
    selection = c.selection()
    closing = any(s["role"] == "planner" for s in selection)
    verdicts = _verdicts(cfg, selection, accepted, rejected) if closing else []
    order = [name for name, _ in cfg.projects()] + ["loop"]
    for repo in order:
        central = cfg.repo_path(repo)
        branch = gitutil.main_branch(cfg, repo)
        if git(cfg, central, "symbolic-ref", "--short", "HEAD") != branch:
            raise CurateError(f"central/{repo} is not on {branch}")
        if mid_merge(cfg, central) or git(cfg, central, "status", "--porcelain",
                                          "--untracked-files=no"):
            raise CurateError(f"central/{repo} has uncommitted changes or a merge in progress")
    for repo in order:
        central = cfg.repo_path(repo)
        if is_merged(cfg, central, c.name):
            continue  # already published
        if not gitutil.ok(cfg, central, "merge", "--ff-only", "-q", c.name):
            raise CurateError(f"{repo}: main has moved; rebuild on main and validate again")
        faults.point(f"publish:after-ff:{repo}")
    if not closing:
        return {"published": order, "cycle": None}
    with msm.transaction(cfg.db) as m:
        cur = m.cycle_get()
        if cur["status"] == "closed":
            return {"published": order, "cycle": cur["id"], "already_closed": True}
        m.cycle_curate({"curator_session": c.name, "report": report, "tasks": verdicts})
    return {"published": order, "cycle": cur["id"]}


def _verdicts(cfg, selection, accepted, rejected):
    workers = {s["name"] for s in selection if s["role"] == "worker"}
    unknown = (set(accepted) | set(rejected)) - workers
    if unknown:
        raise CurateError(f"not selected Worker sessions: {', '.join(sorted(unknown))}")
    both = set(accepted) & set(rejected)
    if both:
        raise CurateError(f"both accepted and rejected: {', '.join(sorted(both))}")
    out = []
    with msm.transaction(cfg.db) as m:
        for name in sorted(workers):
            task = m.task_for_session(name)
            if name in accepted or name in rejected:
                out.append({"id": task["id"],
                            "status": "accepted" if name in accepted else "rejected"})
            elif task["status"] == "done":
                raise CurateError(f"no verdict for done task of {name}")
    return out


# --- Step 9: cleanup --------------------------------------------------------
def cleanup(cfg):
    c = Curation(cfg)
    selection = c.selection()
    warnings = []
    for repo in cfg.repos():
        central = cfg.repo_path(repo)
        if git(cfg, central, "status", "--porcelain", "--untracked-files=no"):
            warnings.append(f"central/{repo} has uncommitted changes")
    with msm.transaction(cfg.db) as m:
        protected = sessions.protected_branches(m)
    removed = []
    for s in selection:
        sessions.remove(cfg, s["name"], protected)
        removed.append(s["name"])
    return {"removed": removed, "warnings": warnings}


# --- command line -----------------------------------------------------------
def main(step, argv):
    cfg = config.load()
    p = argparse.ArgumentParser(prog=f"curate-{step}")
    if step == "merge":
        p.add_argument("--clean-only", action="store_true")
        p.add_argument("sessions", nargs="+")
    elif step == "rebuild":
        p.add_argument("--without", nargs="+", required=True)
    elif step == "publish":
        p.add_argument("--report", default="")
        p.add_argument("--report-file")
        p.add_argument("--accepted", nargs="*", default=[])
        p.add_argument("--rejected", nargs="*", default=[])
    args = p.parse_args(argv)
    try:
        if step == "prepare":
            result = prepare(cfg)
        elif step == "select":
            result = select(cfg)
        elif step == "merge":
            result = merge(cfg, args.sessions, args.clean_only)
        elif step == "rebuild":
            result = rebuild(cfg, args.without)
        elif step == "publish":
            text = args.report
            if args.report_file:
                with open(args.report_file) as f:
                    text = f.read()
            result = publish(cfg, text, args.accepted, args.rejected)
        elif step == "cleanup":
            result = cleanup(cfg)
        else:
            raise CurateError(f"unknown step {step}")
    except CurateError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return e.code
    except msm.MSMError as e:
        print(json.dumps({"code": e.code, "error": e.message}), file=sys.stderr)
        return EXIT_REFUSED if e.code == msm.EPERM else 1
    print(json.dumps(result, indent=1))
    if isinstance(result, dict) and (result.get("conflicts")):
        return EXIT_CONFLICT
    return 0
