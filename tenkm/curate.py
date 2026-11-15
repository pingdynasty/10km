"""tenkm.curate: the Curator's scripted steps (R203-R259).

    curate-prepare                     Step 1 (R207)
    curate-select                      Step 2 (R210)
    curate-merge [ITEM...]             Step 3 (R216)
    curate-publish [--report TEXT | --report-file F] [--accepted S...] [--rejected S...]
                                       Step 9 (R249)
    curate-cleanup                     Step 10 (R254)

Every step runs as the Curator session in LOOP_SESSION (R205). State between steps
is kept in <session>/curation.json. Each step is safe to rerun.

Exit status: 0 done, 1 error, 2 refused (stop), 3 conflict (resolve, commit, rerun).
"""
import argparse
import json
import os
import subprocess
import sys

from . import config, faults, gitutil, msm, sessions

EXIT_ERROR, EXIT_REFUSED, EXIT_CONFLICT = 1, 2, 3
# Replay recorded conflict resolutions in the Curator's merges only.
RERERE = ("-c", "rerere.enabled=true", "-c", "rerere.autoUpdate=true")


class CurateError(Exception):
    def __init__(self, message, code=EXIT_ERROR):
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

    def repos(self):
        """The repos the Curator has a worktree in (not those added to central/ since)."""
        return [r for r in self.cfg.repos() if os.path.isdir(self.worktree(r))]

    def load(self):
        try:
            with open(self.state_path) as f:
                state = json.load(f)
        except (OSError, ValueError):
            state = {}
        state.setdefault("selection", None)
        state.setdefault("applied", [])   # item keys applied, in order
        state.setdefault("picked", [])    # commits created by cherry-picks
        state.setdefault("pending", None) # the item stopped at a conflict
        state.setdefault("own_to_replay", [])
        return state

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


def heads(cfg):
    """{repo: its branch names}, for a step to read once."""
    return {r: gitutil.branches(cfg, r) for r in cfg.repos()}


def branch_repos(cfg, name, known=None):
    """The repos in which a session has a branch, by known (heads()) or read now."""
    known = heads(cfg) if known is None else known
    return [r for r in cfg.repos() if name in known.get(r, ())]


def is_merged(path, name):
    return gitutil.ok(path, "merge-base", "--is-ancestor", name, "HEAD")


def mid_merge(path):
    return gitutil.ok(path, "rev-parse", "-q", "--verify", "MERGE_HEAD")


def dirty(path, untracked=False):
    flag = "--untracked-files=normal" if untracked else "--untracked-files=no"
    return bool(gitutil.git(path, "status", "--porcelain", flag))


def conflicts(path):
    out = gitutil.git(path, "diff", "--name-only", "--diff-filter=U", check=False)
    return [line for line in out.splitlines() if line]


def central_on_main(cfg, repo):
    central = cfg.repo_path(repo)
    branch = gitutil.main_branch(cfg, repo)
    rc, head, _ = gitutil.run(central, "symbolic-ref", "--short", "HEAD")
    if rc != 0 or head != branch:
        raise CurateError(f"central/{repo} is not on its main branch {branch}")
    return central


# --- Step 1: prepare --------------------------------------------------------
def prepare(cfg):
    """R208, R209."""
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
            removed.append(s["name"])
    sessions.remove_all(cfg, removed, protected)
    return {"removed": removed}


# --- Step 2: select ---------------------------------------------------------
def select(cfg):
    """R211-R214."""
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
    previous = {s["name"] for s in state["selection"] or []}
    if previous != {s["name"] for s in chosen}:
        state.update(applied=[], picked=[], pending=None)
    state["selection"] = chosen
    c.save(state)
    return chosen


# --- Step 3: merge ----------------------------------------------------------
MARKERS = ("<<<<<<< ", "=======", ">>>>>>> ")


class Item:
    """A session (merged in every repo it has a branch in) or a commit (cherry-picked
    in its repo)."""

    def __init__(self, kind, name, repo=None):
        self.kind, self.name, self.repo = kind, name, repo

    def key(self):
        return f"{self.kind}:{self.repo or ''}:{self.name}"

    def label(self):
        return self.name if self.kind == "session" else f"{self.repo}:{self.name[:12]}"


