# Ten Thousand Monkeys: Requirements

> Requirement IDs: each requirement carries an ID `Rn`, as `**Rn**` before its
> sentence or list item, or as a trailing `# Rn` inside code blocks. Find them
> with `grep -nwE 'R[0-9]+'`. IDs are stable: new requirements take the next
> unused number, removed numbers are not reused, and nothing is renumbered.

## Agent Roles and Responsibilities
**R1** Workers: Carry out tasks
**R2** Planner: Prepares the next cycle of work by creating tasks
**R3** Curator: Validates all session work and merges accepted work
**R4** Auditor: Inspects the functioning of the loop for possible improvements

## Scripts and Actions
**R5** Kickoff: Set up a loop with goals, deliverables, high-level plan and worker instructions
**R6** Dispatcher: Spawns agents of all roles
**R7** Session: Loop collaboration, interactive or one-shot
**R8** Notification: Send the operator a message
**R9** Escalation: Ask the operator or another agent role for assistance or a decision
**R10** Status: Get a project status report

## Git Repositories and File System
**R11** There is one loop repo, and one or more project repos configured at kickoff.
**R12** The loop repo contains its scripts and prompts, the plan, goals, deliverables, BACKLOG.md, LEARNINGS.md.
**R13** The database and action log are at a configured path, outside the repos.
**R14** Configuration is in `config.env` in the loop repo (see Configuration below). **R15** Scripts read it from the central loop worktree.
**R16** The operator may provide one or more pre-existing project repos for the loop to work on.
**R17** If not, a new project repo is created during kickoff.
**R18** Each session has a directory with git worktrees and scratch files.
**R19** In this document, main means each repo's configured branch.
**R20** Under normal operation, all worktrees and branches are merged into main and removed by the Curator.
**R21** If sessions expire, the Curator will attempt to fix them up but stale branches may remain.
**R22** There are central worktrees that the Curator keeps up to date.
**R23** Worktrees are named after the session, with cycle where applicable and role. E.g.
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

- **R24** Commit trailers: every agent commit carries a `Loop-Session:` trailer. **R25** The session script or the role prompt sets it. With trailers, the Auditor can attribute work even after branches are gone.
- **R26** Harness sessions: name each coding-harness session after the loop session, or record the harness session name in a trailer. That lets the Auditor join token and time metrics to role and cycle.

### Configuration
- **R27** Database and action log path
- **R28** Launcher and agent commands
- **R29** Session time-outs
- **R30** Max workers
- **R31** Auditor daily time, timezone and cycle limit
- **R32** Idle cycle limit
- **R33** Backlog size
- **R34** Worker and validation gates
- **R35** Notification action

## State Machine
**R36** Loop state is managed through a deterministic script with atomic transactions.
**R37** The state machine manages only the database. **R38** It does not touch files or git.
```bash
msm init  # R39
msm loop start|resume  # R40
msm loop stop [reason]  # R41
msm loop get  # R42
msm loop update <json>  # R43

msm session create <role> [username] -> {session}  # R44
msm session update <name> <json>     -> {session}  # R45
msm session get <name>               -> {session}  # R46
msm session list [filter]            -> [sessions]  # R47
msm session done|expired <name>  # R48
msm session remove <name>  # R49

msm task get|remove <id> | --session <name>  # R50
msm task update <id> | --session <name> <json>  # R51
msm task list [filter]  # R52

msm cycle create|curate {json}  # R53
msm cycle get|list|update|remove ...  # R54

msm issue|audit get|list|create|update|remove ...  # R55
```
**R56** Create calls take a string or JSON input and return a JSON representation of the created resource, or an error code and message.
**R57** Update calls take a JSON input with the fields to be changed, and return a JSON representation of the updated resource, or an error code and message. **R58** Fields are cleared with null.
**R59** Get and remove take an id. **R60** List takes an optional filter: a JSON object matched against fields, e.g. `{"status":"open"}`.
**R61** `loop update` cannot change `phase`, `stopped`, `current_cycle` or `last_audit`.
The state machine returns exit status:
- **R62** 0 for success
- **R63** 1 (EINVAL) for invalid arguments
- **R64** 2 (EPERM) if preconditions are not met
- **R65** 3 (ENOENT) if a resource is not found

