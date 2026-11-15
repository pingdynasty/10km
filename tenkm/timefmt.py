"""tenkm.timefmt: times as the operator reads them.

Clock times are local (TZ, else the system zone): "19:47" today, "Nov 14 23:05" on
another day, "Nov 14 2025 23:05" in another year. Elapsed times are short: "45s",
"3m", "1h12m", "2d4h"; past events get "ago". Every function takes an optional
`tz` (a tzinfo; None for the local zone) so callers and tests can fix the zone.
"""
from datetime import datetime, timezone

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
CTIME = "%a %b %d %H:%M:%S %Y"  # ps -o lstart, in the local zone


def now():
    """The current time, in UTC."""
    return datetime.now(timezone.utc)


def _local(t, tz=None):
    return t.astimezone(tz) if tz is not None else t.astimezone()


def parse(text, tz=None):
    """An aware datetime from ISO 8601 UTC ("...Z"), ISO 8601 with an offset (git
    %cI) or a ctime string as ps prints it (local, or `tz`). None if unreadable."""
    if isinstance(text, datetime):
        return text if text.tzinfo else text.replace(tzinfo=timezone.utc)
    if not isinstance(text, str) or not text.strip():
        return None
    text = text.strip()
    try:
        t = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        t = datetime.strptime(" ".join(text.split()), CTIME)
    except ValueError:
        return None
    return t.replace(tzinfo=tz) if tz is not None else t.astimezone()


def handle_start(handle, tz=None):
    """The start time in a process launcher handle ("process:PID:<ps lstart>")."""
    parts = (handle or "").split(":", 2)
    return parse(parts[2], tz) if len(parts) == 3 and parts[0] == "process" else None


def short_handle(handle):
    """A launcher handle as the operator reads it: "pid N" for the process launcher,
    the handle itself for others, "no handle" without one."""
    parts = (handle or "").split(":", 2)
    if len(parts) == 3 and parts[0] == "process" and parts[1].isdigit():
        return f"pid {parts[1]}"
    return handle or "no handle"


def clock(t, ref=None, tz=None):
    """`t` as a local clock time: "HH:MM" on the day of `ref` (default: now),
    "Nov 14 23:05" on another day, "Nov 14 2025 23:05" in another year."""
    t = parse(t, tz)
    if t is None:
        return "?"
    lt, lr = _local(t, tz), _local(parse(ref, tz) if ref is not None else now(), tz)
    hm = f"{lt.hour:02d}:{lt.minute:02d}"
    if lt.date() == lr.date():
        return hm
    day = f"{MONTHS[lt.month - 1]} {lt.day}"
    return f"{day} {hm}" if lt.year == lr.year else f"{day} {lt.year} {hm}"


def stamp(t, tz=None):
    """`t` with its date, time and zone: "Nov 15 19:47 CET" (the report header)."""
    lt = _local(parse(t, tz), tz)
    return f"{MONTHS[lt.month - 1]} {lt.day} {lt.hour:02d}:{lt.minute:02d} {lt.strftime('%Z')}"


def elapsed(seconds):
    """A duration in seconds as "45s", "3m", "1h12m" or "2d4h" (negative counts as 0)."""
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h{s % 3600 // 60}m"
    return f"{s // 86400}d{s % 86400 // 3600}h"


def since(t, ref=None, tz=None):
    """The time from `t` to `ref` (default: now) as `elapsed` text; "?" if unreadable."""
    t = parse(t, tz)
    if t is None:
        return "?"
    r = parse(ref, tz) if ref is not None else now()
    return elapsed((r - t).total_seconds())


def ago(t, ref=None, tz=None):
    """How long before `ref` (default: now) `t` was: "3m ago"."""
    text = since(t, ref, tz)
    return text if text == "?" else f"{text} ago"