def resolve_items(cfg, words, known):
    """Turn session names, SHAs and repo:sha into Items; known: heads()."""
    items = []
    for word in words:
        if branch_repos(cfg, word, known):
            items.append(Item("session", word))
            continue
        repo, sep, sha = word.partition(":")
        candidates = [repo] if sep and repo in cfg.repos() else cfg.repos()
        sha = sha if sep and repo in cfg.repos() else word
        found = []
        for r in candidates:
            rc, full, _ = gitutil.run(cfg.repo_path(r), "rev-parse", "-q", "--verify",
                                      f"{sha}^{{commit}}")
            if rc == 0:
                found.append((r, full))
        if not found:
            raise CurateError(f"{word} is neither a session with a branch nor a commit")
        if len(found) > 1:
            raise CurateError(f"commit {word} is in {', '.join(r for r, _ in found)}; "
                              "say which with repo:sha")
        items.append(Item("commit", found[0][1], found[0][0]))
    return items


def merge(cfg, words):
    """R217-R223. A list that isn't an extension of the last one rebuilds."""
    c = Curation(cfg)
    selected = {s["name"] for s in c.load()["selection"] or []}
    known = heads(cfg)
    mains = gitutil.main_branches(cfg, c.repos())
    empty = [w for w in words if w in selected and not branch_repos(cfg, w, known)]
    words = [w for w in words if w not in empty]  # selected sessions with nothing to merge
    items = resolve_items(cfg, words, known)
    state = c.load()
    keys = [i.key() for i in items]
    pending = state.get("pending")
    dropped = []  # a dropped conflicting item may be merged in other repos already
    if pending:
        if pending["item"] not in keys and pending["kind"] != "own":
            dropped = [_pending_item(pending)]
        done = _finish_pending(c, state, pending, keys)
        if done is not None:
            return done
        state = c.load()
    applied = state.get("applied", [])
    if keys[:len(applied)] != applied or dropped or behind_main(c, mains):
        _rebuild(c, state, dropped, known, mains)
        state = c.load()
        applied = []
    report = {"applied": [], "no_branches": empty, "conflict": None}
    for item in items[len(applied):]:
        stop = _apply(cfg, c, state, item, words, known)
        if stop:
            report["conflict"] = stop
            return report
        state = c.load()
        state["applied"] = state.get("applied", []) + [item.key()]
        c.save(state)
        report["applied"].append(item.label())
    if state.get("own_to_replay"):
        for repo, sha in list(state["own_to_replay"]):
            stop = _cherry_pick(c, state, Item("own", sha, repo), words)
            if stop:
                report["conflict"] = stop
                return report
            state = c.load()
            state["own_to_replay"].remove([repo, sha])
            c.save(state)
    return report


def behind_main(c, mains):
    """True if main has moved past the Curator branch in some repo."""
    return any(not gitutil.ok(c.worktree(r), "merge-base", "--is-ancestor", mains[r], "HEAD")
               for r in c.repos())


def _repos_for(cfg, item, known):
    return branch_repos(cfg, item.name, known) if item.kind == "session" else [item.repo]


def _apply(cfg, c, state, item, words, known):
    if item.kind == "commit":
        return _cherry_pick(c, state, item, words)
    for repo in _repos_for(cfg, item, known):
        path = c.worktree(repo)
        if is_merged(path, item.name):
            continue
        before = gitutil.git(path, "rev-parse", "HEAD")
        rc, _, err = gitutil.run(path, *RERERE, "merge", "--no-ff", "--no-edit",
                                 "-m", f"Merge {item.name}", item.name)
        if rc == 0:
            continue
        if not mid_merge(path):
            raise CurateError(f"{repo}: merging {item.name} failed: {err}")
        if not conflicts(path):  # rerere replayed every resolution
            gitutil.git(path, "commit", "--no-edit")
            continue
        return _stop(c, state, item, repo, before, words)
    return None


def _cherry_pick(c, state, item, words):
    path = c.worktree(item.repo)
    before = gitutil.git(path, "rev-parse", "HEAD")
    rc, out, err = gitutil.run(path, *RERERE, "cherry-pick", "-x", item.name)
    own = item.kind == "own"  # replayed own commits stay "own", so later rebuilds keep them
    if rc == 0:
        if not own:
            _record_pick(c, state, gitutil.git(path, "rev-parse", "HEAD"))
        return None
    if picking(path) and not conflicts(path):
        if "empty" in (out + err).lower() \
                or not gitutil.git(path, "diff", "--cached", "--name-only"):
            gitutil.run(path, "cherry-pick", "--skip")  # already applied
            return None
        _continue(path)
        if not own:
            _record_pick(c, state, gitutil.git(path, "rev-parse", "HEAD"))
        return None
    if not picking(path):
        raise CurateError(f"{item.repo}: cherry-picking {item.name[:12]} failed: {err}")
    return _stop(c, state, item, item.repo, before, words)


def picking(path):
    return gitutil.ok(path, "rev-parse", "-q", "--verify", "CHERRY_PICK_HEAD")


