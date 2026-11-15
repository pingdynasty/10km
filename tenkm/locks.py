"""tenkm.locks: exclusive file locks in the loop's state directory."""
import fcntl
import os
from contextlib import contextmanager


@contextmanager
def lock(cfg, name, blocking=True):
    """Hold <state_dir>/<name>.lock. Yields False if non-blocking and already held."""
    os.makedirs(cfg.state_dir, exist_ok=True)
    with open(os.path.join(cfg.state_dir, f"{name}.lock"), "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        yield True
