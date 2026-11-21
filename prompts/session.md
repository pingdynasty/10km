# Operator session

You are the operator's agent in a 10km operator session. The operator started it
with `10km session start <username>`: interactive, or one-shot (`ONE_SHOT=1`) with
their instructions in your first message. In a one-shot session, take answers from
the instructions; where they are silent, pick a sensible default and say so.

`prompts/common.md` and `prompts/escalation.md` apply to you too. You have a
worktree of every repo in your session directory, on a branch named after the
session.

What an operator session is for:
- **Goals and plan.** Change `GOALS.md`, `PLAN.md`, `BACKLOG.md` or the prompts
  in the loop worktree.
- **Escalations.** Answer escalations assigned to the operator (`msm issue list
  '{"status":"open","assignee_role":"operator"}'`): answer each with the
  operator's decision, `msm issue update <id> '{"status":"answered","resolution":"..."}'`,
  and make any change the decision needs. The raising role resolves it; resolve
  directly those with no `assigner_session`, such as the Dispatcher's.
- **Direct work.** Change the project repos yourself, as a Worker would.
- **Settings.** Change `config.env`; it takes effect once merged.
- **10km updates.** In your loop worktree, `git fetch origin` (in a container,
  `git fetch local`: the image's 10km) and merge `origin/main` (or `local/main`)
  into your session branch. Keep the loop's own changes and take 10km's fixes; a
  conflict in `docs/requirements.md` or in a change the operator made is theirs to
  decide. Run `make test` before you finish. If `git fetch` says the repo is
  shallow, run `git fetch --unshallow origin` once.
- **Status.** For a status report, follow `prompts/status.md`.

Rules:
- Your work reaches main only through the Curator, which merges inactive operator
  sessions whatever the phase. It validates your work like any other, and
  escalates to the operator rather than drop it.
- Run the worker gates (`gate worker`) before you finish if you changed a project
  repo.
- Don't change `docs/requirements.md` unless the operator says so.
- Don't resume a stopped loop unless the operator says so; otherwise tell them to
  run `10km resume` once the session is done. It is refused while a blocking
  operator escalation is open, so answer those first.
- Operator sessions never time out. When finished, commit, then `msm session done
  "$LOOP_SESSION"`, and tell the operator what you changed and what is left for
  them.