def _continue(path):
    env = dict(os.environ, GIT_EDITOR="true")
    subprocess.run(["git", "-C", path, *RERERE, "cherry-pick", "--continue"], env=env,
                   capture_output=True)


def _record_pick(c, state, sha):
    state = c.load()
    state.setdefault("picked", []).append(sha)
    c.save(state)


def _stop(c, state, item, repo, before, words):
    state = c.load()
    state["pending"] = {"item": item.key(), "kind": item.kind, "name": item.name,
                        "repo": repo, "before": before}
    c.save(state)
    return _instructions(c, item, repo, words)


def _instructions(c, item, repo, words):
    path = c.worktree(repo)
    files = conflicts(path)
    what = "merging" if item.kind == "session" else "cherry-picking"
    finish = "git -C {p} commit --no-edit" if item.kind == "session" \
        else "git -C {p} cherry-pick --continue"
    abort = "merge --abort" if item.kind == "session" else "cherry-pick --abort"
    others = [w for w in words if w != item.name and not item.name.startswith(w)]
    text = (f"CONFLICT {what} {item.label()} in {repo} (worktree {path})\n"
            f"Conflicted files: {', '.join(files)}\n"
            "To resolve: edit those files to remove the conflict markers, then rerun\n"
            f"  curate-merge {' '.join(words)}\n"
            "(or finish it yourself with "
            f"git -C {path} add <files> and {finish.format(p=path)}, then rerun).\n"
            f"To leave {item.label()} out instead, rerun without it:\n"
            f"  curate-merge {' '.join(others)}")
    return {"item": item.label(), "repo": repo, "files": files, "instructions": text}


def _finish_pending(c, state, pending, keys):
    """Continue after a conflict. Returns a report to stop with, or None to go on."""
    path = c.worktree(pending["repo"])
    in_progress = mid_merge(path) or picking(path)
    item = _pending_item(pending)
    if pending["item"] not in keys and pending["kind"] != "own":
        if in_progress:  # the agent dropped the item: abandon its merge
            gitutil.ok(path, "merge", "--abort")
            gitutil.ok(path, "cherry-pick", "--abort")
        elif pending["kind"] == "commit" and \
                gitutil.git(path, "rev-parse", "HEAD") != pending["before"]:
            _record_pick(c, state, gitutil.git(path, "rev-parse", "HEAD"))  # not an own commit
            state = c.load()
        state["pending"] = None
        c.save(state)
        return None
    if in_progress:
        unresolved = [f for f in conflicts(path) if _has_markers(os.path.join(path, f))]
        if unresolved:
            words = [k.split(":", 2)[2] for k in keys]
            return {"applied": [], "no_branches": [],
                    "conflict": _instructions(c, item, pending["repo"], words)}
        for f in conflicts(path):
            gitutil.git(path, "add", "--", f)
        if mid_merge(path):
            gitutil.git(path, *RERERE, "commit", "--no-edit")
        else:
            _continue(path)
            if pending["kind"] == "commit":
                _record_pick(c, state, gitutil.git(path, "rev-parse", "HEAD"))
    elif pending["kind"] == "commit" and \
            gitutil.git(path, "rev-parse", "HEAD") != pending["before"]:
        _record_pick(c, state, gitutil.git(path, "rev-parse", "HEAD"))  # the agent finished it
    state = c.load()
    state["pending"] = None
    c.save(state)
    return None


def _pending_item(pending):
    return Item(pending["kind"], pending["name"],
                pending["repo"] if pending["kind"] != "session" else None)


def _has_markers(path):
    try:
        with open(path, errors="replace") as f:
            return any(line.startswith(MARKERS) or line.rstrip("\n") == "=======" for line in f)
    except OSError:
        return False


def own_commits(c, state, repo, items, known, main):
    """The Curator's own commits in a repo: not merges, not on main, not on an
    included session branch, and not cherry-picked by curate-merge."""
    path = c.worktree(repo)
    exclude = [main] + [
        i.name for i in items if i.kind == "session" and i.name in known.get(repo, ())]
    out = gitutil.git(path, "rev-list", "--reverse", "--no-merges", "HEAD",
                      *[f"^{e}" for e in exclude])
    picked = set(state.get("picked", []))
    return [sha for sha in out.splitlines() if sha and sha not in picked]


