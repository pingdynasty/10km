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
- Commits get a `Loop-Session:` trailer from the commit hook automatically; don't add one.

## Issues

Issues are escalations (a request for help or a decision) or backlog items (work
for later). Before creating one, search for a similar open issue
(`msm issue list '{"status":"open"}'`) and update it instead if one exists.

Create with `msm issue create '<json>'`. Fields:

- `type`: `escalation` or `backlog`; `title`: one line; `description`: the details.
- `owner_session`: your session name.
- `assignee_role`: `planner`, `curator`, `auditor` or `operator`.
- `severity`: `low`, `high` or `blocking`.
- `urgent_if`: for backlog items, the condition under which the item becomes urgent.
- `branch`: the branch holding unmerged work (expired, incomplete or rejected), if any.

Any role may escalate to the planner, curator or auditor. Only the planner, curator
and auditor may escalate to the operator.

An operator escalation states what is needed from the operator, the options, and
your recommendation. Make it `blocking` only if the loop cannot proceed without it.

Resolve an issue with
`msm issue update <id> '{"status":"resolved","resolution":"..."}'`.
