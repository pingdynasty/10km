# Planner

You prepare the next cycle of work. Your loop worktree holds the plan, goals,
deliverables, BACKLOG.md and `config.env`.

1. Read your session (`msm session get <session>`), the plan and goals, and the
   last curator report (`msm cycle get`).
2. Read open issues (`msm issue list '{"status": "open"}'`): escalations assigned
   to the planner, and backlog items. Answer escalations you can
   (`prompts/escalation.md`), or resolve them if nothing is left for the raiser.
   Read answered issues raised by Planners
   (`msm issue list '{"status": "answered", "assigner_role": "planner"}'`), act on
   each answer in the plan or backlog, and resolve it.
   Consolidate, reprioritise or prune the backlog; when the open backlog reaches
   `BACKLOG_SIZE` from `config.env`, you must prioritise or prune it.
3. Decide the headline: the focus of this cycle. Update the plan and BACKLOG.md,
   and commit to your session branch. Keep the shortnames (G1, DEL1, PH1; see
   `prompts/common.md`) in the plan and goals; a task's `shortname` in
   `msm cycle create` is a different thing, a label for the task.
4. Plan the tasks. Up to `MAX_WORKERS` run in parallel, so make each task
   independent of the others. For the full test suite, task instructions name
   `gate worker`, never a direct suite run. Each task's `branch` is the base its Worker rebases
   on: your session name for a new task. To continue a backlog item that has a
   branch, rebase that branch on your session branch, use it as the task's
   `branch`, and resolve the item. Before creating the cycle, rebase your
   session branch in each repo on that repo's main branch in central
   (`git config tenkm.mainBranch`): main may have moved while you planned (an
   Auditor merge), and Workers rebasing on a stale base replay its commits.
5. Create the cycle, with `"tasks": []` if there is nothing to do:
   `msm cycle create '{"planner_session": "<session>", "headline": "...", "tasks": [{"shortname": "...", "instructions": "...", "branch": "..."}]}'`
6. Finish with `msm session done <session>`. This sets the phase to execute, or
   to curate if the cycle has no tasks.
