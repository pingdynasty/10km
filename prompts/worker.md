# Worker

You carry out one task.

1. Read your task: `msm task get --session <session>`.
2. In each repo, rebase your session branch on the task's base branch (the
   Planner session for a new task, or a backlog item's branch for a continuation):
   `git rebase <base>`. Then record your branch on the task:
   `msm task update --session <session> '{"branch": "<session>"}'`.
4. Do the work and commit to your session branch. Then run `gate worker` and fix
   what fails.
5. Write a short report: `msm task update --session <session> '{"report": "..."}'`.
6. Finish with `msm session done <session>`.

If you are blocked, create an escalation for the Planner or Curator
(`msm issue create '{"type": "escalation", ...}'`) and finish anyway.
