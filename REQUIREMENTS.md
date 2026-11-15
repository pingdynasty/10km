# Ten Thousand Monkeys: Requirements

## Agent Roles and Responsibilities
Workers: Carry out tasks
Planner: Prepares the next cycle of work by creating tasks
Curator: Validates all session work and merges accepted work
Auditor: Inspects the functioning of the loop for possible improvements

## Scripts and Actions
Kickoff: Set up a loop with goals, deliverables, high-level plan and worker instructions
Dispatcher: Spawns agents of all roles
Session: Loop collaboration, interactive or one-shot
Notification: Send the operator a message
Escalation: Ask the operator or another agent role for assistance or a decision
Status: Get a project status report

## Git Repositories and File System
There is one loop repo, and one or more project repos configured at kickoff.
The loop repo contains its scripts and prompts, the plan, goals, deliverables, BACKLOG.md, LEARNINGS.md.
The database and action log are at a configured path, outside the repos.
Configuration is in `config.env` in the loop repo (see Configuration below). Scripts read it from the central loop worktree.
The operator may provide one or more pre-existing project repos for the loop to work on.
If not, a new project repo is created during kickoff.
Each session has a directory with git worktrees and scratch files.
In this document, main means each repo's default branch.
Under normal operation, all worktrees and branches are merged into main and removed by the Curator.
If sessions expire, the Curator will attempt to fix them up but stale branches may remain.
There are central worktrees that the Curator keeps up to date.
Worktrees are named after the session, with cycle where applicable and role. E.g.
```
root/cycle123-planner-abcd/loop/
root/cycle123-planner-abcd/project-repo1/
root/cycle123-planner-abcd/project-repo2/
root/cycle123-worker1-abcd/loop/
root/cycle123-worker1-abcd/project-repo1/
root/cycle123-worker1-abcd/project-repo2/
root/cycle123-curator-abcd/loop/
root/cycle123-curator-abcd/project-repo1/
root/cycle123-curator-abcd/project-repo2/
root/operator-someone-abcd/loop/
root/operator-someone-abcd/project-repo1/
root/operator-someone-abcd/project-repo2/
root/auditor123-abcd/loop/
root/auditor123-abcd/project-repo1/
root/auditor123-abcd/project-repo2/
root/central/loop/
root/central/project-repo1/
root/central/project-repo2/
```

- Commit trailers: every agent commit carries a `Loop-Session:` trailer. The session script or the role prompt sets it. With trailers, the Auditor can attribute work even after branches are gone.
- Harness sessions: name each coding-harness session after the loop session, or record the harness session name in a trailer. That lets the Auditor join token and time metrics to role and cycle.

### Configuration
- Project repos
- Database and action log path
- Main branch
- Commit identity
- Launcher and agent commands
- Session time-outs
- Max workers
- Auditor daily time, timezone and cycle limit
- Idle cycle limit
- Backlog size
- Worker and validation gates
- Notification action

## State Machine
Loop state is managed through a deterministic script with atomic transactions.
The state machine manages only the database. It does not touch files or git.
```bash
msm init
msm loop start|resume
msm loop stop [reason]
msm loop get
msm loop update <json>

msm session create <role> [username] -> {session}
msm session update <name> <json>     -> {session}
msm session get <name>               -> {session}
msm session list [filter]            -> [sessions]
msm session done|expired <name>
msm session remove <name>

msm task get|remove <id> | --session <name>
msm task update <id> | --session <name> <json>
msm task list [filter]
msm task batch <verdicts-json> [<cycle-curate-json>]

msm cycle create|curate {json}
msm cycle get|list|update|remove ...

msm issue|audit get|list|create|update|remove ...
```
Create calls take a string or JSON input and return a JSON representation of the created resource, or an error code and message.
Update calls take a JSON input with the fields to be changed, and return a JSON representation of the updated resource, or an error code and message. Fields are cleared with null.
Get and remove take an id. List takes an optional filter: a JSON object matched against fields, e.g. `{"status":"open"}`.
`loop update` cannot change `phase`, `stopped`, `current_cycle` or `last_audit`.
The state machine returns exit status:
- 0 for success
- 1 (EINVAL) for invalid arguments
- 2 (EPERM) if preconditions are not met
- 3 (ENOENT) if a resource is not found