### Side effects:
1. **R66** Creating a Worker session claims the first waiting task: sets `session`, `started_at`, `status: active`.
2. **R67** Updating a Worker session to done|expired sets its task to the same status and sets `done_at`.
3. **R68** Removing a Worker session whose task is still `active` returns that task to `waiting`, clearing `session` and `started_at`.
4. **R69** `cycle create` requires phase = plan and not stopped. **R70** It increments the cycle and creates the tasks. **R71** If phase = plan and the current cycle is open, it replaces that cycle and its tasks instead. **R72** It sets `empty_cycles` to the previous value + 1 if tasks is empty, or 0 otherwise.
5. **R73** `cycle curate` closes the cycle and its tasks.
6. **R74** `loop start` sets stopped = false, reason = null.
7. **R75** `loop resume` sets stopped = false, reason = null.
8. **R76** `loop stop <reason>`: stopped = true, reason = <reason>.

**R77** Changing loop or session status updates `updated_at`.
**R78** An expired session cannot be set to done.
**R79** A closed cycle can't be changed.
**R80** Creating a Cycle sets `id: (Loop.current_cycle + 1)`, `status: open` and `planned_at`.
**R81** Curating a Cycle sets `curated_at` and `status: closed`.
**R82** Creating a Task sets `cycle`, `status: waiting`, and `created_at`.
**R83** Updating a Task to `status: accepted|rejected` sets `curated_at`.
**R84** Creating an Audit sets `id: (Loop.last_audit + 1)`, `created_at`, and `Loop.last_audit = id`.
**R85** `msm init` sets `current_cycle = 0`, `last_audit = 0`, `empty_cycles = 0`, phase = curate, stopped = true.

### Callers
**R86** Agents call msm with their session name in `LOOP_SESSION`, set by the Dispatcher. **R87** If that session is expired or no longer exists, msm refuses any change with EPERM.
**R88** While the loop is stopped, msm refuses agents' changes to the loop record (`loop start`, `loop resume`, `loop update`) with EPERM.
**R89** msm appends every change to a cycle, task, audit or issue to an action log: a text file, one line per change with the time, the caller's session and the command.

### Role Preconditions
- **R90** Planner: phase = plan AND not stopped AND no active Planner
- **R91** Curator: not stopped AND no active Curator AND (phase = curate OR an inactive operator or Auditor session exists)
- **R92** Worker: phase = execute AND not stopped AND a waiting task exists
- **R93** Auditor: not stopped AND no Auditor session
- **R94** Operator: always

### State
```
Loop    { current_cycle: number,  # R95
	      last_audit: number,
	      empty_cycles: number,
	      phase: plan|execute|curate, 
          stopped: boolean,
		  reason: string|null,
          updated_at: time }

Session { name: string,  # R96
          role: planner|worker|curator|auditor|operator,
          status: active|done|expired,
          handle: string|null,
          working_directory: string,
          created_at: time, 
		  updated_at: time }

Cycle   { id: number,  # R97
          status: open|closed,
		  planner_session: string,
          planned_at: time, 
          headline: string,
          report: string,
		  curator_session: string,
		  curated_at: time }

Task    { id : uuid,  # R98
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

Issue   { id: uuid,  # R99
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

Audit   { id: number,  # R100
          period: { from: time, to: time },
          summary: string,
          created_at: time }

cycle create  # R101
        { planner_session: string, 
		  headline: string, 
          tasks: [{ shortname, instructions, branch }] }

cycle curate  # R102
        { curator_session: string,
          report: string,
          tasks: [{ id, status: accepted|rejected }] }
```
**R103** State is stored in a database that supports transactions.
**R104** Sessions and Status reflect a point in time. 
**R105** Cycles, Tasks, Audits and Issues accumulate. **R106** They are kept for metrics and analysis, but are disposable. **R107** Only the operator decides when they are archived or removed, and may delegate this to an agent. **R108** Removal must not affect the current cycle, open issues, or active sessions.

### Phase Transitions
**R109** Planner session `done`: if the current cycle is open: `execute`, or `curate` if it has no tasks.
**R110** Worker session `done|expired`: if no tasks remain waiting or active: `curate`.
**R111** Curator session `done`: if the current cycle is not open: `plan`.
**R112** `loop start`: `plan`.
**R113** `loop resume`: if phase = plan: `curate`. Otherwise leave as is.

