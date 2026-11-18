"""tenkm: the 10km agent loop library.

Modules:
  msm        the loop state machine, one transaction per call
  config     loop settings from config.env and the environment
  gitutil    git helpers
  sessions   session creation and removal (records, branches, worktrees)
  launchers  how agents are started, checked and stopped
  notify     operator notifications
  dispatch   one Dispatcher pass
  status     the status report
"""
import sys

if sys.version_info < (3, 9):
    sys.exit(f"10km needs Python 3.9 or later; this is {sys.version.split()[0]} "
             f"({sys.executable})")