### Side effects:
1. Creating a Worker session claims the first waiting task: sets `session`, `started_at`, `status: active`.
2. Updating a Worker session to done|expired sets its task to the same status and sets `done_at`.
3. Removing a Worker session whose task is still `active` returns that task to `waiting`, clearing `session` and `started_at`.
4. `cycle create` requires phase = plan and not stopped. It increments the cycle and creates the tasks. If phase = plan and the current cycle is open, it replaces that cycle and its tasks instead. It sets `empty_cycles` to the previous value + 1 if tasks is empty, or 0 otherwise.
5. `cycle curate` closes the cycle.
6. `loop start` sets stopped = false, reason = null.
7. `loop resume` sets stopped = false, reason = null.
8. `loop stop <reason>`: stopped = true, reason = <reason>.

Changing loop or session status updates `updated_at`.
An expired session cannot be set to done.
Creating a Cycle sets `id: (Loop.current_cycle + 1)`, `status: open` and `planned_at`.
Curating a Cycle sets `curated_at` and `status: closed`.
Creating a Task sets `cycle`, `status: waiting`, and `created_at`.
Updating a Task to `status: accepted|rejected` sets `curated_at`.
Creating an Audit sets `id: (Loop.last_audit + 1)`, `created_at`, and `Loop.last_audit = id`.
`msm init` sets `current_cycle = 0`, `last_audit = 0`, `empty_cycles = 0`, phase = curate, stopped = true.

### Callers
Agents call msm with their session name in `LOOP_SESSION`, set by the Dispatcher. If that session is expired or no longer exists, msm refuses any change with EPERM.
While the loop is stopped, msm refuses agents' changes to the loop record (`loop start`, `loop resume`, `loop update`) with EPERM.
msm appends every change to a cycle, task, audit or issue to an action log: a text file, one line per change with the time, the caller's session and the command.

### Role Preconditions
- Planner: phase = plan, not stopped, no active Planner.
- Curator: not stopped, no active Curator, and either phase = curate or an inactive operator or Auditor session exists.
- Worker: phase = execute, not stopped, a waiting task exists. The task is claimed atomically.
- Auditor: not stopped, no Auditor session.
- Operator: always.

### State
```
Loop    { current_cycle: number,
	      last_audit: number,
	      empty_cycles: number,
	      phase: plan|execute|curate, 
          stopped: boolean,
		  reason: string|null,
          updated_at: time }

Session { name: string,
          role: planner|worker|curator|auditor|operator,
          status: active|done|expired,
          handle: string|null,
          working_directory: string,
          created_at: time, 
		  updated_at: time }

Cycle   { id: number,
          status: open|closed,
		  planner_session: string,
          planned_at: time, 
          headline: string,
          report: string,
		  curator_session: string,
		  curated_at: time }

Task    { id : uuid, 
	      cycle: number, 
		  shortname: string, 
		  instructions: string, 
		  branch: string, 
		  session: string, 
		  report: string,
          status: waiting|active|done|expired|accepted|rejected,
          created_at: time, 
		  started_at: time, 
		  done_at: time,
		  curated_at: time }

Issue   { id: uuid,
          type: escalation|backlog,
          title: string,
          description: string,
          owner_session: string,
          assignee_role: planner|curator|auditor|operator,
          resolver_role: planner|curator|auditor|operator,
          severity: low|high|blocking,
          urgent_if: string,
          status: open|resolved,
          branch: string,
          created_at: time, 
		  resolved_at: time,
		  resolution: string }

Audit   { id: number,
          period: { from: time, to: time },
          summary: string,
          created_at: time }

cycle create
        { planner_session: string, 
		  headline: string, 
          tasks: [{ shortname, instructions, branch }] }

cycle curate
        { curator_session: string, 
		  report: string }
```
State is stored in a database that supports transactions.
Sessions and Status reflect a point in time. 
Cycles, Tasks, Audits and Issues accumulate. They are kept for metrics and analysis, but are disposable. Only the operator decides when they are archived or removed, and may delegate this to an agent. Removal must not affect the current cycle, open issues, or active sessions.