## Sessions
**R114** Agents and operators do their work in sessions.
When a session is instantiated, these are created:
- **R115** a session record
- **R116** a working directory
- **R117** git worktrees
- **R118** session branch for each worktree
**R119** When the agent finishes, the session status is set to done.
**R120** A session is considered inactive if its status is done or expired.
**R121** Sessions expire after a configurable amount of time.
**R122** Sessions are named `cycle#-planner|curator|worker#`, `auditor#`, or `operator-username`.
**R123** The assigned worker number is the number of existing workers in the cycle + 1.
**R124** The assigned auditor number is `Loop.last_audit` + 1.
**R125** The session name is used as that session's git branch across all repos.
**R126** A short, unique string of readable characters shall be appended to ensure branch uniqueness.
e.g. `cycle12-worker3-abcd1234`, `auditor123-abcd2345`, `operator-mars-abcd3456`.
**R127** Operator sessions can be interactive or one-shot.
**R128** Sessions are created by a deterministic script with exclusive file locking (flock) that takes a role argument.
**R129** The script first calls `msm session create <role>` which fails if preconditions are not met.
**R130** If session create succeeds, it attempts to create git branches, a working directory, and git worktrees.
**R131** If that fails, it removes the session record and any created branches or directories/files.
The script returns exit status:
- **R132** 0 for success, session created
- **R133** EPERM or EINVAL if `msm session create` fails
- **R134** 4 (EAGAIN) if the session name is already used by another git branch
- **R135** 5: git or worktree creation errors

## Dispatcher
**R136** The Dispatcher is invoked periodically, e.g. by cron, at an interval set in the configuration.
**R137** When the Dispatcher is invoked, it reads the loop state.
**R138** It checks for and expires timed out sessions.
**R139** If the loop is stopped, it exits.
**R140** If an inactive operator or Auditor session exists, it launches a Curator, whatever the phase.
Then, by phase:
  **R141** plan    -> launch Planner
  **R142** execute -> launch Workers while launches succeed, up to max workers active
  **R143** curate  -> launch Curator
**R144** Launches fail harmlessly if the role's preconditions are not met.
**R145** It launches an Auditor when the configured daily time, in the configured timezone, has passed and no audit has run since then, or when the configured number of cycles have been curated since the last audit. **R146** Either trigger can be disabled. **R147** The first Auditor runs only after a cycle has been curated.
**R148** To launch a role, it attempts to create a session. **R149** If it fails with EAGAIN (4) it tries again, up to 3 times.
**R150** If it succeeds it reads the role prompt.
**R151** It writes the role prompt to a file in the session directory, launches the agent through the configured launcher with the session name and prompt file path in its first message, and records the launcher's handle in the session.
**R152** The launcher is configured for the loop. **R153** The default process launcher runs an agent command, configured for the loop or specialised for each role:
**R154** `LOOP|PLANNER|WORKER|CURATOR|AUDITOR_AGENT=...`
`LOOP_AGENT="pi --no-session --name $SESSION -p $PROMPT"`
`LOOP_AGENT="claude --no-session-persistence --dangerously-skip-permissions -n $SESSION -p $PROMPT"`
`LOOP_AGENT="kiro-cli chat --trust-tools --no-interactive $PROMPT"`
`LOOP_AGENT="codex exec --ephemeral --sandbox $PROMPT"`

### Session Time-out
**R155** The Dispatcher times out sessions that have run longer than the configured limit. **R156** Operator sessions are never timed out.
**R157** It asks the launcher to stop the agent (process launcher: SIGTERM, a short grace period, then SIGKILL) and sets the session status to expired. **R158** If the launcher cannot confirm the agent stopped, the Dispatcher also creates a non-blocking operator escalation naming the session.
**R159** The Dispatcher may also expire sessions whose launcher reports them not running, after a start grace period. **R160** Sessions not launched by the Dispatcher have no handle.

Notes:
**R161** Expired Planners and Curators need no special rule. **R162** The phase hasn't moved, so the next dispatcher run relaunches them. **R163** The next Planner's `cycle create` replaces an open cycle.
**R164** A Curator that crashes before Publish leaves main unchanged, and the next Curator redoes the pass. **R165** One that crashes after Publish has already merged its work, so redoing the pass changes nothing. **R166** Sessions left by a crash after Publish are removed by the next Prepare.
**R167** The Curator doesn't wait for active operator and Auditor sessions to finish before launching.
**R168** A failing Planner or Curator is relaunched until it succeeds.

### Resume
**R169** Only the operator can resume a stopped loop: 
- **R170** start an operator session
- **R171** resolve blocking escalations, or update the goals
- **R172** set the operator session to done
- **R173** call `loop resume`

