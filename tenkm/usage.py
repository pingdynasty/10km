"""tenkm.usage: each agent run's harness usage, kept in Config.usage_log (R26, R267).

One JSON object per finished agent run: session, role, cycle, recorded_at (UTC),
harness, harness_session_id and the FIGURES the harness reports (omitted, not
zero, when it doesn't). The figures come from the end of agent.log, read by the
harness's parser (PARSERS, by harness_name): Claude Code's JSON result with
`--output-format json`, or kiro-cli's events with `--output-format stream-json`
(credits and time, no tokens). Other harnesses get the Claude parser. A session
is recorded once.
"""
import json
import math
import os
import stat
import shlex
from datetime import datetime, timezone

from .locks import lock

TAIL_BYTES = 1 << 20  # the result is at the end of the log
RESULT = ("duration_ms", "num_turns", "total_cost_usd")  # top-level in the result
TOKENS = ("input_tokens", "output_tokens", "cache_read_input_tokens",
          "cache_creation_input_tokens")
FIGURES = RESULT + TOKENS + ("credits",)


def harness_name(command):
    """The harness of an agent command: the basename of its first word."""
    try:
        words = shlex.split(command or "")
    except ValueError:
        words = (command or "").split()
    return os.path.basename(words[0]) if words else ""


def is_number(value):
    """A finite JSON number of sane size (agent logs are untrusted)."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and abs(value) < 1e12)


def parse_result(text):
    """The figures in the last JSON line (or whole text) with "type": "result", or {}."""
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
    for key in RESULT:
        if is_number(data.get(key)):
            out[key] = data[key]
    usage = data.get("usage")
    if isinstance(usage, dict):
        for key in TOKENS:
            if is_number(usage.get(key)):
                out[key] = usage[key]
    return out


def _json_lines(text):
    """The JSON objects among a log's lines; other lines are skipped."""
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict):
            yield data


def _credits(items, key):
    """The sum of the credit amounts (`key`) in a list of usage items, or None."""
    if not isinstance(items, list):
        return None
    found = [i[key] for i in items if isinstance(i, dict) and i.get("unit") == "credit"
             and is_number(i.get(key))]
    return sum(found) if found else None


def _kiro_turn(event):
    """(kind, duration_ms, credits) of a kiro-cli event, or None if it reports neither.

    kind is "turn" for a turn's figures, "session" for v3's session credit total.
    """
    data = event.get("data")
    if not isinstance(data, dict):
        return None
    if event.get("type") == "metadata":  # engine v2, at the end of each turn
        return "turn", data.get("turnDurationMs"), _credits(data.get("meteringUsage"), "value")
    update = data.get("update")
    meta = update.get("_meta") if isinstance(update, dict) else None
    kiro = meta.get("kiro") if isinstance(meta, dict) else None
    if not isinstance(kiro, dict):
        return None
    if kiro.get("kind") == "turn_completion":  # engine v3
        return "turn", kiro.get("elapsedTime"), _credits(kiro.get("promptTurnSummaries"), "usage")
    if kiro.get("kind") == "session_usage":
        return "session", None, _credits(kiro.get("credits"), "usage")
    return None


def parse_kiro(text):
    """The figures in kiro-cli's `--output-format stream-json` events, or {}.

    Engine v2 ends each turn with a "metadata" event carrying meteringUsage
    (credits) and turnDurationMs; engine v3 with a "turn_completion" update
    carrying promptTurnSummaries (credits) and elapsedTime (ms), and reports the
    session's credits in "session_usage" updates. Turns are summed; v3's last
    session total wins for credits. kiro-cli reports no tokens, and its default
    text output reports nothing.
    """
    out, ms_total, credit_total, session_credits = {}, [], [], None
    for event in _json_lines(text):
        data = event.get("data")
        if isinstance(data, dict) and isinstance(data.get("sessionId"), str):
            out["harness_session_id"] = data["sessionId"]
        turn = _kiro_turn(event)
        if turn is None:
            continue
        kind, ms, credits = turn
        if kind == "session":
            session_credits = credits if credits is not None else session_credits
            continue
        if is_number(ms):
            ms_total.append(ms)
        if credits is not None:
            credit_total.append(credits)
    for key, values in (("duration_ms", ms_total), ("credits", credit_total)):
        if values and is_number(sum(values)):
            out[key] = sum(values)
    if session_credits is not None and is_number(session_credits):
        out["credits"] = session_credits
    return out


PARSERS = {"kiro-cli": parse_kiro}


def parse_log(harness, text):
    """The figures in an agent log, read by the harness's parser."""
    return PARSERS.get(harness, parse_result)(text)


def read_log(path):
    """The tail of an agent log as text, or None if it can't be read."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        size = os.fstat(fd)
        if not stat.S_ISREG(size.st_mode):  # a fifo or device must not block or flood a pass
            return None
        f.seek(max(0, size.st_size - TAIL_BYTES))
        return f.read(TAIL_BYTES).decode("utf-8", "replace")


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
    rec.update(parse_log(rec["harness"], log_text or ""))
    return rec


def record(cfg, session, now=None):
    """Append a session's usage record from its agent.log, once; the record, or None.

    Skips operator sessions and sessions without an agent.log.
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
