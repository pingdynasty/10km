"""tenkm.notify: operator notifications.

Every command in NOTIFY_CMD (one per line) runs with TENKM_PRIORITY (critical,
default or passive), TENKM_TITLE, TENKM_BODY and TENKM_PROJECT set. With no
commands, the notification is appended to NOTIFICATIONS.md in the central loop
worktree (gitignored).

A notification with a key is sent once: later calls with the same key are skipped.
A failed send is not recorded, so the next call retries it.
"""
import json
import os
import subprocess
from datetime import datetime, timezone

from .locks import lock

PRIORITIES = ("critical", "default", "passive")


def _sent_path(cfg):
    return os.path.join(cfg.state_dir, "notices.json")


def _load(cfg):
    try:
        with open(_sent_path(cfg)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(cfg, sent):
    os.makedirs(cfg.state_dir, exist_ok=True)
    tmp = _sent_path(cfg) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(sent, f, indent=1)
    os.replace(tmp, _sent_path(cfg))


def forget(cfg, prefix):
    """Forget keys starting with prefix, so their notifications can be sent again."""
    with lock(cfg, "notify"):
        sent = _load(cfg)
        kept = {k: v for k, v in sent.items() if not k.startswith(prefix)}
        if kept != sent:
            _save(cfg, kept)


def send(cfg, title, body="", priority="default", key=None):
    """Notify the operator. Returns True if sent (or already sent for this key)."""
    with lock(cfg, "notify"):
        return _send(cfg, title, body, priority, key)


def _send(cfg, title, body, priority, key):
    if priority not in PRIORITIES:
        priority = "default"
    sent = _load(cfg)
    if key and key in sent:
        return True
    project = cfg.get("PROJECT_NAME") or (cfg.projects() or ["loop"])[0]
    commands = cfg.lines("NOTIFY_CMD")
    ok = True
    if commands:
        env = dict(os.environ, TENKM_PRIORITY=priority, TENKM_TITLE=title, TENKM_BODY=body,
                   TENKM_PROJECT=project)
        for command in commands:
            if subprocess.run(["bash", "-c", command], env=env).returncode != 0:
                ok = False
    else:
        path = os.path.join(cfg.central, "loop", "NOTIFICATIONS.md")
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            with open(path, "a") as f:
                f.write(f"## {stamp} [{priority}] {title}\n\n{body}\n\n" if body
                        else f"## {stamp} [{priority}] {title}\n\n")
        except OSError:
            ok = False
    if ok and key:
        sent[key] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _save(cfg, sent)
    return ok
