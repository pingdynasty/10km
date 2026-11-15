# Working in a 10km loop

You are one agent session in a 10km loop. Your session name is in `LOOP_SESSION`,
and your worktrees (one per repo) are in your session directory. Work only in your
own worktrees; never commit in `$LOOP_ROOT/central/`.

- Loop state: `msm` (`msm --help`). Status report: `10km status`.
- Python: `from tenkm import msm` gives the same operations as the `msm` command.
- If msm or a 10km script refuses because your session is no longer active, stop.
  Don't retry and don't do the step by hand: your session has expired and another
  agent has taken over.
- Write files with your file tools, not heredocs, `sed -i` or `>` redirection.
- Use POSIX sh. Redirect output to a file rather than piping, to keep exit codes.
- Never `pkill -f`: other agents run the same commands.
- Run one long command per tool call, in the foreground.
- Read diffs file by file, never whole.
- Background processes and scratch files end with your session.
