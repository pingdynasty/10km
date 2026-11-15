"""tenkm.faults: named crash points for recovery tests.

    faults.point("publish:after-ff:loop")

If TENKM_FAULT names this point, the process exits at once with status 99, as if
it had been killed there. Tests use this to prove that rerunning recovers.
"""
import os


def point(name):
    if os.environ.get("TENKM_FAULT") == name:
        os._exit(99)
