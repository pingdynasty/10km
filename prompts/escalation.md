# Escalations

An escalation asks another role, or the operator, for help or a decision you
cannot make yourself. It is an issue with `type: escalation` (`prompts/common.md`).

## When

- **Escalate rarely.** First try a workaround, a smaller step, or a backlog item.
- Any role may escalate to the Planner, Curator or Auditor. Only the Planner,
  Curator and Auditor escalate to the operator; a Worker reports a blocker in its
  task report, or escalates to the Curator.
- Escalate to the operator only for what the loop cannot settle: a change to the
  goals or requirements, a decision only the operator can make, missing access or
  resources, or a blocker the loop failed to clear twice.

## How

- `title`: the next free ESCn, then the question, in one line (`ESC3: ...`).
- `assignee_role`: who must answer.
- `description`, in this order: what is needed, the context (why the loop can't
  settle it, with evidence: commits, logs, test names), the options, and your
  recommendation.

Write for a reader without the loop's files open: say what each id or name is,
and spell out each shortname on first use.

## Severity

- `low` and `high` don't stop the loop; the assignee acts on them in its own time.
- `blocking` on an operator escalation stops the loop: the Curator notifies the
  operator and stops the loop at the end of its pass, and `msm loop resume` is
  refused until the escalation is answered. Use it only when the loop cannot make
  progress without the answer. A blocking escalation to another role does not
  stop the loop.

## Answering

Answer, follow up and resolve as for any issue (`prompts/common.md`). The operator
answers operator escalations the same way. When you follow up on an answered
escalation, record anything lasting in the plan before you resolve it.
