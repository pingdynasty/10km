"""tenkm.launchers: how agents are started, checked and stopped.

A launcher is a module with three functions:

    launch(cfg, session, role, env, log_path) -> handle (str)
    alive(cfg, handle) -> True, False, or None if it can't tell
    stop(cfg, handle) -> True if stopped, False if it can't stop agents

The handle is stored in Session.handle. LAUNCHER selects the module (default
"process"); a launcher outside this package can be named as "pkg.module".
"""
import importlib


def get(cfg):
    name = cfg.get("LAUNCHER") or "process"
    module = name if "." in name else f"tenkm.launchers.{name}"
    return importlib.import_module(module)


def kind(handle):
    """The launcher name a handle belongs to ("process:..." -> "process")."""
    return (handle or "").split(":", 1)[0]


def for_handle(handle):
    """The launcher module that issued a handle, or None if there is none.

    A handle from an unknown launcher (or "pending:", recorded before a launch
    completes) can't be checked or stopped; only the time-out applies to it.
    """
    try:
        return get({"LAUNCHER": kind(handle)})
    except ImportError:
        return None