## Issues
**R174** There are two types of issues: Escalation, and Backlog.
**R175** Issues from unmerged work (expired, incomplete, or rejected) should reference its branch.

## Escalations
**R176** Issues can be escalated by any role to the Planner, Auditor or Curator.
**R177** Planner, Curator and Auditor can escalate to the operator.
**R178** The escalation prompt tells agents how to write an operator escalation.

## Backlog
**R179** Agents and operators can create backlog items.
**R180** There may be a backlog summary in BACKLOG.md. Planner keeps it current.
**R181** If the backlog reaches a certain size, the planner shall prioritise backlog items or prune them.
**R182** Backlog items should indicate under what conditions they become urgent.
**R183** Issues should not be created without first searching for existing, similar issues.

## Planner
**R184** It is launched with its session name. **R185** It reads its session.
**R186** It reads the plan, open backlog items, and the last curator report.
**R187** It reads open escalations.
**R188** It may resolve escalations.
**R189** It may consolidate, reprioritise, or prune the backlog.
**R190** It updates the plan and decides the headline (focus/goal/purpose of cycle).
**R191** It plans the cycle tasks.
**R192** It may plan tasks from backlog items:
- **R193** if the item has a branch, rebase it on the Planner branch and use as the task branch
- **R194** resolve the item
**R195** It creates a new cycle with headline and tasks, or empty if there is no work to do.
**R196** It sets its session to done (sets phase = execute, or curate if there are no tasks).

## Worker
**R197** It is launched with its session name. **R198** It reads its session and its task.
**R199** In each repo, it rebases its session branch on the task's base branch: the Planner session for new tasks, or a backlog item's branch for continuations. **R200** It then sets the task's `branch` field to its session name.
**R201** The worker agent performs the work in the worktree, and commits to the session branch.
**R202** When finished, it sets the session to done (this also sets the task to done).

## Curator
**R203** The Curator agent runs these steps in order. **R204** Steps marked (script) are deterministic scripts that it calls. **R205** Scripts refuse to run unless the Curator session is active.
**R206** Scripts never remove branches referenced by open issues.

**R207** Step 1: Prepare (script `curate-prepare`)
**R208** It removes done Curator sessions, and expired Curator and Planner sessions, with their worktrees and branches.
**R209** It removes sessions left over from closed cycles, with their worktrees and branches.

**R210** Step 2: Select (script `curate-select`)
**R211** It selects and returns the sessions to curate:
- **R212** if they exist: inactive operator and Auditor sessions
- **R213** else if phase = curate: the current, open cycle's inactive Planner and Worker sessions
- **R214** else: nothing
**R215** If the selection is empty, the Curator skips to Step 8: Assess.
Note: Selection makes sure that operator and Auditor work is curated as soon as it is done, whatever the phase. The cycle is then curated with fresh context, in its own pass, against updated goals and prompts.

**R216** Step 3: Merge (script `curate-merge`)
**R217** `curate-merge <item>...` updates the Curator branch in every repo to main plus the given items. **R218** An item is a session name or a commit. **R219** The Curator's own commits are kept.
**R220** The agent always passes the full list. **R221** Leaving an item out removes it; the branch is rebuilt and resolutions already made are replayed.
**R222** In case of conflicts the script stops with that repo mid-merge, and prints the conflict details and suggested resolution steps.
**R223** When rerun, it continues where it stopped: it completes a merge in progress once no conflict markers remain, and keeps a merge the agent completed itself.

**R224** Step 4: Triage
**R225** The agent merges the done sessions, then triages expired sessions:
- **R226** complete work is added to the list; the agent may leave it out if its conflicts aren't worth resolving
- **R227** incomplete work is either backlogged or discarded

**R228** Step 5: Read
**R229** It reads the plan, goals, open escalations, the current cycle, and audits since the cycle was planned.

**R230** Step 6: Evaluate
For each done or included expired Worker session:
- **R231** read the associated task
- **R232** review commits and diffs against goals and task instructions
- **R233** accept or reject the task, in whole or in part
**R234** It re-runs `curate-merge` with only the accepted sessions and commits.

**R235** Step 7: Validate
**R236** It runs the validation gates listed in config.env.
If any gate fails:
- **R237** identify the responsible work
- **R238** it may make and commit small fixes
- **R239** call `curate-merge` with only accepted work
- **R240** re-validate
**R241** If operator work is rejected then the failure shall be escalated to the operator.
**R242** If other work is rejected then it shall be either backlogged or discarded.

