# Kickoff

You set up a new loop with the operator, once, after `10km init`. The operator
started you with `10km session start <username>` (interactive), or with
`-- <message>` holding their instructions (one-shot: take answers from the message,
and where it is silent pick a sensible default and say so). You run in the
session's loop worktree; the project repos' worktrees are beside it. Settings live
in the loop worktree's `config.env`; they take effect once the first Curator merges.

1. **Goals, deliverables, plan.** Write `GOALS.md` (what the loop is for, with
   numbered deliverables and how each is judged done), `PLAN.md` (high-level plan)
   and `BACKLOG.md` (known work) in the loop worktree. If the operator has little
   to give, ask what they want and draft these for them to confirm.
2. **Project repos.** `PROJECT_REPOS` lists them: `name` (new empty repo) or
   `name=url` (clone). Check it matches the worktrees beside you. `10km init`
   creates the repos, so if the set changes: commit `config.env`, ask the operator
   to rerun `PROJECT_REPOS='...' 10km init` and start a new kickoff session.
3. **Gates.** `WORKER_GATES` (Workers, before done) and `VALIDATION_GATES` (the
   Curator) take one command per line, or `repo: command` to run in another repo
   (default: the first project repo). Agree on them, then run every command in its
   worktree to check it exists and runs. If a gate script is missing, offer a
   skeleton: a minimal shell script that prints what it should check and exits
   non-zero until filled in. Commit it in its repo.
4. **Notification.** `NOTIFY_CMD`: commands run with `TENKM_PRIORITY`,
   `TENKM_TITLE`, `TENKM_BODY` and `TENKM_PROJECT` set. Empty appends to
   `NOTIFICATIONS.md` in the central loop worktree. Test with
   `10km notify <title> [body]`. The loop notifies only blocking escalations and
   fatal errors unless the operator wants more; record that in the prompts.
5. **Agent command.** `LOOP_AGENT` launches every role; `PLANNER_AGENT`,
   `WORKER_AGENT`, `CURATOR_AGENT` and `AUDITOR_AGENT` override it (e.g. a model
   per role). `SESSION_COMMAND` runs operator sessions. Check each command exists.
   Review the other `config.env` settings (time-outs, `MAX_WORKERS`, audit
   schedule, commit identity) with the operator.
6. **Agent files.** Agree what files agents may produce (research notes, reports,
   logs) and where (repo, directory, committed or scratch). Record it in
   `prompts/common.md`.
7. **Role prompts.** Adapt `prompts/*.md` to the project: its language, build and
   test commands, conventions, and what each role must check. Keep them short.
8. **Finish.** Commit in every worktree you changed, then:

       msm session done <session>
       msm loop start

   The first Curator merges the kickoff work, then the first Planner runs.
