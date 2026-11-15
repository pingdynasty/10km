"""tenkm.timefmt: times as the operator reads them (R10).

Clock times are local: `tz` (a tzinfo) or, if None, the system zone. Elapsed
times are short, with "ago" for past events.
"""
from datetime import datetime, timezone

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def now():
    """The current time, in UTC."""
    return datetime.now(timezone.utc)


def parse(t):
    """A UTC datetime from an ISO 8601 string (naive means UTC) or a datetime; None
    if unreadable."""
    if isinstance(t, str):
        try:
            t = datetime.fromisoformat(t.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(t, datetime):
        return None
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)


def clock(t, ref=None, tz=None):
    """`t` as "19:47" on the day of `ref` (default: now), "Nov 14 23:05" on another
    day, "Nov 14 2025 23:05" in another year; "?" if unreadable."""
    t = parse(t)
    if t is None:
        return "?"
    lt, lr = t.astimezone(tz), (parse(ref) or now()).astimezone(tz)
    hm = f"{lt.hour:02d}:{lt.minute:02d}"
    if lt.date() == lr.date():
        return hm
    day = f"{MONTHS[lt.month - 1]} {lt.day}"
    return f"{day} {hm}" if lt.year == lr.year else f"{day} {lt.year} {hm}"


def stamp(t, tz=None):
    """`t` with date, time and zone: "Nov 15 19:47 CET"."""
    lt = parse(t).astimezone(tz)
    return f"{MONTHS[lt.month - 1]} {lt.day} {lt.hour:02d}:{lt.minute:02d} {lt.strftime('%Z')}"


def elapsed(seconds):
    """A duration as "45s", "3m", "1h12m" or "2d4h" (negative counts as 0)."""
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h{s % 3600 // 60}m"
    return f"{s // 86400}d{s % 86400 // 3600}h"


def since(t, ref=None):
    """The `elapsed` time from `t` to `ref` (default: now); "?" if unreadable."""
    t = parse(t)
    return "?" if t is None else elapsed(((parse(ref) or now()) - t).total_seconds())


def ago(t, ref=None):
    """`since` with " ago": "3m ago"."""
    text = since(t, ref)
    return text if text == "?" else f"{text} ago"
