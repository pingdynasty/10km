"""tenkm.usage: keep each agent run's harness usage after its session is removed.

One JSON object per finished agent run is appended to `Config.usage_log`
(USAGE_LOG, else usage.jsonl next to the database):

    session, role, cycle, recorded_at (UTC ISO), harness, and, when the harness
    reports them: harness_session_id, duration_ms, num_turns, input_tokens,
    output_tokens, cache_read_input_tokens, cache_creation_input_tokens,
    total_cost_usd

Figures the harness doesn't report are omitted, not zero. The figures come from
the harness's JSON result in the session's agent.log (Claude Code with
`--output-format json`); any other log still gets a record without figures.

A session is recorded once: `record` skips sessions already in the log, so it is
safe to call again after a crash. The Dispatcher records sessions whose agent has
exited, and removing a session records it first if it wasn't yet.
"""
import json
import os
import shlex
from datetime import datetime, timezone

from .locks import lock

TAIL_BYTES = 1 << 20  # the result is at the end of the log
USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens",
                "cache_creation_input_tokens")


def harness_name(command):
    """The harness of an agent command: the basename of its first word."""
    try:
        words = shlex.split(command or "")
    except ValueError:
        words = (command or "").split()
    return os.path.basename(words[0]) if words else ""


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def parse_result(text):
    """The harness figures in an agent log, as a dict (empty if there are none).

    Takes the last line (or the whole text) that is a JSON object with a
    "type": "result" field, as Claude Code prints with --output-format json.
    """
    candidates = [text] + text.splitlines()[::-1]
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate.startswith("{"):
            continue
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("type") == "result":
            return _figures(data)
    return {}


def _figures(data):
    out = {}
    if isinstance(data.get("session_id"), str):
        out["harness_session_id"] = data["session_id"]
    for key in ("duration_ms", "num_turns", "total_cost_usd"):
        if _number(data.get(key)):
            out[key] = data[key]
    usage = data.get("usage")
    if isinstance(usage, dict):
        for key in USAGE_FIELDS:
            if _number(usage.get(key)):
                out[key] = usage[key]
    return out


def read_log(path):
    """The tail of an agent log as text, or None if it can't be read."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - TAIL_BYTES))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return None


def recorded(cfg):
    """Names of the sessions already in the usage log."""
    names = set()
    try:
        with open(cfg.usage_log) as f:
            for line in f:
                try:
                    names.add(json.loads(line)["session"])
                except (ValueError, KeyError, TypeError):
                    continue
    except OSError:
        pass
    return names


def make_record(cfg, session, log_text, now=None):
    now = now or datetime.now(timezone.utc)
    rec = {"session": session["name"], "role": session.get("role"),
           "cycle": session.get("cycle"),
           "recorded_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
           "harness": harness_name(cfg.agent_command(session.get("role") or ""))}
    rec.update(parse_result(log_text or ""))
    return rec


def record(cfg, session, now=None):
    """Append a usage record for a session from its agent.log, once.

    Skips operator sessions and sessions whose agent never ran (no agent.log).
    Returns the record written, or None.
    """
    if session.get("role") == "operator":
        return None
    directory = session.get("working_directory") or os.path.join(cfg.root, session["name"])
    text = read_log(os.path.join(directory, "agent.log"))
    if text is None:
        return None
    with lock(cfg, "usage"):
        if session["name"] in recorded(cfg):
            return None
        rec = make_record(cfg, session, text, now)
        os.makedirs(os.path.dirname(os.path.abspath(cfg.usage_log)), exist_ok=True)
        with open(cfg.usage_log, "a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
    return rec


def safe_record(cfg, session, log=None):
    """`record`, but never raises: usage must not stop a pass or a removal."""
    try:
        return record(cfg, session)
    except Exception as e:  # a bad log or an unwritable file only loses a record
        if log:
            log(f"usage for {session.get('name')} not recorded: {e}")
        return None