### Phase Transitions
Planner session `done`: if the current cycle is open: phase = execute, or curate if it has no tasks.
Worker session `done|expired`: if no tasks remain waiting or active: phase = curate.
Curator session `done`: if the current cycle is not open: phase = plan.
`loop start`: phase = curate.
`loop resume`: phase = curate if phase = plan.

## Sessions
Agents and operators do their work in sessions.
When a session is instantiated, these are created:
- a session record
- a working directory
- git worktrees
- session branch for each worktree
When the agent finishes, the session status is set to done.
Sessions expire after a configurable amount of time.
Sessions are named `cycle#-planner|curator|worker#`, `auditor#`, or `operator-username`.
The assigned worker number is the number of existing workers in the cycle + 1.
The assigned auditor number is `Loop.last_audit` + 1.
The session name is used as that session's git branch across all repos.
A short, unique string of readable characters shall be appended to ensure branch uniqueness.
e.g. `cycle12-worker3-abcd1234`, `auditor123-abcd2345`, `operator-mars-abcd3456`.
Operator sessions can be interactive or one-shot.
Sessions are created by a deterministic script with exclusive file locking (flock) that takes a role argument.
The script first calls `msm session create <role>` which fails if preconditions are not met.
If session create succeeds, it attempts to create git branches, a working directory, and git worktrees.
If that fails, it removes the session record and any created branches or directories/files.
The script returns exit status:
- 0 for success, session created
- EPERM or EINVAL if `msm session create` fails
- 4 (EAGAIN) if the session name is already used by another git branch
- 5: git or worktree creation errors

## Dispatcher
The Dispatcher is invoked periodically, e.g. by cron, at an interval set in the configuration.
When the Dispatcher is invoked, it reads the loop state.
It checks for and expires timed out sessions.
If the loop is stopped, it exits.
If an inactive operator or Auditor session exists, it launches a Curator, whatever the phase.
Then, by phase:
  plan    -> launch Planner
  execute -> launch Workers while launches succeed, up to max workers active
  curate  -> launch Curator
Launches fail harmlessly if the role's preconditions are not met.
It launches an Auditor when the configured daily time, in the configured timezone, has passed and no audit has run since then, or when the configured number of cycles have been curated since the last audit. Either trigger can be disabled. The first Auditor runs only after a cycle has been curated.
To launch a role, it attempts to create a session. If it fails with EAGAIN (4) it tries again, up to 3 times.
If it succeeds it reads the role prompt.
It writes the role prompt to a file in the session directory, launches the agent through the configured launcher with the session name and prompt file path in its first message, and records the launcher's handle in the session.
The launcher is configured for the loop. The default process launcher runs an agent command, configured for the loop or specialised for each role:
`LOOP|PLANNER|WORKER|CURATOR|AUDITOR_AGENT=...`
`LOOP_AGENT="pi --no-session --name $SESSION -p $PROMPT"`
`LOOP_AGENT="claude --no-session-persistence --dangerously-skip-permissions -n $SESSION -p $PROMPT"`
`LOOP_AGENT="kiro-cli chat --trust-tools --no-interactive $PROMPT"`
`LOOP_AGENT="codex exec --ephemeral --sandbox $PROMPT"`

### Session Time-out
The Dispatcher times out sessions that have run longer than the configured limit. Operator sessions are never timed out.
It asks the launcher to stop the agent (process launcher: SIGTERM, a short grace period, then SIGKILL) and sets the session status to expired. If the launcher cannot confirm the agent stopped, the Dispatcher also creates a non-blocking operator escalation naming the session.
The Dispatcher may also expire sessions whose launcher reports them not running, after a start grace period. Sessions not launched by the Dispatcher have no handle.