def _rebuild(c, state, dropped, known, mains):
    """Reset every repo to main, keeping the Curator's own commits for replay.
    Commits of the applied items and of the dropped ones are not own commits."""
    repos = c.repos()
    for repo in repos:
        path = c.worktree(repo)
        if not mid_merge(path) and not picking(path) and dirty(path):
            raise CurateError(f"your {repo} worktree has uncommitted changes, which a rebuild "
                              "would lose; commit or discard them, then rerun curate-merge")
    previous = list(dropped)
    for key in state.get("applied", []):
        kind, repo, name = key.split(":", 2)
        previous.append(Item(kind, name, repo or None))
    own = [[r, sha] for r in repos for sha in own_commits(c, state, r, previous, known, mains[r])]
    for repo in repos:
        path = c.worktree(repo)
        gitutil.ok(path, "merge", "--abort")
        gitutil.ok(path, "cherry-pick", "--abort")
        gitutil.git(path, "reset", "-q", "--hard", mains[repo])
    state = c.load()
    state.update(applied=[], picked=[], pending=None,
                 own_to_replay=state.get("own_to_replay", []) + own)
    c.save(state)


# --- Step 9: publish --------------------------------------------------------
def publish(cfg, report="", accepted=(), rejected=()):
    """R250-R253. Rerunning after a crash finishes the job."""
    c = Curation(cfg)
    state = c.load()
    selection = c.selection()
    order = [r for r in cfg.projects() if r in c.repos()] + ["loop"]
    warnings = []
    for repo in order:
        central_on_main(cfg, repo)
        if mid_merge(cfg.repo_path(repo)) or dirty(cfg.repo_path(repo)):
            raise CurateError(f"central/{repo} has uncommitted changes or a merge in progress")
        path = c.worktree(repo)
        if mid_merge(path) or picking(path):
            raise CurateError(f"your {repo} worktree has an unfinished merge or cherry-pick; "
                              "finish it (rerun curate-merge) or abort it first")
        if dirty(path):
            warnings.append(f"your {repo} worktree has uncommitted changes; they are not "
                            "published")
    closing = any(s["role"] == "planner" for s in selection)
    verdicts = _verdicts(cfg, selection, accepted, rejected) if closing else []
    for repo in order:
        central = cfg.repo_path(repo)
        if is_merged(central, c.name):
            continue  # already published
        if not gitutil.ok(central, "merge", "--ff-only", "-q", c.name):
            raise CurateError(f"{repo}: main has moved; rerun curate-merge, validate, "
                              "then publish")
        faults.point(f"publish:after-ff:{repo}")
    state = c.load()
    state["published"] = True
    c.save(state)
    result = {"published": order, "cycle": None, "warnings": warnings}
    if not closing:
        return result
    with msm.transaction(cfg.db) as m:
        cur = m.cycle_get()
        result["cycle"] = cur["id"]
        if cur["status"] == "closed":
            result["already_closed"] = True
            return result
        m.cycle_curate({"curator_session": c.name, "report": report, "tasks": verdicts})
    return result


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


# --- Step 10: cleanup -------------------------------------------------------
def cleanup(cfg):
    """R256. Reports removed branches with commits that never reached main."""
    c = Curation(cfg)
    selection = c.selection()
    warnings = []
    for repo in cfg.repos():
        if dirty(cfg.repo_path(repo)):
            warnings.append(f"central/{repo} has uncommitted changes")
    with msm.transaction(cfg.db) as m:
        protected = sessions.protected_branches(m)
    removed, unpublished = [], []
    known = heads(cfg)
    mains = gitutil.main_branches(cfg, cfg.repos())
    for s in selection:
        for repo in branch_repos(cfg, s["name"], known):
            count = gitutil.git(cfg.repo_path(repo), "rev-list", "--count",
                                f"{mains[repo]}..{s['name']}")
            if count != "0" and s["name"] not in protected:
                unpublished.append({"session": s["name"], "repo": repo, "commits": int(count)})
        removed.append(s["name"])
    sessions.remove_all(cfg, removed, protected)
    return {"removed": removed, "unpublished_removed": unpublished, "warnings": warnings}


# --- command line -----------------------------------------------------------
def main(step, argv):
    cfg = config.load()
    p = argparse.ArgumentParser(prog=f"curate-{step}")
    if step == "merge":
        p.add_argument("items", nargs="*", help="sessions and commits to include, in order")
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
            result = merge(cfg, args.items)
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
    except (msm.MSMError, sessions.SessionError) as e:
        print(json.dumps({"code": e.code, "error": e.message}), file=sys.stderr)
        return EXIT_REFUSED if e.code == msm.EPERM else EXIT_ERROR
    except gitutil.GitError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return EXIT_ERROR
    if isinstance(result, dict) and result.get("conflict"):
        print(result["conflict"]["instructions"])
        return EXIT_CONFLICT
    print(json.dumps(result, indent=1))
    return 0
