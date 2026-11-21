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
- Never push the loop repo. Its remotes, `origin` and `local`, are 10km's (where
  this loop came from): fetch from them, never push. Updating from them is the
  operator's call (`prompts/session.md`).
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
(`msm issue list '{"status":"open"}'`) and update it instead if one exists
(`msm issue update <id> '<json>'`). Before you create or answer an escalation,
read `prompts/escalation.md`.

Create an issue with `msm issue create '<json>'`. Fields:

- `type`: `backlog` or `escalation`; `title`: one line; `description`: the details.
- `assignee_role`: `planner`, `curator`, `auditor` or `operator`.
- `severity`: `low`, `high` or `blocking`.
- `urgent_if`: for backlog items, the condition under which the item becomes urgent.
- `branch`: the branch holding unmerged work (expired, incomplete or rejected), if any.

msm records your session and role as `assigner_session` and `assigner_role`.

An issue goes open, then answered, then resolved:

- The assignee answers:
  `msm issue update <id> '{"status":"answered","resolution":"..."}'`, with the
  answer or decision.
- The role that raised it follows up. Read the answered issues your role raised
  (the list command is in your role prompt), act on each answer (a plan change, a
  backlog item, a task), then resolve it:
  `msm issue update <id> '{"status":"resolved","resolution":"..."}'`, with the
  answer and what was done.
- The assignee resolves directly, without answering, when nothing is left for
  another role: a backlog item it has done, or an issue its own role raised or
  with no `assigner_session`.