**R243** Step 8: Assess
**R244** It evaluates milestones, goals and deliverables
**R245** It may update the plan and backlog.
**R246** It may resolve escalations.
**R247** If the project is done, or `Loop.empty_cycles` has reached the idle limit from config.env, create a blocking operator escalation with reason `done` or `idle`.
**R248** If there are blocking operator escalations, notify the operator.

**R249** Step 9: Publish (script `curate-publish`)
**R250** The script fast-forwards main onto the Curator branch in each project repo, then in the loop repo.
If the selection includes a Planner session:
- **R251** run `cycle curate` with the report and the task verdicts.
**R252** The agent passes any task verdicts and the cycle report as arguments. **R253** It publishes even if nothing was selected, so that its own plan and backlog updates reach main.

**R254** Step 10: Cleanup (script `curate-cleanup`)
**R255** It updates central worktrees.
**R256** It removes the selected sessions with their worktrees and branches.

**R257** Step 11: Exit
**R258** If there are blocking operator escalations, it calls `loop stop blocked`.
**R259** It sets the Curator session to done (phase = plan if the cycle is not open).

## Auditor
**R260** It is launched with its session name. **R261** It reads its session.
**R262** It reads its prompt and the last audit.
**R263** It reads previous learnings from LEARNINGS.md.
**R264** It reads any open escalations.
**R265** It retrieves a git log summary since last audit.
**R266** It analyses git history for time spent per role and cycle.
**R267** It may analyse agent harness metrics for tokens or credits used per role and cycle.
**R268** It retrieves the sizes and growth of prompt files.
**R269** It evaluates progress against the goals, deliverables and plan.
**R270** It looks for recurring expired tasks, and long-running or expired sessions.
**R271** It may trim files by summarizing, culling or archiving.
**R272** It may remove merged git branches.
**R273** It may update role prompts.
**R274** It may instruct the planner to make smaller or bigger tasks with fewer or more parallel workers.
**R275** It may instruct the Curator to relax or tighten validation criteria.
**R276** It may clarify definitions of done, e.g. for deliverables, milestones, goals.
**R277** It may create scripts to automate common agent tasks.
**R278** It may resolve open escalations.
**R279** If it can fix a problem itself, it does so. If not, it may create backlog items or escalations.
**R280** It may add to LEARNINGS.md if the learnings are general.
**R281** It stores an audit report in the database.
**R282** The Auditor will not run until the previous audit has been curated.

## Prompts
**R283** Every role and some actions (Kickoff, Session, Status, Escalation) has a prompt. **R284** Most prompts can and should be adapted to the project either during Kickoff, or while the loop is running: by the auditor, curator or planner, or operator sessions.

## Agent Files
**R285** Files can be used for agents to communicate, for example for workers to save research.
**R286** What type of files that agents may produce, and where, is determined during kickoff.

## Kickoff
**R287** The operator runs Kickoff (`10km kickoff`) before the loop starts.
**R288** Kickoff can be interactive, or a one-shot operator instruction.
**R289** It creates no session and runs directly in the central working directory.
**R290** It calls `msm init` if there is not already a database.
**R291** It determines the goals, the plan, the deliverables and the configuration, and commits them to loop main.
**R292** It determines the project repos and their configuration: branch, author, hooks, remotes etc.
**R293** It clones or creates the central project worktrees and configures them with `git config`.
**R294** It ensures that loop prompts meet the project needs.
**R295** It should leave the central worktrees clean.
**R296** When done, kickoff calls `loop start`, and the first Planner runs.

## Notification
**R297** The operator notification mechanism should be a deterministic action configured during Kickoff.
**R298** The default notification is to append to NOTIFICATIONS.md in the central loop worktree. **R299** The file is gitignored, so notifications are immediate and don't depend on a merge.
**R300** Unless given other instructions, the loop only notifies the operator of blocking escalations and fatal errors.

# Test Scripts
**R301** Replace agent command with test invocation: `LOOP_AGENT=test.sh $SESSION`
**R302** Test reads next item from script, checks the role, runs command.
**R303** If next item is 'verify', runs it and checks result.
**R304** planner: msm cycle create {...}
**R305** planner: msm session done $SESSION
**R306** worker: msm task update --session $SESSION {report: ...}
**R307** worker: msm session done $SESSION
**R308** verify: msm task get --session $SESSION == {status:done, report: ...}
**R309** curator: msm cycle curate {...}
**R310** curator: msm session done $SESSION
**R311** verify: msm cycle get 1 == {report: ...}
