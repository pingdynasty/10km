"""tenkm.dispatch: one Dispatcher pass (R136-R160).

It records the usage of agents that have exited, and notifies only fatal errors
(R300), after the pass and outside the dispatch lock.
"""
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config, launchers, msm, notify, sessions, usage
from .config import BIN, CODE_ROOT
from .locks import lock


def parse_time(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def log(message):
    print(f"{datetime.now().astimezone():%Y-%m-%d %H:%M:%S%z} {message}", flush=True)


ESC = re.compile(r"ESC(\d{1,9})\b")


class DatabaseUnreadable(Exception):
    """The database can't be read, or holds no loop record."""


def next_escalation(m):
    """The next free escalation shortname (ESCn), as agents number them."""
    numbers = [int(x.group(1)) for i in m.list("issue", '{"type": "escalation"}')
               for x in [ESC.match(i.get("title") or "")] if x]
    return f"ESC{max(numbers, default=0) + 1}"


class Pass:
    def __init__(self, cfg, now=None):
        self.cfg = cfg
        self.now = now or datetime.now(timezone.utc)
        self.launcher = launchers.get(cfg)
        self.notices = []
        self.setup = {}  # sessions.repo_setup, read by the pass's first launch

    def notice(self, title, body="", priority="default", key=None):
        self.notices.append((title, body, priority, key))

    # --- expiry ------------------------------------------------------------
    def expire_sessions(self):
        """R155-R159."""
        with msm.transaction(self.cfg.db) as m:
            active = m.list("session", '{"status": "active"}')
        for s in active:
            if s["role"] == "operator":
                continue
            age = (self.now - parse_time(s["created_at"])).total_seconds()
            handle = s.get("handle")
            launcher = launchers.for_handle(handle) if handle else None
            if age > self.cfg.timeout(s["role"]):
                stopped = launcher is not None and launcher.stop(self.cfg, handle)
                self.expire(s["name"], "timed out")
                if not stopped:
                    self.escalate_unstopped(s, handle)
            elif launcher is not None and age > self.cfg.int("START_GRACE", 180) \
                    and launcher.alive(self.cfg, handle) is False:
                self.expire(s["name"], "not running")

    def escalate_unstopped(self, s, handle):
        """R158."""
        with msm.transaction(self.cfg.db) as m:
            m.create("issue", {
                "type": "escalation",
                "title": f"{next_escalation(m)}: Agent may still be running: {s['name']}",
                "description": f"Session {s['name']} timed out and was expired, but its "
                               f"launcher could not confirm the agent stopped (handle "
                               f"{handle}). Stop it by hand if it is still running.",
                "assignee_role": "operator", "severity": "high"})
        log(f"escalated {s['name']}: agent may still be running")

    def expire(self, name, why):
        """Mark a session expired, unless it finished or was removed meanwhile."""
        with msm.transaction(self.cfg.db) as m:
            row = m.one("SELECT status FROM sessions WHERE name = ?", name)
            if row is None or row["status"] != "active":
                return
            m.session_status(name, "expired")
        log(f"expired {name} ({why})")

    # --- usage -------------------------------------------------------------
    def record_usage(self):
        """Record each finished session whose agent has exited, once. Never raises."""
        try:
            with msm.transaction(self.cfg.db) as m:
                done = [s for s in m.list("session")
                        if s["status"] != "active" and s["role"] != "operator"]
            seen = usage.recorded(self.cfg)
        except Exception as e:
            log(f"usage not recorded: {e}")
            return
        for s in done:
            if s["name"] in seen:
                continue
            handle = s.get("handle") or ""
            launcher = launchers.for_handle(handle) if handle else None
            try:
                if launcher is not None and launcher.alive(self.cfg, handle) is not False:
                    continue  # still writing its log, or can't tell: removal records it
            except Exception:
                continue
            usage.safe_record(self.cfg, s, log)

    # --- launching ---------------------------------------------------------
    def at_agent_limit(self):
        """R325: MAX_CONCURRENT_AGENTS of the Dispatcher's agents are active."""
        limit = self.cfg.int("MAX_CONCURRENT_AGENTS", 0)
        if limit <= 0:
            return False
        with msm.transaction(self.cfg.db) as m:
            active = m.one("SELECT COUNT(*) FROM sessions WHERE status = 'active' "
                           "AND role != 'operator'")[0]
        return active >= limit

    def launch(self, role):
        """R148-R151. Returns True if launched."""
        if self.at_agent_limit():
            return False
        session = None
        for _ in range(3):
            try:
                session = sessions.create(self.cfg, role, setup=self.setup)
                break
            except sessions.SessionError as e:
                if e.code == sessions.EAGAIN:
                    continue
                if e.code != msm.EPERM:
                    log(f"launch {role} failed: {e.code} {e.message}")
                return False
        if session is None:
            return False
        name, directory = session["name"], session["working_directory"]
        prompt_file = os.path.join(directory, "prompt.txt")
        try:
            with open(prompt_file, "w", encoding="utf-8") as f:
                f.write(self.prompt(role, session))
        except (OSError, ValueError) as e:
            log(f"launch {role} failed: prompt not written: {e}")
            sessions.remove(self.cfg, name)
            return False
        first_message = (f"You are the 10km {role} session {name}. Your worktrees are in "
                         f"{directory}. Read your instructions in {prompt_file} and follow them.")
        env = self.agent_env(name, prompt_file, first_message)
        # If this pass dies after launching but before recording the real handle,
        # the pending handle makes the time-out report the session, not expire it.
        with msm.transaction(self.cfg.db) as m:
            m.session_update(name, {"handle": f"pending:{os.getpid()}"})
        try:
            handle = self.launcher.launch(self.cfg, session, role, env,
                                          os.path.join(directory, "agent.log"))
        except Exception as e:  # a launcher failure must not stop the pass
            log(f"launch {role} failed: {e}")
            sessions.remove(self.cfg, name)
            return False
        with msm.transaction(self.cfg.db) as m:
            m.session_update(name, {"handle": handle})
        log(f"launched {name} ({handle})")
        return True

    def prompt(self, role, session):
        parts = [f"Session: {session['name']}\nWorktrees: {session['working_directory']}\n"
                 f"Repos: {', '.join(self.cfg.repos())}\n"]
        prompts = os.path.join(self.cfg.central, "loop", "prompts")
        for name in ("common.md", f"{role}.md"):
            path = os.path.join(prompts, name)
            if os.path.exists(path):
                with open(path, encoding="utf-8", errors="replace") as f:
                    parts.append(f.read())
        return "\n".join(parts)

    def agent_env(self, name, prompt_file, first_message):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("LOOP_SESSION", "TENKM_"))}
        loop_code = os.path.join(self.cfg.central, "loop")
        code = loop_code if os.path.isdir(os.path.join(loop_code, "tenkm")) else CODE_ROOT
        env.update(SESSION=name, LOOP_SESSION=name, PROMPT_FILE=prompt_file,
                   FIRST_MESSAGE=first_message, LOOP_ROOT=self.cfg.root, MSM_DB=self.cfg.db,
                   MAX_TASKS_PER_CYCLE=str(self.cfg.int("MAX_TASKS_PER_CYCLE", 0)),
                   MSM_LOG=self.cfg.action_log,
                   PATH=os.pathsep.join([os.path.join(code, "bin"), BIN, env.get("PATH", "")]),
                   PYTHONPATH=os.pathsep.join(p for p in (code, env.get("PYTHONPATH")) if p))
        return env

    # --- auditor -----------------------------------------------------------
    def auditor_due(self, m):
        """R145-R147."""
        closed = m.list("cycle", '{"status": "closed"}')
        if not closed:
            return False
        audits = m.list("audit")
        last = max((parse_time(a["created_at"]) for a in audits), default=None)
        since = [c for c in closed if c.get("curated_at")
                 and (last is None or parse_time(c["curated_at"]) > last)]
        limit = self.cfg.int("AUDIT_CYCLES_LIMIT", 0)
        if limit > 0 and len(since) >= limit:
            return True
        at = self.cfg.get("AUDIT_TIME", "")
        if at:
            trigger = self.daily_trigger(at, self.cfg.get("AUDIT_TIMEZONE") or "UTC")
            if trigger is not None and (last is None or last < trigger):
                return True
        return False

    def daily_trigger(self, at, zone):
        """Today's AUDIT_TIME in AUDIT_TIMEZONE, as a UTC datetime."""
        try:
            hour, minute = (int(x) for x in at.split(":"))
            tz = ZoneInfo(zone)
        except Exception:
            self.notice("Bad AUDIT_TIME or AUDIT_TIMEZONE", f"{at!r} {zone!r}", key="bad-audit-time")
            return None
        local = self.now.astimezone(tz)
        trigger = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if trigger > local:
            trigger = (local - timedelta(days=1)).replace(hour=hour, minute=minute,
                                                          second=0, microsecond=0)
        return trigger.astimezone(timezone.utc)

    # --- the pass ----------------------------------------------------------
    def check_database(self):
        """Raise DatabaseUnreadable unless the database opens and has a loop record."""
        try:
            with msm.transaction(self.cfg.db) as m:
                m.loop_get()
        except (sqlite3.DatabaseError, msm.MSMError) as e:
            raise DatabaseUnreadable(str(e)) from e

    def run(self):
        self.check_database()
        self.expire_sessions()
        self.record_usage()
        with msm.transaction(self.cfg.db) as m:
            loop = m.loop_get()
            auditor = not loop["stopped"] and self.auditor_due(m)
        if loop["stopped"]:
            return
        self.launch("curator")
        if loop["phase"] == "plan":
            self.launch("planner")
        elif loop["phase"] == "execute":
            while self.launch("worker"):
                pass
        if auditor:
            self.launch("auditor")

    def flush(self):
        for title, body, priority, key in self.notices:
            notify.send(self.cfg, title, body, priority, key)


def run_pass(cfg=None, now=None):
    """One Dispatcher pass. Returns an exit status."""
    os.environ.pop("LOOP_SESSION", None)  # the Dispatcher acts for the operator
    cfg = cfg or config.load()
    if cfg.get("TENKM_CONFIG_ERROR"):
        log(f"config error: {cfg['TENKM_CONFIG_ERROR']}")
    p = Pass(cfg, now)
    with lock(cfg, "dispatch", blocking=False) as locked:
        if not locked:
            return 0
        if not os.path.exists(cfg.db):
            if os.path.isdir(cfg.central):
                p.notice("Loop database missing", f"No database at {cfg.db}, but the loop "
                         f"exists at {cfg.root}. Check MSM_DB.", "critical", key="db-missing")
                p.flush()
            return 0
        notify.forget(cfg, "db-missing")
        try:
            p.run()
            notify.forget(cfg, "db-unreadable")
        except (sqlite3.DatabaseError, DatabaseUnreadable) as e:  # other MSMErrors raise
            p.notice("Loop database unreadable", f"{cfg.db}: {e}. The Dispatcher starts "
                     "nothing until it can read the database.", "critical", key="db-unreadable")
    p.flush()
    return 0


def main(argv=None):
    return run_pass()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