Notes:
Expired Planners and Curators need no special rule. The phase hasn't moved, so the next dispatcher run relaunches them. The next Planner's `cycle create` replaces an open cycle.
A Curator that crashes before Publish leaves main unchanged, and the next Curator redoes the pass. One that crashes after Publish has already merged its work, so redoing the pass changes nothing. Sessions left by a crash after Publish are removed by the next Clean up.
The Curator doesn't wait for active operator and Auditor sessions to finish before launching.
A failing Planner or Curator is relaunched until it succeeds.

### Resume
Only the operator can resume a stopped loop: 
- start an operator session
- resolve blocking escalations, or update the goals
- set the operator session to done
- call `loop resume`

## Issues
There are two types of issues: Escalation, and Backlog.
Issues from unmerged work (expired, incomplete, or rejected) should reference its branch.

## Escalations
Issues can be escalated by any role to the Planner, Auditor or Curator.
Planner, Curator and Auditor can escalate to the operator.
The escalation prompt tells agents how to write an operator escalation.

## Backlog
Agents and operators can create backlog items.
There may be a backlog summary in BACKLOG.md. Planner keeps it current.
If the backlog reaches a certain size, the planner shall prioritise backlog items or prune them.
Backlog items should indicate under what conditions they become urgent.
Issues should not be created without first searching for existing, similar issues.

## Planner
It is launched with its session name. It reads its session.
It reads the plan, open backlog items, and the last curator report.
It reads open escalations.
It may resolve escalations.
It may consolidate, reprioritise, or prune the backlog.
It updates the plan and decides the headline (focus/goal/purpose of cycle).
It plans the cycle tasks.
It may plan tasks from backlog items:
- if the item has a branch, rebase it on the Planner branch and use as the task branch
- resolve the item
It creates a new cycle with headline and tasks, or empty if there is no work to do.
It sets its session to done (sets phase = execute, or curate if there are no tasks).

## Worker
It is launched with its session name. It reads its session and its task.
In each repo, it rebases its session branch on the task's base branch: the Planner session for new tasks, or a backlog item's branch for continuations. It then sets the task's `branch` field to its session name.
The worker agent performs the work in the worktree, and commits to the session branch.
When finished, it sets the session to done (this also sets the task to done).

## Curator
The Curator agent runs these steps in order. Steps marked (script) are deterministic scripts that it calls. Scripts refuse to run unless the Curator session is active.
Scripts never remove branches referenced by open issues.

Step 1: Clean up (script `curate-clean`)
It removes done Curator sessions, and expired Curator and Planner sessions, with their worktrees and branches.
It removes sessions left over from closed cycles, with their worktrees and branches.

Step 2: Select (script `curate-select`)
It selects and returns the sessions to curate:
- if they exist: inactive operator and Auditor sessions
- otherwise, if phase = curate: the current cycle's inactive Planner and Worker sessions
- otherwise: nothing
Note: A session is inactive if its status is done or expired.
Note: Operator and Auditor work is curated as soon as it is done, in its own pass, whatever the phase. The cycle is then curated with fresh context against the updated goals and prompts.
If the selection is empty, the Curator skips to Step 7.

Step 3: Triage (script `curate-merge`)
The script merges done sessions into the Curator session, reporting conflicts.
The agent resolves reported conflicts, then triages expired sessions:
- complete work is merged by rerunning `curate-merge` with the session; it is kept if the merge is clean
- incomplete work is either backlogged or discarded

Step 4: Read
It reads the plan, goals, open escalations, the current cycle, and audits since the cycle was planned.

Step 5: Evaluate
For each done or accepted expired Worker session:
- read the associated task
- review commits and diffs against goals and task instructions
- accept or reject the task, in whole or in part

