# Escalations

An escalation asks another role, or the operator, for help or a decision you
cannot make yourself. It is an issue with `type: escalation`.

## When

- **Escalate rarely.** First try a workaround, a smaller step, or a backlog item.
- Any role may escalate to the Planner, Curator or Auditor. Only the Planner,
  Curator and Auditor escalate to the operator; a Worker reports a blocker in its
  task report, or escalates to the Curator.
- Escalate to the operator only for what the loop cannot settle: a change to the
  goals or requirements, a decision only the operator can make, missing access or
  resources, or a blocker the loop failed to clear twice.

## How

Search first: `msm issue list '{"status":"open","type":"escalation"}'`. If a
similar escalation is open, update it instead of creating another
(`msm issue update <id> '<json>'`).

Create with `msm issue create '<json>'`:
- `type`: `escalation`; `title`: the question, in one line.
- `owner_session`: your session; `assignee_role`: who must answer (`planner`,
  `curator`, `auditor` or `operator`).
- `severity`: `low`, `high` or `blocking`.
- `branch`: the branch holding related unmerged work, if any.
- `description`, in this order: what is needed, the context (why the loop can't
  settle it, with evidence: commits, logs, test names), the options, and your
  recommendation.

Write for a reader without the loop's files open: say what each id or name is.

## Severity

- `low` and `high` don't stop the loop. The assignee acts on them in its own time.
- `blocking`, on an operator escalation, stops the loop: the Curator notifies the
  operator and stops the loop at the end of its pass, and `msm loop resume` is
  refused until the escalation is resolved. Use it only when the loop
  cannot make progress without the answer. A blocking escalation to another role
  does not stop the loop.

## Resolving

The assignee resolves an escalation with
`msm issue update <id> '{"status":"resolved","resolution":"..."}'`: the decision,
and what was done about it. The role that acts on the decision records anything
lasting in the plan.
