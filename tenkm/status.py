"""tenkm.status: a plain-text status report from the database and git (R10)."""
import os

from . import gitutil, msm, timefmt
from .metrics import table


def _handle(handle):
    """A launcher handle, "pid N" for the process launcher's."""
    parts = (handle or "").split(":", 2)
    if len(parts) == 3 and parts[0] == "process" and parts[1].isdigit():
        return f"pid {parts[1]}"
    return handle or "no handle"


def _printable(text):
    """Text with "?" for each non-printable character but newlines (agent-written
    text must not reach the terminal as escapes)."""
    return "".join(c if c.isprintable() or c == "\n" else "?" for c in text)


def _loop_line(loop):
    state = "stopped" + (f" ({loop['reason']})" if loop["reason"] else "") \
        if loop["stopped"] else "running"
    line = f"Loop: {state}, phase {loop['phase']}, cycle {loop['current_cycle']}"
    n = loop["empty_cycles"]
    if n > 0:
        line += f", {n} empty cycle{'s' if n != 1 else ''} in a row"
    return line


def _repo_rows(cfg, now):
    """The Repository table: each repo's main branch and its latest commit."""
    rows = [("Repository", "Branch", "Commit", "When", "Message")]
    for repo in cfg.repos():
        path = cfg.repo_path(repo)
        if not os.path.isdir(path):
            continue
        branch = gitutil.main_branch(cfg, repo)
        rc, out, _ = gitutil.run(path, "log", "-1", "--format=%h%x00%cI%x00%s", branch, "--")
        parts = out.split("\x00", 2) if rc == 0 else []
        if len(parts) == 3:
            rows.append((repo, branch, parts[0], timefmt.ago(parts[1], now), parts[2]))
        else:
            rows.append((repo, branch, "-", "-", "(no commits)"))
    return rows


def report(cfg, now=None, tz=None):
    """The status report as text; `now` and `tz` (default: the local zone) fix the
    clock, for tests."""
    now = timefmt.parse(now) or timefmt.now()
    with msm.transaction(cfg.db) as m:
        loop = m.loop_get()
        try:
            cycle = m.cycle_get()
        except msm.MSMError:
            cycle = None
        active = m.list("session", '{"status": "active"}')
        inactive = [s for s in m.list("session") if s["status"] != "active"]
        issues = m.list("issue", '{"status": "open"}')
        answered = m.list("issue", '{"status": "answered"}')
        audits = m.list("audit")

    def when(t):
        return f"{timefmt.clock(t, now, tz)}, {timefmt.ago(t, now)}"

    lines = [f"{cfg.project_name} loop, {timefmt.stamp(now, tz)}", _loop_line(loop)]
    if cycle:
        lines.append(f"\nCycle {cycle['id']} ({cycle['status']}, planned "
                     f"{when(cycle.get('planned_at'))}):")
        if cycle.get("headline"):
            lines.append(f"  {cycle['headline']}")
        lines += table([(t["status"], t["shortname"], t.get("session") or "")
                         for t in cycle["tasks"]])
        if cycle.get("report"):
            lines.append(f"  Report: {cycle['report']}")
    lines.append(f"\nActive sessions: {len(active)}")
    lines += table([(s["name"], f"since {timefmt.clock(s['created_at'], now, tz)}",
                      timefmt.since(s["created_at"], now),
                      _handle(s.get("handle"))) for s in active])
    if inactive:
        lines.append(f"Waiting to be curated or removed: {len(inactive)}")
        lines += table([(s["name"], f"{s['status']} {timefmt.clock(s['updated_at'], now, tz)}",
                          timefmt.ago(s["updated_at"], now)) for s in inactive])
    escalations = [i for i in issues if i["type"] == "escalation"]
    backlog = [i for i in issues if i["type"] == "backlog"]
    lines.append(f"\nOpen escalations: {len(escalations)}")
    for i in sorted(escalations, key=lambda i: i["severity"] != "blocking"):
        lines.append(f"  [{i['severity']}] {i['title']}  -> {i.get('assignee_role') or '?'}"
                     f"  since {when(i['created_at'])}")
    lines.append(f"Open backlog items: {len(backlog)}")
    lines.append(f"Answered issues: {len(answered)}")
    for i in answered:
        lines.append(f"  [{i['type']}] {i['title']}  -> {i['assigner_role']}"
                     f"  answered {when(i.get('answered_at'))}")
    lines.append(f"Audits: {len(audits)}"
                 + (f", last {when(audits[-1]['created_at'])}" if audits else ""))
    lines.append("")
    lines += table(_repo_rows(cfg, now), indent="")
    return _printable("\n".join(lines))