Step 6: Validate
It runs the validation gates listed in config.env, and may make small fixes to failing work.
If any gate fails, it rejects the responsible work.
For all work rejected in Step 5 or 6, it calls `curate-rebuild --without <sessions>` and re-validates. Partially accepted work is cherry-picked before re-validation.
If operator work is rejected then the failure shall be escalated to the operator.
If other work is rejected then it shall be either backlogged or discarded.

Step 7: Assess
It evaluates milestones, goals and deliverables
It may update the plan and backlog.
It may resolve escalations.
If the project is done, or `Loop.empty_cycles` has reached the idle limit from config.env, create a blocking operator escalation with reason `done` or `idle`.
If there are blocking operator escalations, notify the operator.

Step 8: Publish (script `curate-publish`)
The script fast-forwards main onto the Curator branch in each project repo, then in the loop repo. It then runs the task status updates and, if a Planner session was selected, `cycle curate`, in one msm transaction. It is safe to rerun.
The agent passes any task verdicts and the cycle report as arguments. It publishes even if nothing was selected, so that its own plan and backlog updates reach main.

Step 9: Cleanup (script `curate-cleanup`)
It updates central worktrees.
It removes the selected sessions with their worktrees and branches.

Step 10: Exit
If there are blocking operator escalations, it calls `loop stop blocked`.
It sets the Curator session to done (phase = plan if the cycle is not open).

## Auditor
It is launched with its session name. It reads its session.
It reads its prompt and the last audit.
It reads previous learnings from LEARNINGS.md.
It reads any open escalations.
It retrieves a git log summary since last audit.
It analyses git history for time spent per role and cycle.
It may analyse agent harness metrics for tokens or credits used per role and cycle.
It retrieves the sizes and growth of prompt files.
It evaluates progress against the goals, deliverables and plan.
It looks for recurring expired tasks, and long-running or expired sessions.
It may trim files by summarizing, culling or archiving.
It may remove merged git branches.
It may update role prompts.
It may instruct the planner to make smaller or bigger tasks with fewer or more parallel workers.
It may instruct the Curator to relax or tighten validation criteria.
It may clarify definitions of done, e.g. for deliverables, milestones, goals.
It may create scripts to automate common agent tasks.
It may resolve open escalations.
If it can fix a problem itself, it does so. If not, it may create backlog items or escalations.
It may add to LEARNINGS.md if the learnings are general.
It stores an audit report in the database.
The Auditor will not run until the previous audit has been curated.

## Prompts
Every role and some actions (Kickoff, Session, Status, Escalation) has a prompt. Most prompts can and should be adapted to the project either during Kickoff, or while the loop is running: by the auditor, curator or planner, or operator sessions.

## Agent Files
Files can be used for agents to communicate, for example for workers to save research.
What type of files that agents may produce, and where, is determined during kickoff.

## Kickoff
An init script prepares the loop: it calls `msm init`, creates the project repo if none is provided, and creates the central worktrees.
The kickoff determines the goals, the plan, and the deliverables.
It ensures that loop prompts meet the project needs.
Kickoff can be an interactive operator session, or a one-shot operator instruction.
When done, kickoff sets its session to done and calls `loop start`. The Curator then merges the kickoff work before the first Planner runs.

## Notification
The operator notification mechanism should be a deterministic action configured during Kickoff.
The default notification is to append to NOTIFICATIONS.md in the central loop worktree. The file is gitignored, so notifications are immediate and don't depend on a merge.
Unless given other instructions, the loop only notifies the operator of blocking escalations and fatal errors.

# Test Scripts
Replace agent command with test invocation: `LOOP_AGENT=test.sh $SESSION`
Test reads next item from script, checks the role, runs command.
If next item is 'verify', runs it and checks result.
planner: msm cycle create {...}
planner: msm session done $SESSION
worker: msm task update --session $SESSION {report: ...}
worker: msm session done $SESSION
verify: msm task get --session $SESSION == {status:done, report: ...}
curator: msm cycle curate {...}
curator: msm session done $SESSION
verify: msm cycle get 1 == {report: ...}
