"""tenkm: the 10km agent loop library.

Modules:
  state      the loop state machine (msm), one transaction per call
  config     loop settings from config.env and the environment
  gitutil    git helpers
  sessions   session creation and removal (records, branches, worktrees)
  launchers  how agents are started, checked and stopped
  notify     operator notifications
  dispatch   one Dispatcher pass
  status     the status report
"""
