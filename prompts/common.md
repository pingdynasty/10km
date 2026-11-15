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
- Only the operator decides when cycles, tasks, audits and issues are archived or
  removed, and may delegate this to an agent. Don't remove them unless delegated.

## Shortnames

Goals, deliverables, escalations and plan phases have numbered shortnames: G1,
G2, ...; DEL1, ...; ESC1, ...; PH1, .... Use them consistently in `GOALS.md`,
`PLAN.md`, escalations and reports; never renumber. When writing to the operator
(escalations, notifications, cycle and status reports), spell out what each
shortname means on first use: "DEL2 (status report)".

## Issues

Issues are escalations (a request for help or a decision) or backlog items (work
for later). Before creating one, search for a similar open issue
(`msm issue list '{"status":"open"}'`) and update it instead if one exists.

For escalations, when to raise them, how to write them, severity and resolving,
read `prompts/escalation.md` before you create or answer one.

Create a backlog item with `msm issue create '<json>'`. Fields:

- `type`: `backlog`; `title`: one line; `description`: the details.
- `owner_session`: your session name.
- `assignee_role`: `planner`, `curator`, `auditor` or `operator`.
- `severity`: `low`, `high` or `blocking`.
- `urgent_if`: for backlog items, the condition under which the item becomes urgent.
- `branch`: the branch holding unmerged work (expired, incomplete or rejected), if any.

Resolve an issue with
`msm issue update <id> '{"status":"resolved","resolution":"..."}'`.
