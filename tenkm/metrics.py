"""tenkm.metrics: sessions, times, commits and harness usage per cycle and role (R26, R267).

Sessions are removed at curation, so each session is pieced together from the
sessions table, task and cycle rows, the action log's session lines and
usage.jsonl (tenkm.usage); commits are counted by Loop-Session trailer on each
repo's main branch.

    data = metrics.collect(cfg, cycle=None)   # {"sessions", "summary", "notes"}
    print(metrics.text(data))
"""
import json
import os
from datetime import datetime, timedelta, timezone

from . import gitutil, msm, usage

ROLE_ORDER = {r: i for i, r in enumerate(("planner", "worker", "curator", "auditor", "operator"))}
TRAILER = "Loop-Session"


def parse_time(text):
    """A UTC datetime from an ISO 8601 string, or None."""
    if not isinstance(text, str) or not text:
        return None
    try:
        t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)


def fmt_time(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def read_jsonl(path):
    """The JSON objects in a JSON-lines file; a missing file or bad lines are skipped."""
    try:
        with open(path) as f:
            lines = f.readlines()
    except OSError:
        return []
    records = []
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def commits_by_session(cfg):
    """{session: {repo: count}} from the Loop-Session trailers on each repo's main branch."""
    found = {}
    for repo in cfg.repos():
        path = cfg.repo_path(repo)
        if not os.path.isdir(path):
            continue
        branch = gitutil.main_branch(cfg, repo)
        rc, out, _ = gitutil.run(cfg, path, "log", branch,
                                 f"--format=%x00%(trailers:key={TRAILER},valueonly)")
        if rc != 0:
            continue
        for chunk in out.split("\0"):
            # Trailers are agent-written: skip values that could carry terminal escapes.
            for name in {v.strip() for v in chunk.splitlines() if v.strip().isprintable()
                         and v.strip()}:
                repos = found.setdefault(name, {})
                repos[repo] = repos.get(repo, 0) + 1
    return found


SESSION_EVENTS = {"session create": 0, "session done": 1, "session expired": 1,
                  "session remove": 2}


def session_event(get, action, at):
    """Note a logged session create, done, expired or remove on its session."""
    slot = SESSION_EVENTS.get(action.get("command"))
    name = action.get("name")
    if slot is None or not at or not isinstance(name, str) or not name:
        return
    s = get(name)
    if not s.role and isinstance(action.get("role"), str):
        s.role = action["role"]
    if s.cycle is None and isinstance(action.get("cycle"), int):
        s.cycle = action["cycle"]
    s.logged[slot] = s.logged[slot] or at
    if slot == 1 and not s.logged_outcome:
        s.logged_outcome = action["command"].split()[1]


class _Session:
    def __init__(self, name):
        self.name = name
        self.role = None
        self.cycle = None
        self.status = None      # session status, if the row survives
        self.task = None        # (shortname, status) for Workers
        self.cycle_outcome = None  # "planned" or "curated" if a cycle row names it
        self.logged_outcome = None  # "done" or "expired" from the action log
        self.times = {}         # source -> [start, end]
        self.logged = [None, None, None]  # logged create, done or expired, remove
        self.usage = []
        self.commits = {}

    def span(self):
        """(start, end, source): the best surviving start and end."""
        create, ended, removed = self.logged
        times = dict(self.times, log=(create, ended or removed))
        for source in ("session", "task", "log", "usage"):
            start, end = times.get(source, (None, None))
            if start or end:
                return start, end, source
        return None, None, None

    def outcome(self):
        """The task status for a Worker, "planned" or "curated" for a session a cycle
        row names, else the session status; none of these change on removal."""
        if self.task:
            return self.task[1]
        return self.cycle_outcome or self.status or self.logged_outcome or "unknown"

    def usage_totals(self):
        totals = {}
        for record in self.usage:
            for field in usage.FIGURES:
                value = record.get(field)
                if usage.is_number(value):
                    totals[field] = totals.get(field, 0) + value
        if self.usage:
            totals["runs"] = len(self.usage)
        return totals


def collect(cfg, cycle=None):
    """Metrics for every session the database, action log, usage log or git know of,
    optionally only those of one cycle."""
    sessions = {}

    def get(name):
        if name not in sessions:
            sessions[name] = _Session(name)
        return sessions[name]

    with msm.transaction(cfg.db) as m:
        rows = m.list("session")
        tasks = m.list("task")
        cycles = m.list("cycle")
    for r in rows:
        s = get(r["name"])
        s.role, s.status = r["role"], r["status"]
        if r["cycle"] is not None:
            s.cycle = r["cycle"]
        s.times["session"] = [parse_time(r["created_at"]),
                              parse_time(r["updated_at"]) if r["status"] != "active" else None]
    for t in tasks:
        if not t.get("session"):
            continue
        s = get(t["session"])
        s.role, s.cycle = s.role or "worker", t["cycle"]
        s.task = (t["shortname"], t["status"])
        s.times["task"] = [parse_time(t.get("started_at")), parse_time(t.get("done_at"))]
    for c in cycles:
        if c.get("planner_session"):
            s = get(c["planner_session"])
            s.role, s.cycle = s.role or "planner", s.cycle if s.cycle is not None else c["id"]
            s.cycle_outcome = "planned"
        if c.get("curator_session"):
            s = get(c["curator_session"])
            s.role, s.cycle = s.role or "curator", s.cycle if s.cycle is not None else c["id"]
            s.cycle_outcome = "curated"
    runs = read_jsonl(cfg.usage_log)
    for record in runs:
        name = record.get("session")
        if not isinstance(name, str) or not name:
            continue
        s = get(name)
        s.role = s.role or record.get("role")
        if s.cycle is None and isinstance(record.get("cycle"), int):
            s.cycle = record["cycle"]
        s.usage.append(record)
        end = parse_time(record.get("recorded_at"))
        if end:
            ms = record.get("duration_ms")
            start = end - timedelta(milliseconds=ms) if usage.is_number(ms) else None
            span = s.times.setdefault("usage", [None, None])
            if start and (span[0] is None or start < span[0]):
                span[0] = start
            if span[1] is None or end > span[1]:
                span[1] = end
    for action in read_jsonl(cfg.action_log):
        session_event(get, action, parse_time(action.get("at")))
    for name, repos in commits_by_session(cfg).items():
        get(name).commits = repos

    # Sessions without a cycle (auditor, operator): the cycle last planned when they started.
    planned = sorted((parse_time(c["planned_at"]), c["id"]) for c in cycles if c.get("planned_at"))
    records = []
    for s in sessions.values():
        start, end, source = s.span()
        cyc = s.cycle
        if cyc is None and start:
            cyc = max((cid for at, cid in planned if at and at <= start), default=None)
        if cycle is not None and cyc != cycle:
            continue
        duration = (end - start).total_seconds() if start and end else None
        records.append({
            "session": s.name, "role": s.role or "unknown", "cycle": cyc,
            "task": s.task[0] if s.task else None, "outcome": s.outcome(),
            "start": fmt_time(start), "end": fmt_time(end), "duration_s": duration,
            "times_from": source, "commits": dict(sorted(s.commits.items())),
            "usage": s.usage_totals()})
    records.sort(key=lambda r: (r["cycle"] is None, r["cycle"] or 0,
                                ROLE_ORDER.get(r["role"], 9), r["start"] or "", r["session"]))
    return {"sessions": records, "summary": summarize(records),
            "notes": notes(records, cfg.usage_log, bool(runs))}


def summarize(records):
    """Totals per cycle and role."""
    groups = {}
    for r in records:
        g = groups.setdefault((r["cycle"], r["role"]), {
            "cycle": r["cycle"], "role": r["role"], "sessions": 0, "duration_s": 0,
            "untimed": 0, "commits": 0, "usage": {}})
        g["sessions"] += 1
        if r["duration_s"] is None:
            g["untimed"] += 1
        else:
            g["duration_s"] += r["duration_s"]
        g["commits"] += sum(r["commits"].values())
        for k, v in r["usage"].items():
            g["usage"][k] = g["usage"].get(k, 0) + v
    return [groups[k] for k in sorted(groups, key=lambda k: (
        k[0] is None, k[0] or 0, ROLE_ORDER.get(k[1], 9)))]


def notes(records, upath, have_usage):
    """What the figures can't tell, in plain words."""
    out = []
    if not have_usage:
        out.append(f"No usage records in {upath}: no harness time, turns, tokens or cost.")
    untimed = [r["session"] for r in records if r["duration_s"] is None]
    if untimed:
        out.append(f"No duration for: {', '.join(untimed)}.")
    return out


def _minutes(seconds):
    return "-" if seconds is None else f"{seconds / 60:.0f}m"


def _num(value, fmt="{:,}"):
    return "-" if value is None else fmt.format(value)


def text(data):
    """The metrics as readable text tables."""
    head = ("cycle", "role", "session", "task", "outcome", "start", "time", "from",
            "commits", "agent", "turns", "in tok", "out tok", "cost")
    rows = []
    for r in data["sessions"]:
        u = r["usage"]
        rows.append((_num(r["cycle"], "{}"), r["role"], r["session"], r["task"] or "",
                     r["outcome"], r["start"] or "-", _minutes(r["duration_s"]),
                     r["times_from"] or "-", str(sum(r["commits"].values())),
                     _minutes(u["duration_ms"] / 1000) if "duration_ms" in u else "-",
                     _num(u.get("num_turns")), _num(u.get("input_tokens")),
                     _num(u.get("output_tokens")), _num(u.get("total_cost_usd"), "${:.2f}")))
    lines = ["Sessions:"] + _table(head, rows)
    head = ("cycle", "role", "sessions", "time", "commits", "agent", "in tok", "out tok", "cost")
    rows = []
    for g in data["summary"]:
        u = g["usage"]
        time = _minutes(g["duration_s"]) + (f" ({g['untimed']} untimed)" if g["untimed"] else "")
        rows.append((_num(g["cycle"], "{}"), g["role"], str(g["sessions"]), time,
                     str(g["commits"]),
                     _minutes(u["duration_ms"] / 1000) if "duration_ms" in u else "-",
                     _num(u.get("input_tokens")), _num(u.get("output_tokens")),
                     _num(u.get("total_cost_usd"), "${:.2f}")))
    lines += ["", "By cycle and role:"] + _table(head, rows)
    if data["notes"]:
        lines += ["", "Notes:"] + [f"- {n}" for n in data["notes"]]
    return "\n".join(lines)


def _table(head, rows):
    widths = [max(len(str(x)) for x in col) for col in zip(head, *rows)]
    return ["  " + "  ".join(str(x).ljust(w) for x, w in zip(row, widths)).rstrip()
            for row in [head] + rows]
