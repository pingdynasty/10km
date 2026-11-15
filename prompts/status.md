# Status report

You write a status report on this 10km loop for the operator. This is read-only:
do not edit, commit, merge or change loop state. In an operator session, finishing
it with `msm session done "$LOOP_SESSION"` is the one change you make.

1. **Facts.** Run `10km status` and `10km metrics`. Read `GOALS.md` and
   `PLAN.md` in the central loop worktree (`$LOOP_ROOT/central/loop`), the open
   escalations in full (`msm issue list '{"status":"open","type":"escalation"}'`),
   the last cycle report (`msm cycle list`, then `msm cycle get <id>`) and the
   last audit (`msm audit list`, highest id). Read what you need to assess them,
   and no more. Trust the database and git, not memory; state only what you
   checked, and say "not verified" otherwise.
2. **Report**, in this layout, short and factual. The operator reads it without
   the loop's files open: never use an id, abbreviation or test name without
   saying in a few words what it is.
   1. **State**: running or stopped, the phase and cycle, and one line of why
      (which sessions are active; or the stop reason, its detail and since when).
   2. **Deliverables**: a table `Deliverable | Status | Pending`, one row per
      deliverable in `GOALS.md`, named `DELn (name)`. Status: `not started`, `in progress`, `done` or
      `failed`, from measured evidence (cycle reports, gates, tests). Pending:
      what is left, in a few words, or `-`.
   3. **Recent cycles**: one line per cycle since the last audit, oldest first:
      what it delivered, accepted and rejected work, expiries.
   4. **Audits**: what the last audit concluded and changed.
   5. **Cost and time**: per role, from `10km metrics`, where reported.
   6. **Escalations**, last: for each open operator escalation, blocking or not,
      the question in one plain sentence, the options, the loop's recommendation,
      and what the operator needs to do.
