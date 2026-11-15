"""tenkm.status: a plain-text status report from the database and git."""
import os

from . import gitutil, msm


def report(cfg):
    lines = []
    with msm.transaction(cfg.db) as m:
        loop = m.loop_get()
        try:
            cycle = m.cycle_get()
        except msm.MSMError:
            cycle = None
        active = m.list("session", '{"status": "active"}')
        inactive = [s for s in m.list("session") if s["status"] != "active"]
        issues = m.list("issue", '{"status": "open"}')
        audits = m.list("audit")
    state_line = "stopped" + (f" ({loop['reason']})" if loop["reason"] else "") \
        if loop["stopped"] else "running"
    lines.append(f"Loop: {state_line}, phase {loop['phase']}, cycle {loop['current_cycle']}, "
                 f"{loop['empty_cycles']} empty cycles in a row")
    if cycle:
        lines.append(f"\nCycle {cycle['id']} ({cycle['status']}): {cycle['headline']}")
        for t in cycle["tasks"]:
            lines.append(f"  {t['status']:9} {t['shortname']}"
                         + (f"  [{t['session']}]" if t.get("session") else ""))
        if cycle.get("report"):
            lines.append(f"  Report: {cycle['report']}")
    lines.append(f"\nActive sessions: {len(active)}")
    for s in active:
        lines.append(f"  {s['name']}  since {s['created_at']}  {s.get('handle') or 'no handle'}")
    if inactive:
        lines.append(f"Waiting to be curated or removed: {len(inactive)}")
        for s in inactive:
            lines.append(f"  {s['name']} ({s['status']})")
    escalations = [i for i in issues if i["type"] == "escalation"]
    backlog = [i for i in issues if i["type"] == "backlog"]
    lines.append(f"\nOpen escalations: {len(escalations)}")
    for i in sorted(escalations, key=lambda i: i["severity"] != "blocking"):
        lines.append(f"  [{i['severity']}] {i['title']}  -> {i.get('assignee_role') or '?'}")
    lines.append(f"Open backlog items: {len(backlog)}")
    lines.append(f"Audits: {len(audits)}"
                 + (f", last {audits[-1]['created_at']}" if audits else ""))
    lines.append("\nMain:")
    for repo in cfg.repos():
        path = cfg.repo_path(repo)
        if os.path.isdir(path):
            head = gitutil.git(cfg, path, "log", "-1", "--format=%h %cI %s", check=False)
            lines.append(f"  {repo}: {head}")
    return "\n".join(lines)
